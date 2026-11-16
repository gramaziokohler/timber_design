"""Tests for Beam2D and ConnectionSolver2D.

Uses real Beam2D objects (no mocks) and is designed to run inside Rhino's
Python environment as well as a standard pytest runner.

Coordinate convention
---------------------
All beams lie flat in the XY plane with ``z_vector=(0,0,1)`` so that:
  * ``frame.yaxis`` points in  **-X** for a beam along Y, and in **-Y** for a
    beam along X.
  * ``edge_a`` is the blank edge offset in the **-yaxis** direction (−width/2).
  * ``edge_b`` is the blank edge offset in the **+yaxis** direction (+width/2).

For a horizontal beam from (x0,0) to (x1,0) with width *w*:
  blank spans x=[x0, x1],  y=[−w/2, +w/2]

For a vertical beam from (0,y0) to (0,y1) with width *w*:
  blank spans x=[−w/2, +w/2],  y=[y0, y1]
"""

import pytest
from compas.geometry import Line
from compas.geometry import Point
from compas.geometry import Polyline
from compas.geometry import Translation
from compas.geometry import Vector
from compas_timber.connections.solver import JointTopology

from timber_design.connections_2d.beam2d import AABB2D
from timber_design.connections_2d.beam2d import Beam2D
from timber_design.connections_2d.connection_solver_2d import Beam2DSolverResult
from timber_design.connections_2d.connection_solver_2d import Cluster2D
from timber_design.connections_2d.connection_solver_2d import Cluster2DFinder
from timber_design.connections_2d.connection_solver_2d import ConnectionSolver2D
from timber_design.connections_2d.connection_solver_2d import _merge_intervals
from timber_design.connections_2d.connection_solver_2d import aabb_overlap


# =============================================================================
# Helpers
# =============================================================================


def make_beam(x0, y0, x1, y1, width=0.5, height=0.1):
    """Create a Beam2D from flat 2D start/end coordinates."""
    return Beam2D.from_centerline(
        Line(Point(x0, y0, 0.0), Point(x1, y1, 0.0)),
        width=width,
        height=height,
        z_vector=Vector(0.0, 0.0, 1.0),
    )


def make_solver_result(beam_a, beam_b, topology, dot_a=None, dot_b=None):
    """Helper to build a Beam2DSolverResult with a dummy location."""
    loc = Point(0, 0, 0)
    return Beam2DSolverResult(beam_a, beam_b, 0.0, topology, loc, dot_a, dot_b)


class SimpleAgent(object):
    """Minimal stand-in for LayerAgent with an ``elements`` list and ``aabb``."""

    def __init__(self, beams):
        self.elements = list(beams)

    @property
    def aabb(self):
        pts = []
        for e in self.elements:
            if hasattr(e, "aabb") and e.aabb:
                pts.extend(e.aabb.points)
        if not pts:
            return None
        return AABB2D.from_points(pts)


# =============================================================================
# AABB2D
# =============================================================================


class TestAABB2D:
    def test_construction(self):
        aabb = AABB2D(1.0, 3.0, 2.0, 4.0)
        assert aabb.xmin == 1.0
        assert aabb.xmax == 3.0
        assert aabb.ymin == 2.0
        assert aabb.ymax == 4.0

    def test_bool_always_true(self):
        assert bool(AABB2D(0, 1, 0, 1))

    def test_from_points(self):
        pts = [Point(1, 3, 0), Point(4, 1, 0), Point(2, 5, 0)]
        aabb = AABB2D.from_points(pts)
        assert aabb.xmin == 1.0
        assert aabb.xmax == 4.0
        assert aabb.ymin == 1.0
        assert aabb.ymax == 5.0

    def test_points_four_corners(self):
        aabb = AABB2D(0, 2, 1, 3)
        pts = aabb.points
        assert len(pts) == 4
        xs = {p.x for p in pts}
        ys = {p.y for p in pts}
        assert xs == {0.0, 2.0}
        assert ys == {1.0, 3.0}


# =============================================================================
# Beam2D geometry
# =============================================================================


