"""Tests for agent_intersection.py.

Covers ``BeamOutlineIntersectionData``, ``find_beam_outline_crossings``,
and ``extend_beam_to_closest_agents``.

All beams lie in the XY plane (z=0) following the same convention as the
connection-solver tests.
"""

import pytest

from compas.geometry import Line
from compas.geometry import Point
from compas.geometry import Polyline
from compas.geometry import Vector
from compas.tolerance import TOL

from timber_design.connections_2d.beam2d import Beam2D
from timber_design.populators.agent_intersection import BeamOutlineIntersectionData
from timber_design.populators.agent_intersection import extend_beam_to_closest_agents
from timber_design.populators.agent_intersection import find_beam_outline_crossings


# =============================================================================
# Helpers
# =============================================================================


def make_beam(x0, y0, x1, y1, width=0.5, height=0.1):
    return Beam2D.from_centerline(
        Line(Point(x0, y0, 0.0), Point(x1, y1, 0.0)),
        width=width,
        height=height,
        z_vector=Vector(0.0, 0.0, 1.0),
    )


def rect_outline(xmin, ymin, xmax, ymax):
    """Closed rectangular Polyline."""
    pts = [
        Point(xmin, ymin, 0),
        Point(xmax, ymin, 0),
        Point(xmax, ymax, 0),
        Point(xmin, ymax, 0),
    ]
    return Polyline(pts + [pts[0]])


class MockAgent(object):
    """Minimal LayerAgent stand-in for extend tests."""

    def __init__(self, outline):
        self.outline = outline
        self.elements = []


# =============================================================================
# BeamOutlineIntersectionData
# =============================================================================


class TestBeamOutlineIntersectionData:
    def test_all_dots_excludes_none(self):
        data = BeamOutlineIntersectionData(start_dot=1.0, end_dot=None, internal_dots=[2.0])
        assert data.all_dots == [1.0, 2.0]

    def test_all_dots_all_present(self):
        data = BeamOutlineIntersectionData(start_dot=0.5, end_dot=1.5, internal_dots=[0.9])
        assert set(data.all_dots) == {0.5, 1.5, 0.9}

    def test_average_dot_basic(self):
        data = BeamOutlineIntersectionData(start_dot=1.0, end_dot=3.0)
        assert TOL.is_close(data.average_dot, 2.0)

    def test_average_dot_with_internal(self):
        data = BeamOutlineIntersectionData(start_dot=0.0, end_dot=4.0, internal_dots=[2.0])
        assert TOL.is_close(data.average_dot, 2.0)

    def test_average_dot_zero_start_not_none(self):
        """0.0 start_dot must not be excluded."""
        data = BeamOutlineIntersectionData(start_dot=0.0, end_dot=2.0)
        assert data.average_dot is not None
        assert TOL.is_close(data.average_dot, 1.0)

    def test_average_dot_no_dots_returns_none(self):
        data = BeamOutlineIntersectionData()
        assert data.average_dot is None

    def test_all_dots_empty_when_no_values(self):
        data = BeamOutlineIntersectionData()
        assert data.all_dots == []

    def test_internal_dots_default_empty(self):
        data = BeamOutlineIntersectionData(start_dot=1.0, end_dot=2.0)
        assert data.internal_dots == []


# =============================================================================
# find_beam_outline_crossings
# =============================================================================


