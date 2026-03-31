import pytest
from itertools import pairwise

from compas.geometry import Line, Point, Polyline, Vector
from compas.tolerance import TOL

from timber_design.populators.beam2d import Beam2D
from timber_design.populators.generator_intersection import BeamGeneratorIntersection
from timber_design.populators.generator_intersection import IntersectionType
from timber_design.populators.generator_intersection import split_beam_with_element_generators
from timber_design.populators.generator_intersection import extend_beam_to_closest_element_generators
from timber_design.populators.generator_intersection import _get_beam_edge_outline_intersections
from timber_design.populators.generator_intersection import _find_crossings


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


def rectangle_outline(xmin, ymin, xmax, ymax):
    """Closed rectangular polyline."""
    pts = [
        Point(xmin, ymin, 0),
        Point(xmax, ymin, 0),
        Point(xmax, ymax, 0),
        Point(xmin, ymax, 0),
    ]
    return Polyline(pts + [pts[0]])


class MockGenerator:
    """Minimal ElementGenerator stand-in."""

    def __init__(self, outline):
        self.outline = outline

    def cull_element_at_point(self, point):
        return False

    def trim_beam(self, beam):
        bgi_list = BeamGeneratorIntersection.from_beam_and_generator(beam, self)
        if not bgi_list:
            return [beam], []
        sentinels = [
            BeamGeneratorIntersection(None, 0.0, None),
            BeamGeneratorIntersection(None, beam.length, None),
        ]
        intersections = sentinels[:1] + bgi_list + sentinels[1:]
        intersections.sort(key=lambda x: x.dot)
        segs = []
        for pair in pairwise(intersections):
            # Use dot_end for segment start, dot_start for segment end
            # → maximum beam length (cut as far from centre as possible)
            start_pos = pair[0].dot_end
            end_pos = pair[1].dot_start
            if end_pos <= start_pos:
                continue
            start_pt = beam.frame.point + beam.frame.xaxis * start_pos
            end_pt = beam.frame.point + beam.frame.xaxis * end_pos
            seg = Beam2D.from_centerline(Line(start_pt, end_pt), width=beam.width, height=beam.height)
            if not self.cull_element_at_point(seg.centerline.midpoint):
                segs.append(seg)
        return segs, []


# =============================================================================
# _find_crossings — SINGLE
# =============================================================================