class TestBeam2DGeometry:
    """Tests for Beam2D blank geometry properties."""

    def test_blank_outline_vertices(self):
        """blank_outline must be [bl, br, tr, tl, bl] (CCW)."""
        beam = make_beam(0, 0, 4, 0, width=1.0)
        outline = beam.blank_outline
        pts = list(outline.points)
        assert len(pts) == 5
        assert pts[0].x == pytest.approx(0.0) and pts[0].y == pytest.approx(-0.5)  # bl
        assert pts[1].x == pytest.approx(4.0) and pts[1].y == pytest.approx(-0.5)  # br
        assert pts[2].x == pytest.approx(4.0) and pts[2].y == pytest.approx(0.5)  # tr
        assert pts[3].x == pytest.approx(0.0) and pts[3].y == pytest.approx(0.5)  # tl
        assert pts[4].x == pytest.approx(pts[0].x) and pts[4].y == pytest.approx(pts[0].y)  # closed

    def test_blank_outline_cached(self):
        """The same object is returned on repeated access (lazy cache)."""
        beam = make_beam(0, 0, 2, 0)
        assert beam.blank_outline is beam.blank_outline

    def test_edge_a_is_bottom_face(self):
        """edge_a runs along the −yaxis side (y = −width/2 for a horizontal beam)."""
        beam = make_beam(0, 0, 4, 0, width=1.0)
        ea = beam.edge_a
        assert ea.start.y == pytest.approx(-0.5)
        assert ea.end.y == pytest.approx(-0.5)
        assert ea.start.x == pytest.approx(0.0)
        assert ea.end.x == pytest.approx(4.0)

    def test_edge_b_is_top_face(self):
        """edge_b runs along the +yaxis side (y = +width/2 for a horizontal beam)."""
        beam = make_beam(0, 0, 4, 0, width=1.0)
        eb = beam.edge_b
        assert eb.start.y == pytest.approx(0.5)
        assert eb.end.y == pytest.approx(0.5)
        assert eb.start.x == pytest.approx(0.0)
        assert eb.end.x == pytest.approx(4.0)

    def test_edge_b_same_direction_as_edge_a(self):
        """edge_b must be oriented start→end (same direction as edge_a / beam axis)."""
        beam = make_beam(0, 0, 5, 0)
        ea, eb = beam.edge_a, beam.edge_b
        # Both should progress in the +x direction for a horizontal beam
        assert ea.end.x > ea.start.x
        assert eb.end.x > eb.start.x

    def test_start_segment_at_beam_start(self):
        """start_segment is the cap at the beam origin end."""
        beam = make_beam(0, 0, 4, 0, width=1.0)
        seg = beam.start_segment
        assert seg.start.x == pytest.approx(0.0)
        assert seg.end.x == pytest.approx(0.0)

    def test_end_segment_at_beam_end(self):
        """end_segment is the cap at the beam terminal end."""
        beam = make_beam(0, 0, 4, 0, width=1.0)
        seg = beam.end_segment
        assert seg.start.x == pytest.approx(4.0)
        assert seg.end.x == pytest.approx(4.0)

    def test_aabb_horizontal_beam(self):
        """AABB of a horizontal beam spans [x0, x1] × [−w/2, +w/2]."""
        beam = make_beam(1, 2, 5, 2, width=1.0)
        aabb = beam.aabb
        assert aabb.xmin == pytest.approx(1.0)
        assert aabb.xmax == pytest.approx(5.0)
        assert aabb.ymin == pytest.approx(1.5)
        assert aabb.ymax == pytest.approx(2.5)

    def test_aabb_vertical_beam(self):
        """AABB of a vertical beam spans [−w/2, +w/2] × [y0, y1]."""
        beam = make_beam(3, 0, 3, 4, width=1.0)
        aabb = beam.aabb
        assert aabb.xmin == pytest.approx(2.5)
        assert aabb.xmax == pytest.approx(3.5)
        assert aabb.ymin == pytest.approx(0.0)
        assert aabb.ymax == pytest.approx(4.0)


# =============================================================================
# Beam2D.contains_point
# =============================================================================


class TestBeam2DContainsPoint:
    """Tests for Beam2D.contains_point."""

    def test_centre_is_inside(self):
        beam = make_beam(0, 0, 4, 0, width=1.0)
        assert beam.contains_point(Point(2, 0, 0))

    def test_corner_is_inside(self):
        beam = make_beam(0, 0, 4, 0, width=1.0)
        assert beam.contains_point(Point(0, -0.5, 0))  # bl corner
        assert beam.contains_point(Point(4, 0.5, 0))  # tr corner

    def test_outside_returns_false(self):
        beam = make_beam(0, 0, 4, 0, width=1.0)
        assert not beam.contains_point(Point(5, 0, 0))  # beyond x end
        assert not beam.contains_point(Point(2, 1.0, 0))  # beyond y top

    def test_exactly_on_edge_included(self):
        """A point sitting exactly on the blank boundary (zero tolerance) is inside."""
        beam = make_beam(0, 0, 4, 0, width=1.0)
        assert beam.contains_point(Point(2, 0.5, 0))  # on top face
        assert beam.contains_point(Point(2, -0.5, 0))  # on bottom face
        assert beam.contains_point(Point(0, 0, 0))  # on start cap
        assert beam.contains_point(Point(4, 0, 0))  # on end cap

    def test_tolerance_expands_boundary(self):
        """A point just outside the blank is inside with a matching tolerance."""
        beam = make_beam(0, 0, 4, 0, width=1.0)
        eps = 0.05
        # Just past the top face: y = 0.5 + eps
        assert not beam.contains_point(Point(2, 0.5 + eps, 0), tolerance=0.0)
        assert beam.contains_point(Point(2, 0.5 + eps, 0), tolerance=eps + 1e-9)

    def test_vertical_beam_contains_its_centre(self):
        beam = make_beam(3, 0, 3, 4, width=1.0)
        assert beam.contains_point(Point(3, 2, 0))
        assert not beam.contains_point(Point(3, 5, 0))  # past the end


