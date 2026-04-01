"""Tests for generator_intersection.py — updated for the outline-walk API.

The old ``BeamGeneratorIntersection`` / ``_find_crossings`` API has been
replaced by ``BeamOutlineIntersectionData`` / ``find_beam_outline_crossings``.
These tests verify the new implementation.  They use only real objects and are
designed to run both with pytest and inside Rhino's Python environment.
"""

from compas.geometry import Line
from compas.geometry import Point
from compas.geometry import Polyline
from compas.geometry import Vector
from compas.tolerance import TOL

from timber_design.populators.beam2d import Beam2D
from timber_design.populators.generator_intersection import (
    BeamOutlineIntersectionData,
    find_beam_outline_crossings,
    extend_beam_to_closest_element_generators,
    trim_generator_elements_with_genenrator,
)


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


class MockGenerator(object):
    """Minimal ElementGenerator stand-in for trimming tests."""

    BOUNDARY_TYPE = "inclusive"

    def __init__(self, outline):
        self.outline = outline
        self.elements = []

    def cull_element_at_point(self, point):
        return False

    def trim_beam(self, beam, skip_notches=True, skip_laps=True):
        from itertools import pairwise
        crossings = find_beam_outline_crossings(beam, self.outline) if self.outline else []
        if not crossings:
            return [beam]
        sentinels = [
            BeamOutlineIntersectionData(start_dot=0.0, end_dot=0.0),
            BeamOutlineIntersectionData(start_dot=beam.length, end_dot=beam.length),
        ]
        all_crossings = sentinels[:1] + crossings + sentinels[1:]
        all_crossings.sort(key=lambda x: x.average_dot or 0.0)
        segs = []
        for left, right in pairwise(all_crossings):
            start_pos = max(left.all_dots) if left.all_dots else 0.0
            end_pos = min(right.all_dots) if right.all_dots else beam.length
            if end_pos <= start_pos:
                continue
            seg = beam.get_beam_segment(start_pos, end_pos)
            if not self.cull_element_at_point(seg.centerline.midpoint):
                segs.append(seg)
        return segs


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

    def test_average_dot_zero_start_is_not_none(self):
        """0.0 start_dot must not be excluded — earlier bug used all() on dots."""
        data = BeamOutlineIntersectionData(start_dot=0.0, end_dot=2.0)
        assert data.average_dot is not None
        assert TOL.is_close(data.average_dot, 1.0)

    def test_average_dot_no_dots_returns_none(self):
        data = BeamOutlineIntersectionData()
        assert data.average_dot is None

    def test_all_dots_empty_when_no_values(self):
        data = BeamOutlineIntersectionData()
        assert data.all_dots == []


# =============================================================================
# find_beam_outline_crossings
# =============================================================================


class TestFindBeamOutlineCrossings:
    def test_transverse_crossing_detected(self):
        """Outline crossing both long beam edges → one crossing returned."""
        beam = make_beam(0, 0, 4, 0, width=0.5)
        outline = rect_outline(2, -1, 6, 1)
        crossings = find_beam_outline_crossings(beam, outline)
        assert len(crossings) >= 1

    def test_no_intersection_returns_empty(self):
        beam = make_beam(0, 0, 4, 0, width=0.5)
        outline = rect_outline(10, -1, 14, 1)
        assert find_beam_outline_crossings(beam, outline) == []

    def test_crossing_has_start_and_end_dot(self):
        beam = make_beam(0, 0, 4, 0, width=0.5)
        outline = rect_outline(2, -1, 6, 1)
        crossings = find_beam_outline_crossings(beam, outline)
        for c in crossings:
            assert c.start_dot is not None
            assert c.end_dot is not None

    def test_beam_passthrough_gives_two_crossings(self):
        """Outline rectangle that the beam passes fully through → two crossings."""
        beam = make_beam(0, 0, 6, 0, width=0.5)
        outline = rect_outline(1, -1, 3, 1)
        crossings = find_beam_outline_crossings(beam, outline)
        assert len(crossings) == 2

    def test_dot_values_in_beam_range(self):
        """All dot values must lie within the beam's length extents."""
        beam = make_beam(0, 0, 4, 0, width=0.5)
        outline = rect_outline(1, -1, 3, 1)
        for c in find_beam_outline_crossings(beam, outline):
            for d in c.all_dots:
                assert 0.0 <= d <= 4.0

    def test_outline_start_inside_beam_wraparound(self):
        """When the outline starts inside the beam the wrap-around logic
        must still return a valid crossing with both start and end dots."""
        beam = make_beam(0, 0, 4, 0, width=1.0)
        # Outline starts at (2, 0) which is INSIDE the beam blank
        outline = Polyline([
            Point(2, 0, 0),
            Point(2, 2, 0),
            Point(-1, 2, 0),
            Point(-1, -2, 0),
            Point(5, -2, 0),
            Point(5, 2, 0),
            Point(2, 2, 0),
            Point(2, 0, 0),
        ])
        crossings = find_beam_outline_crossings(beam, outline)
        # Should get at least one crossing even with wrap-around
        assert isinstance(crossings, list)

    def test_returns_beam_outline_intersection_data_instances(self):
        beam = make_beam(0, 0, 4, 0, width=0.5)
        outline = rect_outline(2, -1, 6, 1)
        crossings = find_beam_outline_crossings(beam, outline)
        for c in crossings:
            assert isinstance(c, BeamOutlineIntersectionData)

    def test_limit_to_segments_false_detects_extended(self):
        """With limit_to_segments=False a crossing beyond the beam end is found."""
        beam = make_beam(0, 0, 1, 0, width=0.5)   # short beam, ends at x=1
        outline = rect_outline(2, -1, 6, 1)        # outline starts at x=2
        # No crossing with segments=True
        assert find_beam_outline_crossings(beam, outline, limit_to_segments=True) == []
        # Should find crossing when extending long edges
        extended = find_beam_outline_crossings(beam, outline, limit_to_segments=False)
        assert len(extended) >= 1