class TestFindCrossings:
    def test_single_transverse_cut(self):
        """Generator boundary crosses both long beam edges in one outline segment."""
        beam = make_beam(0, 0, 4, 0, width=0.5)
        # Outline: rectangle to the right of x=2, spanning y=-1..1
        outline = rectangle_outline(2, -1, 6, 1)
        parsed = _find_crossings(beam, outline)
        assert len(parsed) == 1
        assert parsed[0].type == IntersectionType.SINGLE

    def test_single_dot_values_span_beam_width(self):
        """SINGLE dots should be on the two different long faces (close but not equal)."""
        beam = make_beam(0, 0, 4, 0, width=0.5)
        outline = rectangle_outline(2, -1, 6, 1)
        parsed = _find_crossings(beam, outline)
        d0, d1 = parsed[0].dots
        # One dot on edge_a (y=-0.25) and one on edge_b (y=+0.25) — both near x=2
        assert abs(d0 - 2.0) < 0.01
        assert abs(d1 - 2.0) < 0.01

    def test_no_intersection_when_separate(self):
        """Outline that does not touch the beam returns no crossings."""
        beam = make_beam(0, 0, 4, 0, width=0.5)
        outline = rectangle_outline(10, -1, 14, 1)
        assert _find_crossings(beam, outline) == []

    def test_two_single_intersections(self):
        """Outline straddles the beam on both sides → two SINGLE crossings."""
        beam = make_beam(0, 0, 4, 0, width=0.5)
        # Outline rectangle that the beam passes fully through
        outline = rectangle_outline(1, -1, 3, 1)
        parsed = _find_crossings(beam, outline)
        types = [p.type for p in parsed]
        assert types.count(IntersectionType.SINGLE) == 2

    def test_corner_intersection(self):
        """One outline corner dips across both long faces → CORNER."""
        beam = make_beam(0, 0, 4, 0, width=0.5)
        # Outline corner at (2, 0): diagonal entry through edge_b then exit through edge_a
        outline = Polyline([
            Point(2, 2, 0),
            Point(2, 0, 0),     # corner enters beam blank (y = 0, inside ±0.25)
            Point(6, 0, 0),
            Point(6, 2, 0),
            Point(2, 2, 0),
        ])
        parsed = _find_crossings(beam, outline)
        assert len(parsed) >= 1
        assert any(p.type == IntersectionType.CORNER for p in parsed)

    def test_notch_intersection(self):
        """Outline corner clips only one long face → NOTCH."""
        beam = make_beam(0, 0, 4, 0, width=0.5)
        # Outline dips 0.1 below y=0.25 (edge_b), then comes back — clips top face only
        outline = Polyline([
            Point(-1, 0.4, 0),
            Point(2, 0.4, 0),
            Point(2, 0.2, 0),   # 0.2 < 0.25, so inside beam's +y face
            Point(3, 0.2, 0),
            Point(3, 0.4, 0),
            Point(5, 0.4, 0),
            Point(5, -1, 0),
            Point(-1, -1, 0),
            Point(-1, 0.4, 0),
        ])
        parsed = _find_crossings(beam, outline)
        assert any(p.type == IntersectionType.NOTCH for p in parsed)

    def test_lap_intersection(self):
        """Outline encloses a region through which the beam passes → LAP."""
        beam = make_beam(0, 0, 4, 0, width=0.5)
        # Outline: a small rectangle that overlaps the beam middle, with 2+ corners inside
        outline = rectangle_outline(1.5, -0.2, 2.5, 0.2)
        parsed = _find_crossings(beam, outline)
        assert any(p.type == IntersectionType.LAP for p in parsed)

    def test_skip_notches(self):
        beam = make_beam(0, 0, 4, 0, width=0.5)
        outline = Polyline([
            Point(-1, 0.4, 0), Point(2, 0.4, 0), Point(2, 0.2, 0),
            Point(3, 0.2, 0), Point(3, 0.4, 0), Point(5, 0.4, 0),
            Point(5, -1, 0), Point(-1, -1, 0), Point(-1, 0.4, 0),
        ])
        parsed_with = _find_crossings(beam, outline, skip_notches=False)
        parsed_without = _find_crossings(beam, outline, skip_notches=True)
        notches_with = sum(1 for p in parsed_with if p.type == IntersectionType.NOTCH)
        notches_without = sum(1 for p in parsed_without if p.type == IntersectionType.NOTCH)
        assert notches_with > 0
        assert notches_without == 0

    def test_skip_laps(self):
        beam = make_beam(0, 0, 4, 0, width=0.5)
        outline = rectangle_outline(1.5, -0.2, 2.5, 0.2)
        parsed_with = _find_crossings(beam, outline, skip_laps=False)
        parsed_without = _find_crossings(beam, outline, skip_laps=True)
        assert any(p.type == IntersectionType.LAP for p in parsed_with)
        assert not any(p.type == IntersectionType.LAP for p in parsed_without)


# =============================================================================
# BeamGeneratorIntersection properties
# =============================================================================


class TestBGIProperties:
    def test_dot_is_midpoint(self):
        bgi = BeamGeneratorIntersection("single", [1.0, 1.2], None)
        assert TOL.is_close(bgi.dot, 1.1)

    def test_dot_start_is_min_of_all_dots(self):
        """dot_start uses min across ALL dots, including the corner dot."""
        bgi = BeamGeneratorIntersection("corner", [1.2, 0.9, 1.0], None)
        assert TOL.is_close(bgi.dot_start, 0.9)

    def test_dot_end_is_max_of_all_dots(self):
        """dot_end uses max across ALL dots, including the corner dot."""
        bgi = BeamGeneratorIntersection("corner", [1.2, 0.9, 1.5], None)
        assert TOL.is_close(bgi.dot_end, 1.5)

    def test_dot_start_corner_dot_is_extremum(self):
        """When the corner dot is the outermost value, it controls dot_start."""
        bgi = BeamGeneratorIntersection("notch", [1.0, 1.2, 0.7], None)
        assert TOL.is_close(bgi.dot_start, 0.7)

    def test_dot_end_corner_dot_is_extremum(self):
        """When the corner dot is the outermost value, it controls dot_end."""
        bgi = BeamGeneratorIntersection("notch", [1.0, 1.2, 1.8], None)
        assert TOL.is_close(bgi.dot_end, 1.8)

    def test_dot_start_single_is_min(self):
        """For SINGLE (no corner dot), dot_start is min of two edge crossings."""
        bgi = BeamGeneratorIntersection("single", [1.2, 0.9], None)
        assert TOL.is_close(bgi.dot_start, 0.9)

    def test_dot_end_single_is_max(self):
        """For SINGLE (no corner dot), dot_end is max of two edge crossings."""
        bgi = BeamGeneratorIntersection("single", [1.2, 0.9], None)
        assert TOL.is_close(bgi.dot_end, 1.2)

    def test_sentinel_dot_scalar(self):
        """Scalar dots (sentinels) round-trip through the properties."""
        bgi = BeamGeneratorIntersection(None, 0.0, None)
        assert TOL.is_close(bgi.dot, 0.0)
        assert TOL.is_close(bgi.dot_start, 0.0)
        assert TOL.is_close(bgi.dot_end, 0.0)