# =============================================================================
# Beam2D.transform and cache invalidation
# =============================================================================


class TestBeam2DTransform:
    def test_transform_invalidates_blank_outline_cache(self):
        """After a translation the cached blank_outline must be recomputed."""
        beam = make_beam(0, 0, 4, 0, width=1.0)
        outline_before = beam.blank_outline
        beam.transform(Translation.from_vector(Vector(2, 0, 0)))
        outline_after = beam.blank_outline
        # Object identity must differ (cache was cleared)
        assert outline_before is not outline_after
        # Start point should have moved by +2 in x
        assert outline_after.points[0].x == pytest.approx(2.0)

    def test_transform_updates_aabb(self):
        beam = make_beam(0, 0, 4, 0, width=1.0)
        beam.transform(Translation.from_vector(Vector(10, 0, 0)))
        aabb = beam.aabb
        assert aabb.xmin == pytest.approx(10.0)
        assert aabb.xmax == pytest.approx(14.0)


# =============================================================================
# Beam2D.get_beam_segment
# =============================================================================


class TestGetBeamSegment:
    def test_segment_has_correct_length(self):
        beam = make_beam(0, 0, 10, 0)
        seg = beam.get_beam_segment(2.0, 7.0)
        assert seg.length == pytest.approx(5.0)

    def test_segment_start_is_translated(self):
        """The segment origin must be at the correct position along the beam."""
        beam = make_beam(0, 0, 10, 0)
        seg = beam.get_beam_segment(3.0, 8.0)
        assert seg.frame.point.x == pytest.approx(3.0)
        assert seg.frame.point.y == pytest.approx(0.0)

    def test_degenerate_range_raises(self):
        beam = make_beam(0, 0, 4, 0)
        with pytest.raises(ValueError):
            beam.get_beam_segment(2.0, 2.0)

    def test_segment_aabb_is_correct(self):
        beam = make_beam(0, 0, 10, 0, width=1.0)
        seg = beam.get_beam_segment(2.0, 6.0)
        aabb = seg.aabb
        assert aabb.xmin == pytest.approx(2.0)
        assert aabb.xmax == pytest.approx(6.0)


# =============================================================================
# _merge_intervals
# =============================================================================


class TestMergeIntervals:
    def test_empty(self):
        assert _merge_intervals([]) == []

    def test_single(self):
        assert _merge_intervals([(1.0, 3.0)]) == [(1.0, 3.0)]

    def test_non_overlapping_stays_separate(self):
        result = _merge_intervals([(0, 1), (2, 3)])
        assert result == [(0, 1), (2, 3)]

    def test_overlapping_merged(self):
        result = _merge_intervals([(0, 2), (1, 3)])
        assert result == [(0, 3)]

    def test_touching_merged(self):
        result = _merge_intervals([(0, 2), (2, 4)])
        assert result == [(0, 4)]

    def test_contained_interval_merged(self):
        result = _merge_intervals([(0, 10), (3, 7)])
        assert result == [(0, 10)]

    def test_unsorted_input_handled(self):
        result = _merge_intervals([(5, 8), (1, 3), (2, 6)])
        assert result == [(1, 8)]


# =============================================================================
# aabb_overlap
# =============================================================================


class TestAabbOverlap:
    def test_clearly_overlapping(self):
        a = make_beam(0, 0, 4, 0)  # x=0..4, y=±0.25
        b = make_beam(2, 0, 2, 4)  # x=±0.25+2, y=0..4
        assert aabb_overlap(a, b)

    def test_clearly_separated(self):
        a = make_beam(0, 0, 2, 0)
        b = make_beam(5, 0, 7, 0)
        assert not aabb_overlap(a, b)

    def test_touching_edge_default_tolerance(self):
        """AABBs that exactly share an edge are counted as overlapping (tolerance=0)."""
        a = make_beam(0, 0, 2, 0, width=1.0)  # x=0..2, y=−0.5..+0.5
        b = make_beam(2, 0, 4, 0, width=1.0)  # x=2..4, y=−0.5..+0.5 — share x=2
        assert aabb_overlap(a, b, tolerance=0.0)

    def test_gap_smaller_than_tolerance_overlaps(self):
        """A gap of 0.1 is considered overlapping with tolerance=0.2."""
        a = make_beam(0, 0, 2, 0, width=1.0)  # xmax=2.0
        b = make_beam(2.1, 0, 4, 0, width=1.0)  # xmin=2.1 — gap=0.1
        assert not aabb_overlap(a, b, tolerance=0.0)
        assert aabb_overlap(a, b, tolerance=0.1)

    def test_none_aabb_returns_false(self):
        """Objects with None aabb are never matched."""
        a = SimpleAgent([])  # aabb returns None
        b = make_beam(0, 0, 4, 0)
        assert not aabb_overlap(a, b)


