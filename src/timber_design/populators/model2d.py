from __future__ import annotations

from itertools import combinations
from itertools import product
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from timber_design.populators.element_generators.element_generator import ElementGenerator

from compas.geometry import Point
from compas.geometry import Vector
from compas.geometry import dot_vectors
from compas.geometry import intersection_line_line_xy
from compas_timber.connections import Cluster
from compas_timber.connections import JointCandidate
from compas_timber.connections import get_clusters_from_joint_candidates
from compas_timber.connections.solver import JointTopology
from compas_timber.model import TimberModel

from timber_design.populators.beam2d import Beam2D
from timber_design.populators.generator_intersection import _get_beam_edge_outline_intersections


# =============================================================================
# Internal helpers
# =============================================================================


def _midpoint(points):
    # type: (list[Point]) -> Point
    n = len(points)
    return Point(
        sum(p.x for p in points) / n,
        sum(p.y for p in points) / n,
        sum(p.z for p in points) / n,
    )


def _aabb_overlap(beam_a, beam_b):
    # type: (Beam2D, Beam2D) -> bool
    """Return ``True`` if the axis-aligned bounding boxes of the two beam blanks overlap in XY."""
    pts_a = (beam_a.edge_a.start, beam_a.edge_a.end, beam_a.edge_b.start, beam_a.edge_b.end)
    pts_b = (beam_b.edge_a.start, beam_b.edge_a.end, beam_b.edge_b.start, beam_b.edge_b.end)
    a_xmin = min(p.x for p in pts_a)
    a_xmax = max(p.x for p in pts_a)
    a_ymin = min(p.y for p in pts_a)
    a_ymax = max(p.y for p in pts_a)
    b_xmin = min(p.x for p in pts_b)
    b_xmax = max(p.x for p in pts_b)
    b_ymin = min(p.y for p in pts_b)
    b_ymax = max(p.y for p in pts_b)
    return a_xmax >= b_xmin and b_xmax >= a_xmin and a_ymax >= b_ymin and b_ymax >= a_ymin


def _generators_aabb_overlap(gen_a, gen_b):
    # type: (ElementGenerator, ElementGenerator) -> bool
    """Return ``True`` if the element AABBs of two generators overlap in XY."""
    if not gen_a.elements or not gen_b.elements:
        return False
    a_pts = [pt for e in gen_a.elements for pt in e.aabb.points]
    b_pts = [pt for e in gen_b.elements for pt in e.aabb.points]
    a_xmin = min(p.x for p in a_pts)
    a_xmax = max(p.x for p in a_pts)
    a_ymin = min(p.y for p in a_pts)
    a_ymax = max(p.y for p in a_pts)
    b_xmin = min(p.x for p in b_pts)
    b_xmax = max(p.x for p in b_pts)
    b_ymin = min(p.y for p in b_pts)
    b_ymax = max(p.y for p in b_pts)
    return a_xmax >= b_xmin and b_xmax >= a_xmin and a_ymax >= b_ymin and b_ymax >= a_ymin