# =============================================================================
# from_beam_and_generator
# =============================================================================


class TestFromBeamAndGenerator:
    def test_produces_bgi_list(self):
        beam = make_beam(0, 0, 4, 0, width=0.5)
        gen = MockGenerator(rectangle_outline(2, -1, 6, 1))
        result = BeamGeneratorIntersection.from_beam_and_generator(beam, gen)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].type == IntersectionType.SINGLE

    def test_no_outline_returns_empty(self):
        beam = make_beam(0, 0, 4, 0)
        gen = MockGenerator(None)
        assert BeamGeneratorIntersection.from_beam_and_generator(beam, gen) == []

    def test_no_intersection_returns_empty(self):
        beam = make_beam(0, 0, 1, 0)
        gen = MockGenerator(rectangle_outline(10, -1, 14, 1))
        assert BeamGeneratorIntersection.from_beam_and_generator(beam, gen) == []

    def test_type_and_dots_present(self):
        beam = make_beam(0, 0, 4, 0, width=0.5)
        gen = MockGenerator(rectangle_outline(2, -1, 6, 1))
        bgi = BeamGeneratorIntersection.from_beam_and_generator(beam, gen)[0]
        assert hasattr(bgi, "type")
        assert hasattr(bgi, "dots")
        assert len(bgi.dots) >= 2


# =============================================================================
# split_beam_with_element_generators
# =============================================================================


def test_split_no_intersection_returns_beam():
    beam = make_beam(0, 0, 1, 0, width=0.1)
    gen = MockGenerator(rectangle_outline(10, -1, 14, 1))
    segs, rules = split_beam_with_element_generators(beam, [gen])
    assert len(segs) == 1
    assert segs[0] is beam
    assert rules == []


def test_split_single_crossing_produces_two_segments():
    beam = make_beam(0, 0, 4, 0, width=0.5)
    gen = MockGenerator(rectangle_outline(1, -1, 3, 1))
    segs, _ = split_beam_with_element_generators(beam, [gen])
    assert len(segs) >= 2


def test_split_segments_have_centerlines():
    beam = make_beam(0, 0, 4, 0, width=0.5)
    gen = MockGenerator(rectangle_outline(1, -1, 3, 1))
    segs, _ = split_beam_with_element_generators(beam, [gen])
    for seg in segs:
        assert hasattr(seg, "centerline")


# =============================================================================
# extend_beam_to_closest_element_generators
# =============================================================================


def test_extend_beam_reaches_end_generator():
    beam = make_beam(0, 0, 1, 0, width=0.5)
    gen = MockGenerator(rectangle_outline(2, -1, 6, 1))
    extend_beam_to_closest_element_generators(beam, [gen], only_end=True)
    assert beam.length > 1.0


def test_extend_beam_reaches_start_generator():
    beam = make_beam(3, 0, 5, 0, width=0.5)
    gen = MockGenerator(rectangle_outline(-2, -1, 2, 1))
    extend_beam_to_closest_element_generators(beam, [gen], only_start=True)
    # beam should now start closer to x=2
    assert beam.length > 2.0


def test_extend_no_generator_no_change():
    beam = make_beam(0, 0, 2, 0, width=0.5)
    original_length = beam.length
    extend_beam_to_closest_element_generators(beam, [])
    assert TOL.is_close(beam.length, original_length)


# =============================================================================
# _get_beam_edge_outline_intersections (used by model2d TOPO_X detection)
# =============================================================================


def test_beam_edge_outline_intersections_returns_pair():
    beam = make_beam(0, 0, 4, 0, width=0.5)
    outline = rectangle_outline(2, -1, 6, 1)
    ints_a, ints_b = _get_beam_edge_outline_intersections(beam, outline)
    assert isinstance(ints_a, list)
    assert isinstance(ints_b, list)
    # Each crossing should have a .point attribute
    for item in ints_a + ints_b:
        assert hasattr(item, "point")


def test_beam_edge_outline_no_intersection():
    beam = make_beam(0, 0, 1, 0, width=0.1)
    outline = rectangle_outline(10, -1, 14, 1)
    ints_a, ints_b = _get_beam_edge_outline_intersections(beam, outline)
    assert ints_a == []
    assert ints_b == []


# =============================================================================
# beam.contains_point (regression)
# =============================================================================


def test_beam_contains_point_inside():
    beam = make_beam(0, 0, 4, 0, width=1.0)
    assert beam.contains_point(Point(2, 0.1, 0)) is True


def test_beam_contains_point_outside():
    beam = make_beam(0, 0, 4, 0, width=1.0)
    assert beam.contains_point(Point(2, 2.0, 0)) is False