# =============================================================================
# intersection_beam2d_polyline
# =============================================================================


class TestIntersectionBeam2dPolyline:
    """Tests for ConnectionSolver2D.intersection_beam2d_polyline."""

    def test_polyline_crosses_beam_twice(self):
        """A straight polyline entering and exiting the beam blank → one crossing."""
        beam = make_beam(0, 0, 4, 0, width=1.0)  # blank x=0..4, y=±0.5
        # Vertical line at x=2 from y=−2 to y=+2 crosses the beam twice
        outline = Polyline([Point(2, -2, 0), Point(2, 2, 0)])
        results = ConnectionSolver2D.intersection_beam2d_polyline(beam, outline)
        assert len(results) == 1
        r = results[0]
        assert r.start_dot is not None
        assert r.end_dot is not None

    def test_polyline_does_not_intersect(self):
        """A polyline far from the beam → empty result."""
        beam = make_beam(0, 0, 4, 0, width=1.0)
        outline = Polyline([Point(10, -2, 0), Point(10, 2, 0)])
        results = ConnectionSolver2D.intersection_beam2d_polyline(beam, outline)
        assert results == []

    def test_polyline_parallel_to_beam_outside(self):
        """A polyline running parallel to but outside the beam → no intersection."""
        beam = make_beam(0, 0, 4, 0, width=1.0)  # y=±0.5
        outline = Polyline([Point(0, 2, 0), Point(4, 2, 0)])  # y=2, outside
        results = ConnectionSolver2D.intersection_beam2d_polyline(beam, outline)
        assert results == []

    def test_dots_ordered_start_before_end(self):
        """start_dot ≤ end_dot for a forward-crossing polyline segment."""
        beam = make_beam(0, 0, 4, 0, width=1.0)
        # Diagonal crossing from bottom-left to top-right through the beam
        outline = Polyline([Point(1, -2, 0), Point(3, 2, 0)])
        results = ConnectionSolver2D.intersection_beam2d_polyline(beam, outline)
        assert len(results) >= 1
        r = results[0]
        if r.start_dot is not None and r.end_dot is not None:
            assert r.start_dot <= r.end_dot

    def test_multiple_crossings(self):
        """A zigzag polyline that enters and exits the beam twice → two crossings."""
        beam = make_beam(0, 0, 4, 0, width=1.0)  # blank y=±0.5
        # Goes: outside → inside → outside → inside → outside
        outline = Polyline(
            [
                Point(1, -2, 0),
                Point(1, 0, 0),  # enters at x=1
                Point(1, 2, 0),  # exits
                Point(3, 2, 0),
                Point(3, 0, 0),  # enters at x=3
                Point(3, -2, 0),  # exits
            ]
        )
        results = ConnectionSolver2D.intersection_beam2d_polyline(beam, outline)
        assert len(results) == 2

    def test_limit_to_segments_false_extends_long_edges(self):
        """With limit_to_segments=False, long edges extend beyond the blank ends."""
        # Short beam, but polyline hits the extended long-edge line
        beam = make_beam(1, 0, 3, 0, width=1.0)  # blank x=1..3
        # This outline hits where x=0 would be if the long edge were infinite
        outline = Polyline([Point(0, -2, 0), Point(0, 2, 0)])
        no_extend = ConnectionSolver2D.intersection_beam2d_polyline(beam, outline, limit_to_segments=True)
        with_extend = ConnectionSolver2D.intersection_beam2d_polyline(beam, outline, limit_to_segments=False)
        assert no_extend == []
        assert len(with_extend) == 1


# =============================================================================
# extend_beam_to_polylines
# =============================================================================