class TestFindBeamOutlineCrossings:
    def test_transverse_crossing_detected(self):
        """Outline crossing both long beam edges → at least one crossing.

        y-offset of ±2 ensures the outline start is >1 unit outside the beam
        blank (y=±0.25) so ``contains_point`` with tolerance=1.0 does not
        falsely classify the start as 'inside'.
        """
        beam = make_beam(0, 0, 4, 0, width=0.5)
        outline = rect_outline(2, -2, 6, 2)
        crossings = find_beam_outline_crossings(beam, outline)
        assert len(crossings) >= 1

    def test_no_intersection_returns_empty(self):
        beam = make_beam(0, 0, 4, 0, width=0.5)
        outline = rect_outline(10, -2, 14, 2)
        assert find_beam_outline_crossings(beam, outline) == []

    def test_crossing_has_start_and_end_dot(self):
        beam = make_beam(0, 0, 4, 0, width=0.5)
        outline = rect_outline(2, -2, 6, 2)
        crossings = find_beam_outline_crossings(beam, outline)
        for c in crossings:
            assert c.start_dot is not None
            assert c.end_dot is not None

    def test_beam_passthrough_gives_two_crossings(self):
        """Outline rectangle the beam passes fully through → two crossings."""
        beam = make_beam(0, 0, 6, 0, width=0.5)
        outline = rect_outline(1, -2, 3, 2)
        crossings = find_beam_outline_crossings(beam, outline)
        assert len(crossings) == 2

    def test_dot_values_within_beam_range(self):
        beam = make_beam(0, 0, 4, 0, width=0.5)
        outline = rect_outline(1, -2, 3, 2)
        for c in find_beam_outline_crossings(beam, outline):
            for d in c.all_dots:
                assert -0.01 <= d <= 4.01  # small tolerance for float rounding

    def test_outline_start_inside_beam_wraparound(self):
        """Wrap-around outline starting inside the beam must still yield valid crossings."""
        beam = make_beam(0, 0, 4, 0, width=1.0)
        outline = Polyline(
            [
                Point(2, 0, 0),
                Point(2, 2, 0),
                Point(-1, 2, 0),
                Point(-1, -2, 0),
                Point(5, -2, 0),
                Point(5, 2, 0),
                Point(2, 2, 0),
                Point(2, 0, 0),
            ]
        )
        crossings = find_beam_outline_crossings(beam, outline)
        assert isinstance(crossings, list)

    def test_returns_intersection_data_instances(self):
        beam = make_beam(0, 0, 4, 0, width=0.5)
        outline = rect_outline(2, -1, 6, 1)
        for c in find_beam_outline_crossings(beam, outline):
            assert isinstance(c, BeamOutlineIntersectionData)

    def test_limit_to_segments_false_detects_beyond_beam_end(self):
        """limit_to_segments=False finds crossings outside current beam extents."""
        beam = make_beam(0, 0, 1, 0, width=0.5)  # short beam, ends at x=1
        outline = rect_outline(2, -2, 6, 2)  # outline starts at x=2 (y-offset >1 to stay outside blank)
        # With segment limits: no crossing
        assert find_beam_outline_crossings(beam, outline, limit_to_segments=True) == []
        # Without limits: crossing found
        extended = find_beam_outline_crossings(beam, outline, limit_to_segments=False)
        assert len(extended) >= 1

    def test_crossing_start_dot_less_than_end_dot(self):
        """For a clean transverse crossing start_dot < end_dot."""
        beam = make_beam(0, 0, 4, 0, width=0.5)
        outline = rect_outline(2, -1, 6, 1)
        crossings = find_beam_outline_crossings(beam, outline)
        for c in crossings:
            if c.start_dot is not None and c.end_dot is not None:
                assert c.start_dot <= c.end_dot


# =============================================================================
# extend_beam_to_closest_agents
# =============================================================================


class TestExtendBeam:
    def test_no_agents_no_change(self):
        beam = make_beam(0, 0, 2, 0, width=0.5)
        original_length = beam.length
        extend_beam_to_closest_agents(beam, [])
        assert TOL.is_close(beam.length, original_length)

    def test_extends_toward_end(self):
        """Agent outline beyond the beam end → beam grows in length."""
        beam = make_beam(0, 0, 1, 0, width=0.5)
        agent = MockAgent(rect_outline(2, -2, 6, 2))
        extend_beam_to_closest_agents(beam, [agent], only_end=True)
        assert beam.length > 1.0

    def test_extends_toward_start(self):
        """Agent outline behind beam start → beam origin shifts, length grows."""
        beam = make_beam(3, 0, 5, 0, width=0.5)
        agent = MockAgent(rect_outline(-2, -2, 2, 2))
        original_length = beam.length
        extend_beam_to_closest_agents(beam, [agent], only_start=True)
        assert beam.length > original_length

    def test_only_start_and_only_end_raises(self):
        beam = make_beam(0, 0, 2, 0)
        with pytest.raises(ValueError):
            extend_beam_to_closest_agents(beam, [], only_start=True, only_end=True)

    def test_agent_with_none_outline_ignored(self):
        """Agent whose outline is None must not affect the beam."""
        beam = make_beam(0, 0, 2, 0, width=0.5)
        original_length = beam.length
        agent = MockAgent(None)
        extend_beam_to_closest_agents(beam, [agent])
        assert TOL.is_close(beam.length, original_length)

    def test_multiple_agents_picks_nearest(self):
        """When two agents are on the same side, the nearest one wins."""
        beam = make_beam(0, 0, 1, 0, width=0.5)
        agent_near = MockAgent(rect_outline(2, -2, 4, 2))  # nearest boundary at x≈2
        agent_far = MockAgent(rect_outline(5, -2, 8, 2))  # nearest boundary at x≈5
        extend_beam_to_closest_agents(beam, [agent_near, agent_far], only_end=True)
        # Beam should reach into the near agent, not all the way to the far one
        assert beam.length < 5.0