def _find_t_connection_extended(end_beam, face_beam, max_extension=None):
    # type: (Beam2D, Beam2D, float | None) -> Point | None
    """Return the connection location if *end_beam*'s edge lines, extended beyond
    their endpoints, intersect *face_beam*'s long blank edges within
    *face_beam*'s blank extents.

    This handles beams that have been trimmed flush with the adjacent beam's
    outer face by :func:`~timber_design.populators.split_beam_with_element_generators`,
    leaving no blank-corner overlap for the normal containment test.

    Parameters
    ----------
    end_beam : :class:`~timber_design.populators.Beam2D`
        The beam whose edge lines are extended.
    face_beam : :class:`~timber_design.populators.Beam2D`
        The beam whose long blank edges are tested against.
    max_extension : float, optional
        Maximum distance beyond *end_beam*'s endpoints to search.
        Defaults to ``face_beam.width``.

    Returns
    -------
    :class:`compas.geometry.Point` | None
        Midpoint of all found intersection points, or ``None`` if none are found.
    """
    if max_extension is None:
        max_extension = face_beam.width

    pts = []
    for src_edge in (end_beam.edge_a, end_beam.edge_b):
        for tgt_edge in (face_beam.edge_a, face_beam.edge_b):
            result = intersection_line_line_xy(src_edge, tgt_edge)
            if result is None:
                continue
            pt = Point(*result)

            # Must lie within face_beam's blank extent along its length
            vec_tgt = Vector.from_start_end(face_beam.frame.point, pt)
            along_tgt = dot_vectors(vec_tgt, face_beam.frame.xaxis)
            if not (0.0 <= along_tgt <= face_beam.length):
                continue

            # Must be at or within max_extension outside one of end_beam's ends
            # (not somewhere along the middle of end_beam)
            vec_src = Vector.from_start_end(end_beam.frame.point, pt)
            along_src = dot_vectors(vec_src, end_beam.frame.xaxis)
            near_start = -max_extension <= along_src <= 0.0
            near_end = end_beam.length <= along_src <= end_beam.length + max_extension
            if near_start or near_end:
                pts.append(pt)

    return _midpoint(pts) if pts else None


# =============================================================================
# ConnectionSolver2D
# =============================================================================


class ConnectionSolver2D(object):
    """2D blank-outline-aware solver for beam adjacency and topology detection.

    Mirrors the interface of :class:`~compas_timber.connections.ConnectionSolver`
    but uses endpoint-containment tests on :class:`~timber_design.populators.Beam2D`
    blank outlines instead of 3D centerline distance.

    Usage
    -----
    Typical two-step usage::

        solver = ConnectionSolver2D()
        for beam_a, beam_b in solver.find_intersecting_pairs(beams):
            candidate = solver.find_topology(beam_a, beam_b)
            if candidate:
                model.add_joint_candidate(candidate)

    For generator-level pre-filtering::

        for gen_a, gen_b in solver.find_intersecting_generator_pairs(generators):
            for beam_a, beam_b in product(gen_a.elements, gen_b.elements):
                candidate = solver.find_topology(beam_a, beam_b)
                if candidate:
                    model.add_joint_candidate(candidate)
    """

    def find_intersecting_pairs(self, beams):
        """Yield ``(beam_a, beam_b)`` pairs from *beams* whose blank AABBs overlap.

        Parameters
        ----------
        beams : list[:class:`~timber_design.populators.Beam2D`]

        Yields
        ------
        tuple[:class:`~timber_design.populators.Beam2D`, :class:`~timber_design.populators.Beam2D`]
        """
        for beam_a, beam_b in combinations(beams, 2):
            if _aabb_overlap(beam_a, beam_b):
                yield beam_a, beam_b

    def find_intersecting_generator_pairs(self, generators):
        """Yield ``(gen_a, gen_b)`` pairs from *generators* whose element AABBs overlap.

        Parameters
        ----------
        generators : list[:class:`~timber_design.populators.element_generators.ElementGenerator`]

        Yields
        ------
        tuple[ElementGenerator, ElementGenerator]
        """
        for gen_a, gen_b in combinations(generators, 2):
            if _generators_aabb_overlap(gen_a, gen_b):
                yield gen_a, gen_b

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
        if not _aabb_overlap(beam_a, beam_b):
            return None

        a_corners = [beam_a.edge_a.start, beam_a.edge_a.end, beam_a.edge_b.start, beam_a.edge_b.end]
        b_corners = [beam_b.edge_a.start, beam_b.edge_a.end, beam_b.edge_b.start, beam_b.edge_b.end]
        a_in_b = [pt for pt in a_corners if beam_b.contains_point(pt)]
        b_in_a = [pt for pt in b_corners if beam_a.contains_point(pt)]

        if not a_in_b and not b_in_a:
            # No endpoints inside — look for edge-edge crossings (TOPO_X)
            ints_a, ints_b = _get_beam_edge_outline_intersections(beam_a, beam_b.blank_outline)
            if ints_a or ints_b:
                location = _midpoint([i.point for i in ints_a + ints_b])
                return JointCandidate(element_a=beam_a, element_b=beam_b, topology=JointTopology.TOPO_X, location=location)

            # No direct overlap — try extending edge lines for beams that have been
            # trimmed flush with the adjacent beam's outer face.
            loc_a = _find_t_connection_extended(beam_a, beam_b)
            loc_b = _find_t_connection_extended(beam_b, beam_a)
            if loc_a is not None and loc_b is not None:
                return JointCandidate(element_a=beam_a, element_b=beam_b, topology=JointTopology.TOPO_L, location=_midpoint([loc_a, loc_b]))
            if loc_a is not None:
                return JointCandidate(element_a=beam_a, element_b=beam_b, topology=JointTopology.TOPO_T, location=loc_a)
            if loc_b is not None:
                return JointCandidate(element_a=beam_b, element_b=beam_a, topology=JointTopology.TOPO_T, location=loc_b)
            return None

        if a_in_b and b_in_a:
            # L-joint: both beams have blank corners inside each other
            location = _midpoint(a_in_b + b_in_a)
            return JointCandidate(element_a=beam_a, element_b=beam_b, topology=JointTopology.TOPO_L, location=location)

        if a_in_b:
            # T-joint: beam_a is the end beam
            location = _midpoint(a_in_b)
            return JointCandidate(element_a=beam_a, element_b=beam_b, topology=JointTopology.TOPO_T, location=location)

        # T-joint: beam_b is the end beam — normalise so element_a is always the end beam
        location = _midpoint(b_in_a)
        return JointCandidate(element_a=beam_b, element_b=beam_a, topology=JointTopology.TOPO_T, location=location)