class TestExtendBeamToPolylines:
    """Tests for ConnectionSolver2D.extend_beam_to_polylines."""

    def _rect_outline(self, xmin, xmax, ymin, ymax):
        return Polyline(
            [
                Point(xmin, ymin, 0),
                Point(xmax, ymin, 0),
                Point(xmax, ymax, 0),
                Point(xmin, ymax, 0),
                Point(xmin, ymin, 0),
            ]
        )

    def test_extend_start_to_outline(self):
        """Beam start is pushed to reach the boundary outline."""
        beam = make_beam(1, 0, 4, 0, width=0.5)  # starts at x=1
        boundary = self._rect_outline(-1, 5, -2, 2)  # left edge at x=−1
        orig_length = beam.length
        ConnectionSolver2D.extend_beam_to_polylines(beam, [boundary])
        assert beam.frame.point.x == pytest.approx(-1.0)
        assert beam.length > orig_length

    def test_extend_end_to_outline(self):
        """Beam end is pushed to reach the boundary outline."""
        beam = make_beam(0, 0, 3, 0, width=0.5)  # ends at x=3
        boundary = self._rect_outline(-1, 5, -2, 2)  # right edge at x=5
        ConnectionSolver2D.extend_beam_to_polylines(beam, [boundary])
        assert beam.length == pytest.approx(6.0)  # 0→(-1) start + up to x=5 end

    def test_only_end_flag(self):
        """only_end=True: only the end side is extended, start is unchanged."""
        beam = make_beam(1, 0, 4, 0, width=0.5)
        boundary = self._rect_outline(-1, 6, -2, 2)
        ConnectionSolver2D.extend_beam_to_polylines(beam, [boundary], only_end=True)
        # Start must stay at x=1
        assert beam.frame.point.x == pytest.approx(1.0)

    def test_only_start_flag(self):
        """only_start=True: only the start side is extended, end is unchanged."""
        beam = make_beam(1, 0, 4, 0, width=0.5)
        boundary = self._rect_outline(-1, 6, -2, 2)
        ConnectionSolver2D.extend_beam_to_polylines(beam, [boundary], only_start=True)
        # After extending the start to x=−1, the length = 4 − (−1) = 5
        assert beam.frame.point.x == pytest.approx(-1.0)
        assert beam.length == pytest.approx(5.0)

    def test_both_flags_raises(self):
        """Passing both only_start and only_end must raise ValueError."""
        beam = make_beam(0, 0, 4, 0)
        with pytest.raises(ValueError):
            ConnectionSolver2D.extend_beam_to_polylines(beam, [], only_start=True, only_end=True)

    def test_no_intersection_beam_unchanged(self):
        """If no outline intersects, the beam geometry stays the same."""
        beam = make_beam(0, 0, 4, 0, width=0.5)
        start_x = beam.frame.point.x
        length = beam.length
        # Outline completely to the right, no intersection
        ConnectionSolver2D.extend_beam_to_polylines(beam, [None])
        assert beam.frame.point.x == pytest.approx(start_x)
        assert beam.length == pytest.approx(length)


# =============================================================================
# find_topology
# =============================================================================