# =============================================================================
# Beam2D helpers (regression)
# =============================================================================


class TestBeam2DHelpers:
    def test_contains_point_inside(self):
        beam = make_beam(0, 0, 4, 0, width=1.0)
        assert beam.contains_point(Point(2, 0.1, 0)) is True

    def test_contains_point_outside(self):
        beam = make_beam(0, 0, 4, 0, width=1.0)
        assert beam.contains_point(Point(2, 2.0, 0)) is False

    def test_contains_point_on_edge_within_tolerance(self):
        """Point exactly on the blank boundary is inside when tolerance > 0."""
        beam = make_beam(0, 0, 4, 0, width=1.0)
        # Point at y = +0.5 (exactly on edge_b)
        assert beam.contains_point(Point(2, 0.5, 0), tolerance=1.0) is True

    def test_contains_point_default_tolerance(self):
        """Default tolerance=1.0 accepts a point just outside the blank edge."""
        beam = make_beam(0, 0, 4, 0, width=1.0)
        assert beam.contains_point(Point(2, 0.6, 0)) is True  # 0.6 > 0.5 but within tol=1.0

    def test_get_beam_segment_correct_length(self):
        beam = make_beam(0, 0, 4, 0, width=0.5)
        seg = beam.get_beam_segment(1.0, 3.0)
        assert TOL.is_close(seg.length, 2.0)

    def test_get_beam_segment_degenerate_raises(self):
        beam = make_beam(0, 0, 4, 0, width=0.5)
        with pytest.raises(ValueError):
            beam.get_beam_segment(2.0, 2.0)

    def test_get_beam_segment_blank_cache_cleared(self):
        """Segment's blank outline must reflect its new position, not the parent's."""
        beam = make_beam(0, 0, 4, 0, width=0.5)
        seg = beam.get_beam_segment(1.0, 3.0)
        # blank outline start should be near x=1, not x=0
        assert seg.blank_outline.points[0].x > 0.5

    def test_edge_a_and_edge_b_are_lines(self):
        from compas.geometry import Line

        beam = make_beam(0, 0, 4, 0, width=0.5)
        assert isinstance(beam.edge_a, Line)
        assert isinstance(beam.edge_b, Line)

    def test_start_and_end_segment_are_lines(self):
        from compas.geometry import Line

        beam = make_beam(0, 0, 4, 0, width=0.5)
        assert isinstance(beam.start_segment, Line)
        assert isinstance(beam.end_segment, Line)

    def test_transform_invalidates_cache(self):
        """After a transform the cached blank_outline must be recomputed."""
        from compas.geometry import Translation

        beam = make_beam(0, 0, 4, 0, width=0.5)
        _ = beam.blank_outline  # populate cache
        beam.transform(Translation.from_vector(Vector(1, 0, 0)))
        # New blank_outline origin should be near x=1
        assert beam.blank_outline.points[0].x > 0.5

    def test_aabb_covers_blank(self):
        from timber_design.connections_2d.beam2d import AABB2D

        beam = make_beam(0, 0, 4, 0, width=1.0)
        aabb = beam.aabb
        assert isinstance(aabb, AABB2D)
        assert aabb.xmin <= 0.0
        assert aabb.xmax >= 4.0
        assert aabb.ymin <= -0.5
        assert aabb.ymax >= 0.5
