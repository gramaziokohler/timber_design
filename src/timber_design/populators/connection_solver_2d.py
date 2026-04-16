from __future__ import annotations

from itertools import combinations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from compas.geometry import Point
from compas.geometry import Vector
from compas.geometry import dot_vectors
from compas.geometry import intersection_segment_segment
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
    # type: (Union[Beam2D, PopulatorAgent], Union[Beam2D, PopulatorAgent], float) -> bool
    """Return ``True`` if the axis-aligned bounding boxes of the two beam blanks overlap in XY.

    Parameters
    ----------
    a, b : :class:`~timber_design.populators.Beam2D` or PopulatorAgent
    tolerance : float
        Each AABB is expanded by this amount in every direction before the
        overlap test.  Use a small positive value (e.g. the model tolerance)
        so that beams whose blanks merely *touch* are still considered
        overlapping.
    """
    print("a", a, a.aabb)
    print("b", b, b.aabb)
    if not (a.aabb and b.aabb):
        return False
    return (
        a.aabb.xmax + tolerance >= b.aabb.xmin - tolerance
        and b.aabb.xmax + tolerance >= a.aabb.xmin - tolerance
        and a.aabb.ymax + tolerance >= b.aabb.ymin - tolerance
        and b.aabb.ymax + tolerance >= a.aabb.ymin - tolerance
    )


def aabb_overlap_x(a, b, tolerance=0.0):
    # type: (Union[Beam2D, PopulatorAgent], Union[Beam2D, PopulatorAgent], float) -> bool
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
        agents : list[:class:`~timber_design.populators.populator_agents.PopulatorAgent`]

        Yields
        ------
        tuple[:class:`~timber_design.populators.PopulatorAgent`, :class:`~timber_design.populators.PopulatorAgent`]
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
                test=pts
                + [beam_a.edge_a.start, beam_a.edge_a.end, beam_a.edge_b.start, beam_a.edge_b.end]
                + [beam_b.edge_a.start, beam_b.edge_a.end, beam_b.edge_b.start, beam_b.edge_b.end],
            )
        return None


class Beam2DSolverResult:
    def __init__(self, beam_a, beam_b, distance, topology, location, test=None):
        self.beam_a = beam_a
        self.beam_b = beam_b
        self.distance = distance
        self.topology = topology
        self.location = location
        self.test = test
