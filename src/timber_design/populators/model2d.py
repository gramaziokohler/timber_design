from __future__ import annotations

from itertools import combinations

from compas.geometry import Point
from compas_timber.analyzers import Cluster
from compas_timber.connections import JointCandidate
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


def _detect_beam_pair(beam_a, beam_b):
    # type: (Beam2D, Beam2D) -> JointCandidate | None
    """Return a :class:`~compas_timber.connections.JointCandidate` for the 2D
    blank-space intersection between *beam_a* and *beam_b*, or ``None`` when
    the blanks do not overlap.

    Topology is determined by endpoint-containment tests on the four blank
    corners of each beam (``blank_a.start/end`` and ``blank_b.start/end``):

    - **TOPO_L**: corners of *both* beams lie inside the other beam's blank.
    - **TOPO_T**: corners of only *one* beam lie inside the other.
      ``element_a`` of the returned candidate is always the *end* beam.
    - **TOPO_X**: no corners inside either beam; overlap detected via
      edge–edge crossings of the blank outlines.
    """
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

    Builds :class:`~compas_timber.analyzers.Cluster` objects directly from the
    blank-edge intersection tests, without requiring a
    :class:`~compas_timber.model.TimberModel` or a ``max_distance`` threshold.

    **Two-beam clusters** (one :class:`~compas_timber.connections.JointCandidate`
    each) are created for all intersecting pairs:

    - *TOPO_L* — corners of both beams inside each other (L-corner joint).
    - *TOPO_T* — corners of one beam inside the other (T-joint;
      ``element_a`` is always the end beam).
    - *TOPO_X* — no corners inside either; long-edge crossings detected
      (lap / X-joint).

    **Three-beam clusters** (two candidates, one per pair) are created when
    three mutually intersecting beams share a common junction.  The criterion
    is purely geometric — no distance threshold is needed:

    - *CORNER* (TOPO_Y or TOPO_K): the primary beam is the *end* beam in ≥2
      pairwise candidates, **and** those two other beams are themselves
      directly connected.  The primary beam butts into the corner where the
      other two meet.
    - *NOTCH* (TOPO_K): ≥2 beams end inside the primary beam (primary is
      *face* beam in ≥2 T-joint candidates), **and** those end-beams are
      themselves directly connected.  The primary beam spans over the
      junction where the other two meet.

    Pairwise candidates that are already covered by a three-beam cluster are
    **not** returned as additional two-beam clusters.

    Parameters
    ----------
    beams : list[:class:`~timber_design.populators.Beam2D`]

    Returns
    -------
    list[:class:`~compas_timber.analyzers.Cluster`]
    """
    # ------------------------------------------------------------------
    # Step 1 — pre-compute all pairwise candidates
    # ------------------------------------------------------------------
    pair_candidates = {}  # frozenset({id_a, id_b}) -> JointCandidate
    for beam_a, beam_b in combinations(beams, 2):
        cand = _detect_beam_pair(beam_a, beam_b)
        if cand is not None:
            pair_candidates[frozenset([id(beam_a), id(beam_b)])] = cand

    # ------------------------------------------------------------------
    # Step 2 — find three-beam clusters (CORNER and NOTCH)
    # ------------------------------------------------------------------
    seen_multi = set()  # frozenset of three element ids, one per 3-beam cluster
    clusters = []

    for primary in beams:
        # Candidates where primary is the *end* beam:
        #   T-joint with primary as element_a, or L-joint involving primary
        end_cands = [
            c for key, c in pair_candidates.items()
            if id(primary) in key
            and c.topology in (JointTopology.TOPO_T, JointTopology.TOPO_L)
            and (c.topology == JointTopology.TOPO_L or c.element_a is primary)
        ]

        # Candidates where primary is the *face* beam:
        #   T-joint with primary as element_b only (L handled in end_cands)
        face_cands = [
            c for key, c in pair_candidates.items()
            if id(primary) in key
            and c.topology == JointTopology.TOPO_T
            and c.element_b is primary
        ]

        # CORNER: primary (end) butts into the junction of two connected beams
        for c1, c2 in combinations(end_cands, 2):
            b1 = _other_beam(c1, primary)
            b2 = _other_beam(c2, primary)
            if frozenset([id(b1), id(b2)]) not in pair_candidates:
                continue  # b1 and b2 are not connected — not the same junction
            cluster_key = frozenset([id(primary), id(b1), id(b2)])
            if cluster_key not in seen_multi:
                seen_multi.add(cluster_key)
                clusters.append(Cluster([c1, c2]))

        # NOTCH: two connected beams both end inside primary (primary is face)
        for c1, c2 in combinations(face_cands, 2):
            b1 = c1.element_a  # always element_a for T-joints
            b2 = c2.element_a
            if frozenset([id(b1), id(b2)]) not in pair_candidates:
                continue  # b1 and b2 are not connected — separate T-joints
            cluster_key = frozenset([id(primary), id(b1), id(b2)])
            if cluster_key not in seen_multi:
                seen_multi.add(cluster_key)
                clusters.append(Cluster([c1, c2]))

    # ------------------------------------------------------------------
    # Step 3 — wrap remaining pairwise candidates as two-beam clusters
    # ------------------------------------------------------------------
    for pair_key, cand in pair_candidates.items():
        if any(pair_key.issubset(multi_key) for multi_key in seen_multi):
            continue  # already covered by a three-beam cluster
        clusters.append(Cluster([cand]))

    return clusters


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
