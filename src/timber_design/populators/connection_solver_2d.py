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



