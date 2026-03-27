from __future__ import annotations

from itertools import combinations

from compas.geometry import Point
from compas_timber.connections import Cluster
from compas_timber.connections import JointCandidate
from compas_timber.connections import get_clusters_from_joint_candidates
from compas_timber.connections.solver import JointTopology
from compas_timber.model import TimberModel

from timber_design.populators.beam2d import Beam2D
from timber_design.populators.generator_intersection import _get_beam_outline_intersections


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
    pts_a = (beam_a.blank_a.start, beam_a.blank_a.end, beam_a.blank_b.start, beam_a.blank_b.end)
    pts_b = (beam_b.blank_a.start, beam_b.blank_a.end, beam_b.blank_b.start, beam_b.blank_b.end)
    a_xmin = min(p.x for p in pts_a)
    a_xmax = max(p.x for p in pts_a)
    a_ymin = min(p.y for p in pts_a)
    a_ymax = max(p.y for p in pts_a)
    b_xmin = min(p.x for p in pts_b)
    b_xmax = max(p.x for p in pts_b)
    b_ymin = min(p.y for p in pts_b)
    b_ymax = max(p.y for p in pts_b)
    return a_xmax >= b_xmin and b_xmax >= a_xmin and a_ymax >= b_ymin and b_ymax >= a_ymin


def _detect_beam_pair(beam_a, beam_b):
    # type: (Beam2D, Beam2D) -> JointCandidate | None
    """Return a :class:`~compas_timber.connections.JointCandidate` for the 2D
    blank-space intersection between *beam_a* and *beam_b*, or ``None`` when
    the blanks do not overlap.

    A fast axis-aligned bounding-box check is applied first; only pairs whose
    AABBs overlap proceed to the more expensive containment and edge-crossing
    tests.

    Topology is determined by endpoint-containment tests on the four blank
    corners of each beam (``blank_a.start/end`` and ``blank_b.start/end``):

    - **TOPO_L**: corners of *both* beams lie inside the other beam's blank.
    - **TOPO_T**: corners of only *one* beam lie inside the other.
      ``element_a`` of the returned candidate is always the *end* beam.
    - **TOPO_X**: no corners inside either beam; overlap detected via
      edge–edge crossings of the blank outlines.
    """
    if not _aabb_overlap(beam_a, beam_b):
        return None
    a_corners = [beam_a.blank_a.start, beam_a.blank_a.end, beam_a.blank_b.start, beam_a.blank_b.end]
    b_corners = [beam_b.blank_a.start, beam_b.blank_a.end, beam_b.blank_b.start, beam_b.blank_b.end]
    a_in_b = [pt for pt in a_corners if beam_b.contains_point(pt)]
    b_in_a = [pt for pt in b_corners if beam_a.contains_point(pt)]

    if not a_in_b and not b_in_a:
        # No endpoints inside — look for edge-edge crossings (TOPO_X)
        ints_a, ints_b = _get_beam_outline_intersections(beam_a, beam_b.blank_outline)
        if not ints_a and not ints_b:
            return None
        location = _midpoint([i.point for i in ints_a + ints_b])
        return JointCandidate(element_a=beam_a, element_b=beam_b, topology=JointTopology.TOPO_X, location=location)

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


def find_beam_clusters(beams):
    # type: (list[Beam2D]) -> list[Cluster]
    """Find all joint clusters among *beams* using 2D blank-outline geometry.

    **Algorithm overview**

    1. Compute all pairwise :class:`~compas_timber.connections.JointCandidate`
       objects using endpoint-containment and edge-crossing tests on each
       pair's 2D blank outlines (with an AABB pre-filter).
    2. Use :func:`~compas_timber.connections.get_clusters_from_joint_candidates`
       to spatially group the candidates with ``max_distance`` set to twice
       the widest beam.  This efficiently separates spatially isolated pairs
       from groups of candidates that could form a three-beam cluster.
    3. Within each spatial group apply the 2D containment checks:

       - *CORNER* (TOPO_Y / TOPO_K): the *primary* beam is the end beam in
         ≥2 candidates in the group, and the two other beams are themselves
         directly connected (their pair is also in the group).
       - *NOTCH* (TOPO_K): ≥2 beams end inside the *primary* beam (primary
         is the face beam in ≥2 T-joint candidates), and those end beams are
         directly connected.

    Candidates already consumed by a three-beam cluster are not returned as
    separate two-beam clusters.

    Parameters
    ----------
    beams : list[:class:`~timber_design.populators.Beam2D`]

    Returns
    -------
    list[:class:`~compas_timber.connections.Cluster`]
    """
    # ------------------------------------------------------------------
    # Step 1 — pairwise candidates (AABB-filtered)
    # ------------------------------------------------------------------
    pair_candidates = {}  # frozenset({id_a, id_b}) -> JointCandidate
    for beam_a, beam_b in combinations(beams, 2):
        cand = _detect_beam_pair(beam_a, beam_b)
        if cand is not None:
            pair_candidates[frozenset([id(beam_a), id(beam_b)])] = cand

    if not pair_candidates:
        return []

    # ------------------------------------------------------------------
    # Step 2 — spatial pre-clustering
    # ------------------------------------------------------------------
    max_distance = max(b.width for b in beams) * 2.0
    spatial_groups = get_clusters_from_joint_candidates(
        list(pair_candidates.values()), max_distance=max_distance
    )

    # ------------------------------------------------------------------
    # Step 3 — CORNER / NOTCH classification within each spatial group
    # ------------------------------------------------------------------
    seen_multi = set()  # frozenset of 3 beam ids for each confirmed multi-beam cluster
    result_clusters = []

    for group in spatial_groups:
        candidates = group.joints  # list[JointCandidate] within this spatial group

        if len(candidates) == 1:
            result_clusters.append(Cluster(candidates))
            continue

        # Beam-pair keys present in this group — used to confirm b1↔b2 connection
        group_pair_keys = {frozenset([id(c.element_a), id(c.element_b)]) for c in candidates}

        # Unique beams in this group
        group_beams = {c.element_a for c in candidates} | {c.element_b for c in candidates}

        for primary in group_beams:
            # Candidates where primary is the *end* beam
            end_cands = [
                c for c in candidates
                if c.topology in (JointTopology.TOPO_T, JointTopology.TOPO_L)
                and (c.topology == JointTopology.TOPO_L or c.element_a is primary)
            ]
            # Candidates where primary is the *face* beam (T only)
            face_cands = [
                c for c in candidates
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

        # Remaining candidates in this group not consumed by a multi-beam cluster
        for cand in candidates:
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

    For cluster assembly, prefer :func:`find_beam_clusters` over
    :class:`~compas_timber.analyzers.NBeamKDTreeAnalyzer` — it uses the same
    2D blank-outline geometry and requires no ``max_distance`` threshold.
    """

    def connect_adjacent_beams(self, max_distance=None):
        """Populate joint candidates using 2D blank-outline containment.

        Replaces the 3D centerline-distance approach of the base class with
        endpoint-containment tests on every pair of
        :class:`~timber_design.populators.Beam2D` elements in the model.

        Parameters
        ----------
        max_distance : float, optional
            Not used — kept for API compatibility with the base class.
        """
        for candidate in list(self.joint_candidates):
            self.remove_joint_candidate(candidate)

        beams = [e for e in self.elements() if isinstance(e, Beam2D)]
        for beam_a, beam_b in combinations(beams, 2):
            candidate = _detect_beam_pair(beam_a, beam_b)
            if candidate is not None:
                self.add_joint_candidate(candidate)