class TestFindTopology:
    """Tests for ConnectionSolver2D.find_topology."""

    def test_no_overlap_returns_none(self):
        """Beams with clearly separated blanks produce no candidate."""
        solver = ConnectionSolver2D()
        beam_a = make_beam(0, 0, 2, 0)  # blank x=0..2,  y=±0.25
        beam_b = make_beam(5, 0, 7, 0)  # blank x=5..7,  y=±0.25  — far apart
        assert solver.find_topology(beam_a, beam_b) is None

    def test_parallel_offset_no_overlap_returns_none(self):
        """Parallel beams whose AABBs are beyond max_distance apart → no candidate.

        With solver max_distance=0.0, the AABB gap must be >0 to avoid overlap.
        beam_b at y=3 gives a blank-edge gap of 2.5.
        """
        solver = ConnectionSolver2D()
        beam_a = make_beam(0, 0, 4, 0)  # blank y=±0.25
        beam_b = make_beam(0, 3, 4, 3)  # blank y=2.75..3.25 — AABB gap=2.5
        assert solver.find_topology(beam_a, beam_b) is None

    def test_topo_l_corner_joint(self):
        """Two beams meeting end-to-end at a right-angle corner → TOPO_L."""
        solver = ConnectionSolver2D()
        beam_a = make_beam(0, 0, 2, 0)
        beam_b = make_beam(2, 0, 2, 2)
        candidate = solver.find_topology(beam_a, beam_b)
        assert candidate is not None
        assert candidate.topology == JointTopology.TOPO_L

    def test_topo_t_end_beam_is_beam_a(self):
        """End beam (the one that butts in) must be ``beam_a`` in the result."""
        solver = ConnectionSolver2D()
        beam_face = make_beam(0, 0, 4, 0)  # long face beam — blank y=±0.25
        beam_end = make_beam(2, -2, 2, 0)  # short end beam terminating at y=0
        candidate = solver.find_topology(beam_face, beam_end)
        assert candidate is not None
        assert candidate.topology == JointTopology.TOPO_T
        assert candidate.beam_a is beam_end
        assert candidate.beam_b is beam_face

    def test_topo_t_argument_order_normalised(self):
        """Swapping argument order must not change which beam is ``beam_a``."""
        solver = ConnectionSolver2D()
        beam_face = make_beam(0, 0, 4, 0)
        beam_end = make_beam(2, -2, 2, 0)
        c1 = solver.find_topology(beam_end, beam_face)
        c2 = solver.find_topology(beam_face, beam_end)
        assert c1 is not None and c2 is not None
        assert c1.beam_a is beam_end
        assert c2.beam_a is beam_end

    def test_topo_x_crossing_beams(self):
        """Two beams whose centrelines cross in the middle, with no endpoint
        inside the other beam's blank → TOPO_X."""
        solver = ConnectionSolver2D()
        beam_a = make_beam(-1, 0, 3, 0)  # horizontal — blank y=±0.25
        beam_b = make_beam(1, -2, 1, 2)  # vertical   — blank x=±0.25
        candidate = solver.find_topology(beam_a, beam_b)
        assert candidate is not None
        assert candidate.topology == JointTopology.TOPO_X

    def test_candidate_carries_location(self):
        """Every returned candidate has a non-None ``location`` point."""
        solver = ConnectionSolver2D()
        cases = [
            (make_beam(0, 0, 2, 0), make_beam(2, 0, 2, 2)),  # L
            (make_beam(0, 0, 4, 0), make_beam(2, -2, 2, 0)),  # T
            (make_beam(-1, 0, 3, 0), make_beam(1, -2, 1, 2)),  # X
        ]
        for beam_a, beam_b in cases:
            candidate = solver.find_topology(beam_a, beam_b)
            assert candidate is not None, "Expected a candidate for overlapping beams"
            assert candidate.location is not None

    def test_candidate_elements_are_the_input_beams(self):
        """``element_a`` and ``element_b`` together must be the two input beams."""
        solver = ConnectionSolver2D()
        beam_a = make_beam(0, 0, 4, 0)
        beam_b = make_beam(2, -2, 2, 0)
        candidate = solver.find_topology(beam_a, beam_b)
        assert candidate is not None
        assert {id(candidate.beam_a), id(candidate.beam_b)} == {id(beam_a), id(beam_b)}

    def test_topo_t_end_trimmed_flush(self):
        """End beam trimmed so its start sits exactly at the face beam's outer edge
        — no blank overlap, but extended edge lines detect the T-joint."""
        solver = ConnectionSolver2D()
        beam_face = make_beam(0, 0, 4, 0, width=0.5)
        beam_end = make_beam(2, 0.25, 2, 2, width=0.5)
        candidate = solver.find_topology(beam_face, beam_end)
        assert candidate is not None
        assert candidate.topology == JointTopology.TOPO_T
        assert candidate.beam_a is beam_end

    def test_topo_l_both_trimmed_flush(self):
        """Both beams trimmed to each other's outer face — extended edge lines
        detect the L-joint even though the blanks are adjacent, not overlapping."""
        solver = ConnectionSolver2D()
        beam_a = make_beam(0, 0, 1.75, 0, width=0.5)
        beam_b = make_beam(2, 0.25, 2, 3, width=0.5)
        candidate = solver.find_topology(beam_a, beam_b)
        assert candidate is not None
        assert candidate.topology == JointTopology.TOPO_L

    def test_symmetric_pair_returns_same_topology(self):
        """Calling find_topology(a, b) and find_topology(b, a) must return the
        same topology value (element roles may differ for T, but topology is equal)."""
        solver = ConnectionSolver2D()
        pairs = [
            (make_beam(0, 0, 2, 0), make_beam(2, 0, 2, 2)),  # L
            (make_beam(0, 0, 4, 0), make_beam(2, -2, 2, 0)),  # T
            (make_beam(-1, 0, 3, 0), make_beam(1, -2, 1, 2)),  # X
        ]
        for beam_a, beam_b in pairs:
            c1 = solver.find_topology(beam_a, beam_b)
            c2 = solver.find_topology(beam_b, beam_a)
            assert c1 is not None and c2 is not None
            assert c1.topology == c2.topology

    def test_dot_ranges_on_result(self):
        """Topology result must carry non-None dot_range_on_a and dot_range_on_b."""
        solver = ConnectionSolver2D()
        beam_a = make_beam(0, 0, 4, 0)
        beam_b = make_beam(2, -2, 2, 0)
        result = solver.find_topology(beam_a, beam_b)
        assert result is not None
        assert result.dot_range_on_a is not None
        assert result.dot_range_on_b is not None
        ra_min, ra_max = result.dot_range_on_a
        assert ra_min <= ra_max
        rb_min, rb_max = result.dot_range_on_b
        assert rb_min <= rb_max


# =============================================================================
# find_intersecting_pairs
# =============================================================================


