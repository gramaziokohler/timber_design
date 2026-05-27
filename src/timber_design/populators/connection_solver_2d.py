from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from compas.geometry import Point
from compas.geometry import Vector
from compas.geometry import dot_vectors
from compas.geometry import intersection_segment_segment
from compas.tolerance import TOL
from compas_timber.connections.solver import JointTopology

# =============================================================================
# Internal helpers
# =============================================================================


def _average_point(points):
    # type: (list[Point]) -> Point
    n = len(points)
    return Point(
        sum(p.x for p in points) / n,
        sum(p.y for p in points) / n,
        sum(p.z for p in points) / n,
    )


def aabb_overlap(a, b, tolerance=0.0):
    # type: (Union[Beam2D, LayerAgent], Union[Beam2D, LayerAgent], float) -> bool
    """Return ``True`` if the axis-aligned bounding boxes of the two beam blanks overlap in XY.

    Parameters
    ----------
    a, b : :class:`~timber_design.populators.Beam2D` or LayerAgent
    tolerance : float
        Each AABB is expanded by this amount in every direction before the
        overlap test.  Use a small positive value (e.g. the model tolerance)
        so that beams whose blanks merely *touch* are still considered
        overlapping.
    """
    if not (a.aabb and b.aabb):
        return False
    return (
        a.aabb.xmax + tolerance >= b.aabb.xmin - tolerance
        and b.aabb.xmax + tolerance >= a.aabb.xmin - tolerance
        and a.aabb.ymax + tolerance >= b.aabb.ymin - tolerance
        and b.aabb.ymax + tolerance >= a.aabb.ymin - tolerance
    )


def aabb_overlap_x(a, b, tolerance=0.0):
    # type: (Union[Beam2D, LayerAgent], Union[Beam2D, LayerAgent], float) -> bool
    """Return ``True`` if the element AABBs of two agents overlap in X.

    Parameters
    ----------
    tolerance : float
        Expand each AABB by this amount before the overlap test.
    """
    if not (a.aabb and b.aabb):
        return False
    return a.aabb.xmax + tolerance >= b.aabb.xmin - tolerance and b.aabb.xmax + tolerance >= a.aabb.xmin - tolerance


# =============================================================================
# ConnectionSolver2D
# =============================================================================