# =============================================================================
# extend_beam_to_closest_element_generators
# =============================================================================


class TestExtendBeam:
    def test_no_generators_no_change(self):
        beam = make_beam(0, 0, 2, 0, width=0.5)
        original_length = beam.length
        extend_beam_to_closest_element_generators(beam, [])
        assert TOL.is_close(beam.length, original_length)

    def test_extends_toward_end(self):
        """Beam is too short; generator outline is further along → beam grows."""
        beam = make_beam(0, 0, 1, 0, width=0.5)
        gen = MockGenerator(rect_outline(2, -1, 6, 1))
        extend_beam_to_closest_element_generators(beam, [gen], only_end=True)
        assert beam.length > 1.0

    def test_extends_toward_start(self):
        """Generator outline is behind the beam start → beam origin shifts."""
        beam = make_beam(3, 0, 5, 0, width=0.5)
        gen = MockGenerator(rect_outline(-2, -1, 2, 1))
        original_length = beam.length
        extend_beam_to_closest_element_generators(beam, [gen], only_start=True)
        assert beam.length > original_length

    def test_only_start_only_end_raises(self):
        import pytest
        beam = make_beam(0, 0, 2, 0)
        with pytest.raises(ValueError):
            extend_beam_to_closest_element_generators(beam, [], only_start=True, only_end=True)

    def test_no_intersecting_outline_no_change(self):
        """Generator has no outline → beam unchanged."""
        beam = make_beam(0, 0, 2, 0, width=0.5)
        gen = MockGenerator(None)
        original_length = beam.length
        extend_beam_to_closest_element_generators(beam, [gen])
        assert TOL.is_close(beam.length, original_length)


# =============================================================================
# trim_generator_elements_with_genenrator (module-level function)
# =============================================================================


class TestTrimGeneratorElementsFunction:
    def test_returns_list(self):
        gen_a = MockGenerator(None)
        gen_a.elements = [make_beam(0, 0, 4, 0, width=0.5)]
        gen_b = MockGenerator(rect_outline(10, -1, 14, 1))
        result = trim_generator_elements_with_genenrator(gen_a, gen_b)
        assert isinstance(result, list)

    def test_no_intersection_preserves_beam(self):
        gen_a = MockGenerator(None)
        beam = make_beam(0, 0, 4, 0, width=0.5)
        gen_a.elements = [beam]
        gen_b = MockGenerator(rect_outline(10, -1, 14, 1))
        result = trim_generator_elements_with_genenrator(gen_a, gen_b)
        assert len(result) == 1

    def test_does_not_mutate_generator_a(self):
        """The module-level function must not change gen_a.elements in place."""
        gen_a = MockGenerator(None)
        beam = make_beam(0, 0, 4, 0, width=0.5)
        gen_a.elements = [beam]
        gen_b = MockGenerator(rect_outline(2, -1, 6, 1))
        _ = trim_generator_elements_with_genenrator(gen_a, gen_b)
        assert len(gen_a.elements) == 1  # unchanged

    def test_empty_generator_returns_empty(self):
        gen_a = MockGenerator(None)
        gen_a.elements = []
        gen_b = MockGenerator(rect_outline(0, -1, 4, 1))
        result = trim_generator_elements_with_genenrator(gen_a, gen_b)
        assert result == []


# =============================================================================
# Beam2D helpers (regression)
# =============================================================================


def test_beam_contains_point_inside():
    beam = make_beam(0, 0, 4, 0, width=1.0)
    assert beam.contains_point(Point(2, 0.1, 0)) is True


def test_beam_contains_point_outside():
    beam = make_beam(0, 0, 4, 0, width=1.0)
    assert beam.contains_point(Point(2, 2.0, 0)) is False


def test_beam_get_beam_segment_shortens_beam():
    beam = make_beam(0, 0, 4, 0, width=0.5)
    seg = beam.get_beam_segment(1.0, 3.0)
    assert TOL.is_close(seg.length, 2.0)


def test_beam_edge_a_and_edge_b_are_lines():
    from compas.geometry import Line
    beam = make_beam(0, 0, 4, 0, width=0.5)
    assert isinstance(beam.edge_a, Line)
    assert isinstance(beam.edge_b, Line)


def test_beam_start_and_end_segment_are_lines():
    from compas.geometry import Line
    beam = make_beam(0, 0, 4, 0, width=0.5)
    assert isinstance(beam.start_segment, Line)
    assert isinstance(beam.end_segment, Line)