class TestFindIntersectingPairs:
    """Tests for ConnectionSolver2D.find_intersecting_pairs."""

    def test_single_overlapping_pair(self):
        """Three beams where only one pair's AABBs overlap → one result."""
        solver = ConnectionSolver2D()
        beam_a = make_beam(0, 0, 2, 0)
        beam_b = make_beam(2, 0, 2, 2)  # meets beam_a at the corner
        beam_c = make_beam(10, 0, 12, 0)  # completely separate
        pairs = list(solver.find_intersecting_pairs([beam_a, beam_b, beam_c]))
        assert len(pairs) == 1
        pair_ids = {id(pairs[0][0]), id(pairs[0][1])}
        assert pair_ids == {id(beam_a), id(beam_b)}

    def test_multiple_overlapping_pairs(self):
        """One long horizontal + two short verticals → two overlapping pairs."""
        solver = ConnectionSolver2D()
        beam_h = make_beam(0, 0, 6, 0)
        beam_v1 = make_beam(2, -2, 2, 0)
        beam_v2 = make_beam(5, -2, 5, 0)
        pairs = list(solver.find_intersecting_pairs([beam_h, beam_v1, beam_v2]))
        assert len(pairs) == 2

    def test_no_overlapping_beams(self):
        """Beams all separated → empty result."""
        solver = ConnectionSolver2D()
        pairs = list(solver.find_intersecting_pairs([make_beam(0, 0, 1, 0), make_beam(5, 0, 6, 0), make_beam(10, 0, 11, 0)]))
        assert pairs == []

    def test_each_pair_yielded_once(self):
        """No (a,b) / (b,a) duplicates — each unordered pair appears once."""
        solver = ConnectionSolver2D()
        beam_a = make_beam(0, 0, 4, 0)
        beam_b = make_beam(2, -2, 2, 2)
        pairs = list(solver.find_intersecting_pairs([beam_a, beam_b]))
        assert len(pairs) == 1

    def test_single_beam_returns_empty(self):
        solver = ConnectionSolver2D()
        assert list(solver.find_intersecting_pairs([make_beam(0, 0, 2, 0)])) == []

    def test_empty_list_returns_empty(self):
        solver = ConnectionSolver2D()
        assert list(solver.find_intersecting_pairs([])) == []

    def test_yielded_pairs_are_tuples_of_two_beams(self):
        """Each yielded item must be a 2-tuple of Beam2D instances."""
        solver = ConnectionSolver2D()
        beam_a = make_beam(0, 0, 4, 0)
        beam_b = make_beam(2, -2, 2, 0)
        pairs = list(solver.find_intersecting_pairs([beam_a, beam_b]))
        assert len(pairs) == 1
        pair = pairs[0]
        assert len(pair) == 2
        assert isinstance(pair[0], Beam2D)
        assert isinstance(pair[1], Beam2D)

    def test_agents_accepted_alongside_beams(self):
        """find_intersecting_pairs accepts SimpleAgent objects (anything with aabb)."""
        solver = ConnectionSolver2D()
        agent_a = SimpleAgent([make_beam(0, 0, 4, 0)])
        agent_b = SimpleAgent([make_beam(2, -2, 2, 0)])
        agent_c = SimpleAgent([make_beam(20, 0, 24, 0)])
        pairs = list(solver.find_intersecting_pairs([agent_a, agent_b, agent_c]))
        assert len(pairs) == 1
        pair_ids = {id(pairs[0][0]), id(pairs[0][1])}
        assert pair_ids == {id(agent_a), id(agent_b)}

    def test_empty_agent_not_matched(self):
        """An agent with no elements (None aabb) is skipped."""
        solver = ConnectionSolver2D()
        agent_a = SimpleAgent([make_beam(0, 0, 4, 0)])
        agent_empty = SimpleAgent([])
        pairs = list(solver.find_intersecting_pairs([agent_a, agent_empty]))
        assert pairs == []


# =============================================================================
# Cluster2D topology and properties
# =============================================================================