class ConnectionSolver2D(object):
    """2D blank-outline-aware solver for beam adjacency and topology detection.

    Mirrors the interface of :class:`~compas_timber.connections.ConnectionSolver`
    but uses endpoint-containment tests on :class:`~timber_design.populators.Beam2D`
    blank outlines instead of 3D centerline distance.

    Parameters
    ----------
    max_distance : float
        Maximum gap between two AABBs that is still considered overlapping.
        Defaults to ``1.0`` so that beams whose blanks merely *touch* (or are
        very slightly apart due to floating-point drift) are still paired.
        Pass ``0.0`` for strict overlap only.

    Usage
    -----
    Typical two-step usage::

        solver = ConnectionSolver2D()
        for beam_a, beam_b in solver.find_intersecting_pairs(beams):
            candidate = solver.find_topology(beam_a, beam_b)
            if candidate:
                model.add_joint_candidate(candidate)

    For agent-level pre-filtering::

        for agent_a, agent_b in solver.find_intersecting_agent_pairs(agents):
            for beam_a, beam_b in product(agent_a.elements, agent_b.elements):
                candidate = solver.find_topology(beam_a, beam_b)
                if candidate:
                    model.add_joint_candidate(candidate)
    """

    def __init__(self, max_distance=1.0):
        # type: (float) -> None
        self.max_distance = max_distance

    def find_intersecting_pairs(self, beams):
        """Yield ``(beam_a, beam_b)`` pairs from *beams* whose blank AABBs overlap.

        Pairs whose AABBs are within :attr:`max_distance` of each other are
        also included so that touching/near-touching beams are not missed.

        Parameters
        ----------
        beams : list[:class:`~timber_design.populators.Beam2D`]

        Yields
        ------
        tuple[:class:`~timber_design.populators.Beam2D`, :class:`~timber_design.populators.Beam2D`]
        """
        for beam_a, beam_b in combinations(beams, 2):
            if beam_a.is_beam and beam_b.is_beam:
                if aabb_overlap(beam_a, beam_b, tolerance=self.max_distance):
                    yield beam_a, beam_b

    def find_intersecting_agent_pairs(self, agents):
        """Yield ``(agent_a, agent_b)`` pairs from *agents* whose element AABBs overlap.

        Pairs whose AABBs are within :attr:`max_distance` of each other are
        also included so that adjacent agents are not missed.

        Parameters
        ----------
        agents : list[:class:`~timber_design.populators.populator_agents.LayerAgent`]

        Yields
        ------
        tuple[:class:`~timber_design.populators.LayerAgent`, :class:`~timber_design.populators.LayerAgent`]
        """
        for agent_a, agent_b in combinations(agents, 2):
            if aabb_overlap(agent_a, agent_b, tolerance=self.max_distance):
                yield agent_a, agent_b

    def find_topology(self, beam_a, beam_b):
        """Return the 2D blank-overlap topology between *beam_a* and *beam_b*.

        Determines topology via endpoint-containment tests on the four blank
        corners of each beam (``edge_a.start/end`` and ``edge_b.start/end``):

        - **TOPO_L**: corners of *both* beams lie inside the other beam's blank.
        - **TOPO_T**: corners of only *one* beam lie inside the other.
          ``element_a`` of the returned candidate is always the *end* beam.
        - **TOPO_X**: no corners inside either beam; overlap detected via
          edge-edge crossings of the blank outlines.

        Parameters
        ----------
        beam_a : :class:`~timber_design.populators.Beam2D`
        beam_b : :class:`~timber_design.populators.Beam2D`

        Returns
        -------
        :class:`~compas_timber.connections.JointCandidate` | None
            ``None`` when the blanks do not overlap.
        """
        if not all([b.is_beam for b in [beam_a, beam_b]]):
            return None
        if not aabb_overlap(beam_a, beam_b, tolerance=self.max_distance):
            return None

        a_corners = [beam_a.edge_a.start, beam_a.edge_a.end, beam_a.edge_b.start, beam_a.edge_b.end]
        b_corners = [beam_b.edge_a.start, beam_b.edge_a.end, beam_b.edge_b.start, beam_b.edge_b.end]
        a_in_b = [pt for pt in a_corners if beam_b.contains_point(pt)]
        b_in_a = [pt for pt in b_corners if beam_a.contains_point(pt)]

        if a_in_b and b_in_a:
            # L-joint: both beams have blank corners inside each other
            location = _average_point(a_in_b + b_in_a)
            return Beam2DSolverResult(beam_a=beam_a, beam_b=beam_b, distance=0.0, topology=JointTopology.TOPO_L, location=location)
        if a_in_b:
            # T-joint: beam_a is the end beam
            location = _average_point(a_in_b)
            return Beam2DSolverResult(beam_a=beam_a, beam_b=beam_b, distance=0.0, topology=JointTopology.TOPO_T, location=location)
        if b_in_a:
            # T-joint: beam_b is the end beam — normalise so element_a is always the end beam
            location = _average_point(b_in_a)
            return Beam2DSolverResult(beam_a=beam_b, beam_b=beam_a, distance=0.0, topology=JointTopology.TOPO_T, location=location)

        # Check for face-to-face: parallel beams sharing a colinear long edge.
        # Conditions:
        #   1. Beam directions are parallel (|dot| ≈ 1).
        #   2. Any long edge of beam_a is colinear with any long edge of beam_b,
        #      i.e. the perpendicular distance between the two edge lines is
        #      within tolerance (the component of the inter-start vector that is
        #      orthogonal to the beam axis is negligible).
        if abs(abs(dot_vectors(beam_a.frame.xaxis, beam_b.frame.xaxis)) - 1.0) < 0.01:
            long_edges_a = [beam_a.edge_a, beam_a.edge_b]
            long_edges_b = [beam_b.edge_a, beam_b.edge_b]
            for ea in long_edges_a:
                for eb in long_edges_b:
                    inter_vec = Vector.from_start_end(ea.start, eb.start)
                    along = dot_vectors(inter_vec, beam_a.frame.xaxis)
                    perp = Vector(
                        inter_vec.x - beam_a.frame.xaxis[0] * along,
                        inter_vec.y - beam_a.frame.xaxis[1] * along,
                        inter_vec.z - beam_a.frame.xaxis[2] * along,
                    )
                    if perp.length <= self.max_distance:
                        location = _average_point([ea.start, ea.end, eb.start, eb.end])
                        return Beam2DSolverResult(
                            beam_a=beam_a,
                            beam_b=beam_b,
                            distance=perp.length,
                            topology=JointTopology.TOPO_FACE_FACE,
                            location=location,
                        )

        # No endpoints inside — look for edge-edge crossings (TOPO_X)
        pts = []
        for seg_a in beam_a.blank_outline.lines:
            for seg_b in beam_b.blank_outline.lines:
                result = intersection_segment_segment(seg_a, seg_b)
                if result[0]:
                    pts.append(Point(*result[0]))
        if pts:
            location = _average_point(pts)
            return Beam2DSolverResult(
                beam_a=beam_a,
                beam_b=beam_b,
                distance=0.0,
                topology=JointTopology.TOPO_X,
                location=location,
            )
        return None

    # =====================================================================
    # Occlusion-aware contact detection (perimeter walk)
    # =====================================================================

    def find_beam_contacts(self, beam, others):
        """Return the *actual* physical contacts of ``beam`` with ``others``.

        Walks each of ``beam``'s four blank edges and, for every edge, finds the
        *nearest* neighbour blank outward of that edge.  Because only the nearest
        beam along each stretch of the perimeter is reported, a beam that is
        occluded by a closer beam (e.g. ``a``–``c`` when ``b`` sits between them)
        never produces a spurious contact.

        Each contact records, for both beams, whether the contact lands on an
        **end** (an end-cap segment) or in the **middle** (a long face) — the
        information needed to classify L/I/T pairwise and Y/K at the cluster
        level.

        Parameters
        ----------
        beam : :class:`~timber_design.populators.Beam2D`
        others : list[:class:`~timber_design.populators.Beam2D`]

        Returns
        -------
        list[:class:`BeamContact`]
        """
        contacts = []
        for edge_index in range(4):
            role_a, end_a = _EDGE_ROLE[edge_index]
            for other, location in self._edge_contacts(beam, edge_index, others):
                end_band = min(other.width, max(other.length * 0.5 - TOL.absolute, 0.0))
                role_b, end_b = self._role_at_point(other, location, max(end_band, beam.width))
                topology = self._pairwise_topology(beam, other, role_a, role_b)
                contacts.append(BeamContact(beam, other, role_a, role_b, end_a, end_b, location, topology))
        return contacts

    def find_all_contacts(self, beams):
        """Return the deduplicated set of contacts among all ``beams``.

        Every beam is walked (so occlusion is resolved with full context), but a
        contact between a given pair is reported only once.

        Parameters
        ----------
        beams : list[:class:`~timber_design.populators.Beam2D`]

        Returns
        -------
        list[:class:`BeamContact`]
        """
        cell = max(self.max_distance, 1.0)
        seen = set()
        contacts = []
        for beam in beams:
            others = [b for b in beams if b is not beam]
            for contact in self.find_beam_contacts(beam, others):
                key = (
                    frozenset((id(contact.beam_a), id(contact.beam_b))),
                    round(contact.location.x / cell),
                    round(contact.location.y / cell),
                )
                if key in seen:
                    continue
                seen.add(key)
                contacts.append(contact)
        return contacts

    def cluster_contacts(self, contacts):
        """Group contacts that share a beam *port* into :class:`Beam2DCluster` objects.

        Two contacts belong to the same cluster when they share a port:

        - an **end** port — the same beam joined at the same end (``"start"`` /
          ``"end"``).  Matched exactly, so a thickness offset between the meeting
          beams never splits a corner joint.
        - a **middle** port — the same beam joined through its length, where the
          two contact footprints **overlap** along that beam's axis.

        Parameters
        ----------
        contacts : list[:class:`BeamContact`]

        Returns
        -------
        list[:class:`Beam2DCluster`]
        """
        parent = list(range(len(contacts)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def union(i, j):
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[rj] = ri

        end_first = {}  # (id(beam), end) -> first contact index
        middle_ports = defaultdict(list)  # id(beam) -> list of (index, start, end) intervals
        for idx, contact in enumerate(contacts):
            for beam, role, end, other in (
                (contact.beam_a, contact.role_a, contact.end_a, contact.beam_b),
                (contact.beam_b, contact.role_b, contact.end_b, contact.beam_a),
            ):
                if role == "end":
                    key = (id(beam), end)
                    if key in end_first:
                        union(idx, end_first[key])
                    else:
                        end_first[key] = idx
                else:
                    center = dot_vectors(Vector.from_start_end(beam.frame.point, contact.location), beam.frame.xaxis)
                    half = max(other.width, beam.width) * 0.5
                    middle_ports[id(beam)].append((idx, center - half, center + half))

        # Merge overlapping middle-port footprints on each beam.
        for items in middle_ports.values():
            items.sort(key=lambda t: t[1])
            for (i0, _s0, e0), (i1, s1, _e1) in zip(items, items[1:]):
                if s1 <= e0:  # intervals overlap along the beam axis
                    union(i0, i1)

        groups = defaultdict(list)
        for idx, contact in enumerate(contacts):
            groups[find(idx)].append(contact)
        return [Beam2DCluster(group) for group in groups.values()]

    # ------------------------------------------------------------------
    # Contact-detection helpers
    # ------------------------------------------------------------------

    def _edge_contacts(self, beam, edge_index, others):
        """Yield ``(other, location)`` for the nearest neighbour along each stretch of one blank edge."""
        edge = beam.blank_outline.lines[edge_index]
        along_vec = Vector.from_start_end(edge.start, edge.end)
        edge_len = along_vec.length
        if edge_len < TOL.absolute:
            return []
        along = along_vec.unitized()
        outward = self._outward_normal(beam, edge_index)
        origin = edge.start
        md = self.max_distance

        # Candidate intervals: each neighbour that faces this edge from outside.
        candidates = []  # (other, s0, s1, distance)
        for other in others:
            corners = [other.edge_a.start, other.edge_a.end, other.edge_b.start, other.edge_b.end]
            along_coords = [dot_vectors(Vector.from_start_end(origin, c), along) for c in corners]
            out_coords = [dot_vectors(Vector.from_start_end(origin, c), outward) for c in corners]
            s0 = max(0.0, min(along_coords))
            s1 = min(edge_len, max(along_coords))
            if s1 - s0 <= TOL.absolute:
                continue  # no overlap along this edge
            h_near = min(out_coords)
            h_far = max(out_coords)
            if h_near > md:
                continue  # entirely beyond reach, outward
            if h_far < -md:
                continue  # entirely behind the edge (inside the beam) — not facing outward
            candidates.append((other, s0, s1, max(0.0, h_near)))

        if not candidates:
            return []

        # Occlusion: along the edge, the nearest candidate owns each sub-interval.
        breaks = sorted({0.0, edge_len} | {s for (_o, s0, s1, _d) in candidates for s in (s0, s1)})
        owned = []  # (other, b0, b1)
        for b0, b1 in zip(breaks, breaks[1:]):
            if b1 - b0 <= TOL.absolute:
                continue
            mid = 0.5 * (b0 + b1)
            covering = [c for c in candidates if c[1] - TOL.absolute <= mid <= c[2] + TOL.absolute]
            if not covering:
                continue
            nearest = min(covering, key=lambda c: c[3])
            if owned and owned[-1][0] is nearest[0]:
                owned[-1] = (nearest[0], owned[-1][1], b1)  # merge adjacent same-owner stretch
            else:
                owned.append((nearest[0], b0, b1))

        results = []
        for other, b0, b1 in owned:
            location = Point(*(origin + along * (0.5 * (b0 + b1))))
            results.append((other, location))
        return results

    @staticmethod
    def _outward_normal(beam, edge_index):
        """Unit outward normal of ``beam``'s blank edge ``edge_index`` (CCW blank)."""
        return {
            0: beam.frame.yaxis * -1.0,  # -y long face
            1: beam.frame.xaxis,         # end cap (beam end)
            2: beam.frame.yaxis,         # +y long face
            3: beam.frame.xaxis * -1.0,  # start cap (beam start)
        }[edge_index]

    @staticmethod
    def _role_at_point(beam, point, end_band):
        """Classify whether ``point`` meets ``beam`` at an end or its middle (tie → end)."""
        along = dot_vectors(Vector.from_start_end(beam.frame.point, point), beam.frame.xaxis)
        end_band = min(end_band, beam.length * 0.5)
        if along <= end_band:
            return "end", "start"
        if along >= beam.length - end_band:
            return "end", "end"
        return "middle", None

    @staticmethod
    def _pairwise_topology(beam_a, beam_b, role_a, role_b):
        """Pairwise topology from the two beams' end/middle roles."""
        if role_a == "end" and role_b == "end":
            parallel = abs(abs(dot_vectors(beam_a.frame.xaxis, beam_b.frame.xaxis)) - 1.0) < 0.01
            return JointTopology.TOPO_I if parallel else JointTopology.TOPO_L
        if role_a == "end" or role_b == "end":
            return JointTopology.TOPO_T
        return JointTopology.TOPO_X


class Beam2DSolverResult:
    def __init__(self, beam_a, beam_b, distance, topology, location):
        self.beam_a = beam_a
        self.beam_b = beam_b
        self.distance = distance
        self.topology = topology
        self.location = location


# blank_outline.lines index -> (role, end-name).  End caps carry an end name;
# long faces are "middle" contacts.
#   0  bl→br  long face (-y)
#   1  br→tr  end cap at the beam end
#   2  tr→tl  long face (+y)
#   3  tl→bl  start cap at the beam start
_EDGE_ROLE = {
    0: ("middle", None),
    1: ("end", "end"),
    2: ("middle", None),
    3: ("end", "start"),
}


class BeamContact:
    """A resolved physical contact between two :class:`Beam2D` blanks.

    Produced by :meth:`ConnectionSolver2D.find_beam_contacts`, so a contact only
    exists where the two blanks actually meet — a beam occluded by a nearer beam
    does not generate one.

    Attributes
    ----------
    beam_a, beam_b : :class:`~timber_design.populators.Beam2D`
        The two beams in contact.  ``beam_a`` is the beam whose perimeter was
        walked to find this contact.
    role_a, role_b : str
        ``"end"`` or ``"middle"`` — whether each beam meets the contact at one of
        its ends or through its length.
    end_a, end_b : str or None
        ``"start"`` / ``"end"`` when the corresponding role is ``"end"``; else
        ``None``.
    location : :class:`~compas.geometry.Point`
        Approximate contact point, used as the cluster location.
    topology : int
        Pairwise :class:`~compas_timber.connections.JointTopology`
        (``TOPO_L`` / ``TOPO_I`` / ``TOPO_T`` / ``TOPO_X``).
    """

    def __init__(self, beam_a, beam_b, role_a, role_b, end_a, end_b, location, topology):
        self.beam_a = beam_a
        self.beam_b = beam_b
        self.role_a = role_a
        self.role_b = role_b
        self.end_a = end_a
        self.end_b = end_b
        self.location = location
        self.topology = topology

    def __repr__(self):
        return "BeamContact({}, a={}/{}, b={}/{})".format(
            JointTopology.get_name(self.topology), self.role_a, self.end_a, self.role_b, self.end_b
        )

    def role_for(self, beam):
        """Return ``"end"``/``"middle"`` for *beam* (one of the two contact beams)."""
        return self.role_a if beam is self.beam_a else self.role_b


class Beam2DCluster:
    """A group of :class:`BeamContact` objects that meet at one location.

    Built by :meth:`ConnectionSolver2D.cluster_contacts`.  The cluster
    :attr:`topology` is derived from the *roles* of its member beams, which is
    the literal definition of Y vs K: Y when every beam meets at an end, K when
    at least one beam is met through its middle.

    Attributes
    ----------
    contacts : list[:class:`BeamContact`]
        The pairwise contacts in this cluster.
    """

    def __init__(self, contacts):
        self.contacts = contacts

    def __repr__(self):
        return "Beam2DCluster({}, {} beams, {} contacts)".format(
            JointTopology.get_name(self.topology), len(self.beams), len(self.contacts)
        )

    @property
    def beams(self):
        """Unique beams in this cluster, in first-seen order."""
        seen_ids = set()
        result = []
        for contact in self.contacts:
            for beam in (contact.beam_a, contact.beam_b):
                if id(beam) not in seen_ids:
                    seen_ids.add(id(beam))
                    result.append(beam)
        return result

    @property
    def location(self):
        return self.contacts[0].location

    @property
    def topology(self):
        """Y/K from member roles; the pairwise topology for a 2-beam cluster."""
        beams = self.beams
        if len(beams) <= 2:
            return self.contacts[0].topology
        # 3+ beams: a beam met through its middle makes the joint a K, else Y.
        role_by_beam = {}
        for contact in self.contacts:
            for beam in (contact.beam_a, contact.beam_b):
                role = contact.role_for(beam)
                # "middle" sticks: once a beam is a through-beam anywhere in the
                # cluster, it stays a middle participant.
                if role_by_beam.get(id(beam)) != "middle":
                    role_by_beam[id(beam)] = role
        if any(role == "middle" for role in role_by_beam.values()):
            return JointTopology.TOPO_K
        return JointTopology.TOPO_Y