def _other_beam(candidate, beam):
    # type: (JointCandidate, Beam2D) -> Beam2D
    """Return the beam in *candidate* that is not *beam*."""
    return candidate.element_b if candidate.element_a is beam else candidate.element_a


# =============================================================================
# Public cluster-building function
# =============================================================================


def find_beam_clusters(candidates, max_distance=None):
    # type: (list[JointCandidate], float | None) -> list[Cluster]
    """Classify pre-computed pairwise joint candidates into beam clusters.

    Expects candidates already produced by
    :meth:`~timber_design.populators.PanelPopulator.connect_overlapping_generators` — it does
    **not** recompute pairwise intersections.

    Uses :func:`~compas_timber.connections.get_clusters_from_joint_candidates`
    to spatially group candidates (``max_distance`` defaults to twice the
    widest beam), then applies 2D containment checks within each group:

    - *CORNER* (TOPO_Y / TOPO_K): the primary beam is the end beam in ≥2
      candidates in the group, and the two other beams are themselves
      directly connected (their pair candidate is also in the group).
    - *NOTCH* (TOPO_K): ≥2 beams end inside the primary beam, and those
      end beams are themselves directly connected.

    Candidates already consumed by a three-beam cluster are not returned as
    separate two-beam clusters.

    Parameters
    ----------
    candidates : list[:class:`~compas_timber.connections.JointCandidate`]
        Pre-computed pairwise candidates (e.g. from ``model.joint_candidates``).
    max_distance : float, optional
        Spatial grouping radius.  Defaults to twice the widest beam width
        found among the candidates' elements.

    Returns
    -------
    list[:class:`~compas_timber.connections.Cluster`]
    """
    if not candidates:
        return []

    if max_distance is None:
        max_distance = max(b.width for c in candidates for b in c.elements) * 2.0

    # ------------------------------------------------------------------
    # Spatial pre-clustering via KDTree
    # ------------------------------------------------------------------
    spatial_groups = get_clusters_from_joint_candidates(candidates, max_distance=max_distance)

    # ------------------------------------------------------------------
    # CORNER / NOTCH classification within each spatial group
    # ------------------------------------------------------------------
    seen_multi = set()  # frozenset of 3 beam ids for each confirmed multi-beam cluster
    result_clusters = []

    for group in spatial_groups:
        group_candidates = group.joints  # list[JointCandidate] in this spatial group

        if len(group_candidates) == 1:
            result_clusters.append(Cluster(group_candidates))
            continue

        # Beam-pair keys in this group — used to confirm b1↔b2 connectivity
        group_pair_keys = {frozenset([id(c.element_a), id(c.element_b)]) for c in group_candidates}
        group_beams = {c.element_a for c in group_candidates} | {c.element_b for c in group_candidates}

        for primary in group_beams:
            # Candidates where primary is the *end* beam
            end_cands = [
                c for c in group_candidates
                if c.topology in (JointTopology.TOPO_T, JointTopology.TOPO_L)
                and (c.topology == JointTopology.TOPO_L or c.element_a is primary)
            ]
            # Candidates where primary is the *face* beam (T only)
            face_cands = [
                c for c in group_candidates
                if c.topology == JointTopology.TOPO_T and c.element_b is primary
            ]

            # CORNER: primary ends into the junction of two connected beams
            for c1, c2 in combinations(end_cands, 2):
                b1 = _other_beam(c1, primary)
                b2 = _other_beam(c2, primary)
                if frozenset([id(b1), id(b2)]) not in group_pair_keys:
                    continue
                cluster_key = frozenset([id(primary), id(b1), id(b2)])
                if cluster_key not in seen_multi:
                    seen_multi.add(cluster_key)
                    result_clusters.append(Cluster([c1, c2]))

            # NOTCH: two connected beams both terminate inside primary
            for c1, c2 in combinations(face_cands, 2):
                b1, b2 = c1.element_a, c2.element_a
                if frozenset([id(b1), id(b2)]) not in group_pair_keys:
                    continue
                cluster_key = frozenset([id(primary), id(b1), id(b2)])
                if cluster_key not in seen_multi:
                    seen_multi.add(cluster_key)
                    result_clusters.append(Cluster([c1, c2]))

        # Remaining candidates not consumed by a multi-beam cluster
        for cand in group_candidates:
            pair_key = frozenset([id(cand.element_a), id(cand.element_b)])
            if not any(pair_key.issubset(mk) for mk in seen_multi):
                result_clusters.append(Cluster([cand]))

    return result_clusters