class TestCluster2DTopology:
    """Tests for Cluster2D using the dot-range topology algorithm."""

    def test_single_result_inherits_topology(self):
        """A cluster with one result reports that result's topology directly."""
        beam_a = make_beam(0, 0, 4, 0)
        beam_b = make_beam(2, -2, 2, 0)
        result = make_solver_result(beam_b, beam_a, JointTopology.TOPO_T, dot_a=(0.0, 2.0), dot_b=(1.5, 2.5))
        cluster = Cluster2D([result])
        assert cluster.topology == JointTopology.TOPO_T

    def test_three_beams_all_ending_at_junction_gives_topo_y(self):
        """Three beams whose ends all meet at the same point → TOPO_Y.

        v1 ends at origin, v2 and v3 start at origin — all three have an
        endpoint in the overlap zone, so the cluster is TOPO_Y.
        """
        v1 = make_beam(-4, 0, 0, 0)  # length=4
        v2 = make_beam(0, 0, 2, 2)  # length≈2.83
        v3 = make_beam(0, 0, 2, -2)  # length≈2.83
        r1 = make_solver_result(v1, v2, JointTopology.TOPO_L, dot_a=(3.75, 4.0), dot_b=(0.0, 0.25))
        r2 = make_solver_result(v1, v3, JointTopology.TOPO_L, dot_a=(3.75, 4.0), dot_b=(0.0, 0.25))
        cluster = Cluster2D([r1, r2], endpoint_tolerance=0.5)
        assert cluster.topology == JointTopology.TOPO_Y

    def test_mid_body_junction_gives_topo_k(self):
        """A result whose dot range does not touch either beam endpoint → TOPO_K."""
        h1 = make_beam(0, 0, 10, 0)  # length=10
        h2 = make_beam(0, 2, 10, 2)  # length=10
        v = make_beam(5, 0, 5, 2, width=0.5)
        r1 = make_solver_result(v, h1, JointTopology.TOPO_T, dot_a=(0.0, 0.25), dot_b=(4.75, 5.25))
        r2 = make_solver_result(v, h2, JointTopology.TOPO_T, dot_a=(1.75, 2.0), dot_b=(4.75, 5.25))
        cluster = Cluster2D([r1, r2], endpoint_tolerance=0.5)
        assert cluster.topology == JointTopology.TOPO_K

    def test_location_is_average_of_results(self):
        """Cluster location is the centroid of all constituent result locations."""
        beam_a = make_beam(0, 0, 4, 0)
        beam_b = make_beam(2, -2, 2, 0)
        r1 = Beam2DSolverResult(beam_b, beam_a, 0.0, JointTopology.TOPO_T, Point(1, 0, 0), (0, 1), (1, 2))
        r2 = Beam2DSolverResult(beam_b, beam_a, 0.0, JointTopology.TOPO_T, Point(3, 0, 0), (0, 1), (3, 4))
        cluster = Cluster2D([r1, r2])
        assert cluster.location.x == pytest.approx(2.0)

    def test_elements_deduplicated(self):
        """cluster.elements contains each beam once, even when shared across results."""
        h = make_beam(0, 0, 4, 0)
        v1 = make_beam(1, -2, 1, 0)
        v2 = make_beam(3, -2, 3, 0)
        r1 = make_solver_result(v1, h, JointTopology.TOPO_T, (0, 1), (0.75, 1.25))
        r2 = make_solver_result(v2, h, JointTopology.TOPO_T, (0, 1), (2.75, 3.25))
        cluster = Cluster2D([r1, r2])
        assert len(cluster.elements) == 3  # h, v1, v2 — h appears in both but counted once


class TestCluster2DFinder:
    """Tests for Cluster2DFinder.find_clusters."""

    def test_empty_results(self):
        finder = Cluster2DFinder()
        assert finder.find_clusters([]) == []

    def test_single_result_becomes_single_cluster(self):
        beam_a = make_beam(0, 0, 4, 0)
        beam_b = make_beam(2, -2, 2, 0)
        result = make_solver_result(beam_b, beam_a, JointTopology.TOPO_T, dot_a=(0.0, 2.0), dot_b=(1.75, 2.25))
        clusters = Cluster2DFinder().find_clusters([result])
        assert len(clusters) == 1
        assert clusters[0].joints[0] is result

    def test_two_overlapping_results_merged_into_one_cluster(self):
        """Two results sharing a beam with overlapping dot ranges → one cluster."""
        h = make_beam(0, 0, 4, 0)
        v1 = make_beam(1, -2, 1, 0)
        v2 = make_beam(1.2, -2, 1.2, 0)  # very close to v1, shares region on h
        r1 = make_solver_result(v1, h, JointTopology.TOPO_T, dot_a=(0.0, 1.0), dot_b=(0.75, 1.45))
        r2 = make_solver_result(v2, h, JointTopology.TOPO_T, dot_a=(0.0, 1.0), dot_b=(0.95, 1.45))
        clusters = Cluster2DFinder().find_clusters([r1, r2])
        assert len(clusters) == 1
        assert len(clusters[0].joints) == 2

    def test_find_clusters_returns_cluster2d(self):
        """find_clusters() returns Cluster2D instances (subclass of Cluster)."""
        from compas_timber.connections import Cluster

        beam_a = make_beam(0, 0, 4, 0)
        beam_b = make_beam(2, -2, 2, 0)
        result = make_solver_result(beam_b, beam_a, JointTopology.TOPO_T, dot_a=(0.0, 2.0), dot_b=(1.75, 2.25))
        clusters = Cluster2DFinder().find_clusters([result])
        assert isinstance(clusters[0], Cluster2D)
        assert isinstance(clusters[0], Cluster)

    def test_two_non_overlapping_results_stay_separate(self):
        """Two T-results on the same face beam but far apart → two clusters."""
        h = make_beam(0, 0, 10, 0)
        v1 = make_beam(1, -2, 1, 0)
        v2 = make_beam(8, -2, 8, 0)
        r1 = make_solver_result(v1, h, JointTopology.TOPO_T, dot_a=(0.0, 1.0), dot_b=(0.75, 1.25))
        r2 = make_solver_result(v2, h, JointTopology.TOPO_T, dot_a=(0.0, 1.0), dot_b=(7.75, 8.25))
        clusters = Cluster2DFinder().find_clusters([r1, r2])
        assert len(clusters) == 2