# =============================================================================
# Model2D
# =============================================================================


class Model2D(TimberModel):
    """A :class:`~compas_timber.model.TimberModel` with 2D blank-outline-aware beam adjacency detection.

    Overrides :meth:`connect_adjacent_beams` to use endpoint-containment tests
    on each :class:`~timber_design.populators.Beam2D` blank outline instead of
    3D centerline distance.  All downstream machinery (joint creation,
    :meth:`process_joinery`, etc.) is inherited unchanged.

    When used inside a :class:`~timber_design.populators.PanelPopulator`, prefer
    :meth:`~timber_design.populators.PanelPopulator.connect_overlapping_generators`
    which uses generator-level AABB pre-filtering.  For standalone use, call
    :meth:`connect_adjacent_beams` directly.

    Beam clusters can be retrieved via :attr:`joint_clusters` after candidates
    have been populated.
    """

    @property
    def joint_clusters(self):
        """Return beam clusters from pre-computed joint candidates.

        Returns
        -------
        list[:class:`~compas_timber.connections.Cluster`]
        """
        return find_beam_clusters(list(self.joint_candidates))

    def connect_adjacent_beams(self, max_distance=None):
        """Populate joint candidates for all :class:`~timber_design.populators.Beam2D` elements in the model.

        Replaces the 3D centerline-distance approach of the base class with
        2D blank-outline containment tests.  Use
        :meth:`~timber_design.populators.PanelPopulator.connect_overlapping_generators`
        instead when element generators are available, as it applies a faster
        generator-level AABB pre-filter.

        Parameters
        ----------
        max_distance : float, optional
            Not used — kept for API compatibility with the base class.
        """
        for candidate in list(self.joint_candidates):
            self.remove_joint_candidate(candidate)

        solver = ConnectionSolver2D()
        beams = [e for e in self.elements() if isinstance(e, Beam2D)]
        for beam_a, beam_b in solver.find_intersecting_pairs(beams):
            candidate = solver.find_topology(beam_a, beam_b)
            if candidate is not None:
                self.add_joint_candidate(candidate)
