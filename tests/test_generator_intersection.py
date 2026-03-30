import math
import pytest
from itertools import pairwise

from compas.geometry import Line, Point, Polyline
from compas.tolerance import TOL

from timber_design.populators.beam2d import Beam2D
from timber_design.populators.generator_intersection import BeamGeneratorIntersection
from timber_design.populators.generator_intersection import split_beam_with_element_generators
from timber_design.populators.generator_intersection import extend_beam_to_closest_element_generators
from timber_design.populators.generator_intersection import _get_beam_outline_intersections
from timber_design.populators.generator_intersection import _parse_corner_intersections
from timber_design.populators.generator_intersection import _parse_notch_intersections
from timber_design.populators.generator_intersection import _parse_simple_intersections


def make_outline(n_edges):
    """Create a closed regular polygon polyline with n_edges edges."""
    pts = [Point(math.cos(2 * math.pi * i / n_edges), math.sin(2 * math.pi * i / n_edges), 0) for i in range(n_edges)]
    return Polyline(pts + [pts[0]])


class MockGenerator:
    def __init__(self, polyline=None):
        polyline = polyline or Polyline([])
        self.edges = {i: e for i, e in enumerate(polyline.lines)}
        self.outline = polyline

    def cull_element_at_point(self, point):
        return False

    def trim_beam(self, beam):
        bgi_list = BeamGeneratorIntersection.from_beam_and_generator(beam, self)
        if not bgi_list:
            return [beam], []
        intersections = [
            BeamGeneratorIntersection(None, 0.0, None),
            BeamGeneratorIntersection(None, beam.length, None),
        ]
        intersections.extend(bgi_list)
        intersections.sort(key=lambda x: x.dot)
        segs = []
        for pair in pairwise(intersections):
            start_pt = beam.frame.point + beam.frame.xaxis * pair[0].dot
            end_pt = beam.frame.point + beam.frame.xaxis * pair[1].dot
            seg = Beam2D.from_centerline(Line(start_pt, end_pt), width=beam.width, height=beam.height)
            if not self.cull_element_at_point(seg.centerline.midpoint):
                segs.append(seg)
        return segs, []


class MockLineGeneratorIntersection:
    def __init__(self, edge_index: int):
        self.edge_index = edge_index
        self.point = Point(0, 0, 0)
        self.dot = 0.0
        self.line = Line([0, 0, 0], [5, 5, 0])


@pytest.fixture
def simple_intersections():
    ints_a = [MockLineGeneratorIntersection(i) for i in [0, 1, 2, 3]]
    ints_b = [MockLineGeneratorIntersection(i) for i in [1, 2, 3, 4]]
    return ints_a, ints_b


def test_parse_simple_intersections(simple_intersections):
    ints_a, ints_b = simple_intersections
    intersections = _parse_simple_intersections(ints_a, ints_b)
    assert len(intersections) == 3
    assert len(ints_a) == 1 and ints_a[0].edge_index == 0
    assert len(ints_b) == 1 and ints_b[0].edge_index == 4


@pytest.fixture
def corner_intersections():
    ints_a = [MockLineGeneratorIntersection(i) for i in [0, 3, 4]]
    ints_b = [MockLineGeneratorIntersection(i) for i in [1, 2, 6]]
    return ints_a, ints_b


def test_parse_corner_intersections(corner_intersections):
    ints_a, ints_b = corner_intersections
    outline = make_outline(8)
    intersections = _parse_corner_intersections(ints_a, ints_b, outline)
    assert len(intersections) == 2
    assert len(ints_a) == 1 and ints_a[0].edge_index == 4
    assert len(ints_b) == 1 and ints_b[0].edge_index == 6


@pytest.fixture
def notch_intersections():
    ints_a = [MockLineGeneratorIntersection(i) for i in [0, 1, 4, 5, 7]]  # no notch at (0,1) b.c. 0.line starts inside beam
    ints_b = [MockLineGeneratorIntersection(i) for i in [2, 4, 6, 8, 9]]
    return ints_a, ints_b


def test_parse_notch_intersections(notch_intersections, beam):
    ints_a, ints_b = notch_intersections
    outline = make_outline(10)
    intersections = _parse_notch_intersections(ints_a, ints_b, beam, outline)
    assert len(intersections) == 2


@pytest.fixture
def beam():
    return Beam2D.from_centerline(Line((-5, -5, 0), (30, 30, 0)), width=1.0, height=1.0)


def rectangle_edges(xmin, ymin, xmax, ymax):
    p0 = Point(xmin, ymin, 0)
    p1 = Point(xmax, ymin, 0)
    p2 = Point(xmax, ymax, 0)
    p3 = Point(xmin, ymax, 0)
    return Polyline([p0, p1, p2, p3, p0])


def test_get_edge_intersections_returns_lists(points, beam):
    gen = MockGenerator(Polyline(points + [points[0]]))

    a, b = _get_beam_outline_intersections(beam, gen.outline, limit_to_segments=True)
    assert isinstance(a, list)
    assert isinstance(b, list)
    # at least one intersection expected on each side (beam edges)
    assert (len(a) == 6 and len(b) == 2) or (len(a) == 2 and len(b) == 6)


def test_from_beam_and_generator_produces_intersections_types():
    beam = Beam2D.from_centerline(Line([0, 0, 0], [3, 0, 0]), width=0.5, height=0.5)
    rect_polyline = rectangle_edges(1.0, -1.0, 2.0, 1.0)
    gen = MockGenerator(rect_polyline)

    intersections = BeamGeneratorIntersection.from_beam_and_generator(beam, gen, limit_to_segments=True)
    assert isinstance(intersections, list)
    assert all(hasattr(i, "type") and hasattr(i, "dot") for i in intersections)


def test_split_beam_with_element_generators_no_intersection_returns_beam():
    beam = Beam2D.from_centerline(Line([0, 0, 0], [1, 0, 0]), width=0.1, height=0.1)
    # generator far away
    rect_polyline = rectangle_edges(10.0, 10.0, 11.0, 11.0)
    gen = MockGenerator(rect_polyline)

    beam_segs, rules = split_beam_with_element_generators(beam, [gen])
    assert len(beam_segs) == 1
    assert beam_segs[0] is beam
    assert rules == []


def test_split_beam_with_element_generators_splits_beam():
    beam = Beam2D.from_centerline(Line([0, 0, 0], [4, 0, 0]), width=0.5, height=0.5)
    rect_polyline = rectangle_edges(1.0, -1.0, 3.0, 1.0)  # beam passes through rectangle from x=1 to x=3
    gen = MockGenerator(rect_polyline)

    beam_segs, rules = split_beam_with_element_generators(beam, [gen])
    assert isinstance(beam_segs, list)
    assert len(beam_segs) >= 2
    for seg in beam_segs:
        assert hasattr(seg, "centerline")


def test_extend_beam_to_closest_element_generators_extends_and_trims_end():
    beam = Beam2D.from_centerline(Line([-5, 0, 0], [0, 0, 0]), width=0.5, height=0.5)
    rect_polyline = rectangle_edges(1.0, -1.0, 4.0, 1.0)
    gen = MockGenerator(rect_polyline)

    extend_beam_to_closest_element_generators(beam, [gen], only_start=False, only_end=False)
    assert TOL.is_close(beam.length, 6.0)


def test_extend_beam_to_closest_element_generators_extends_and_trims_start():
    beam = Beam2D.from_centerline(Line([5, 0, 0], [10, 0, 0]), width=0.5, height=0.5)
    rect_polyline = rectangle_edges(1.0, -1.0, 4.0, 1.0)
    gen = MockGenerator(rect_polyline)

    extend_beam_to_closest_element_generators(beam, [gen], only_start=False, only_end=False)
    assert TOL.is_close(beam.length, 6.0)


def test_extend_beam_to_closest_element_generators_extends_and_trims_start_and_end():
    beam = Beam2D.from_centerline(Line([0, 0, 0], [4, 0, 0]), width=0.5, height=0.5)
    rect_polyline_a = rectangle_edges(-10.0, -1.0, -1.0, 1.0)
    rect_polyline_b = rectangle_edges(5.0, -1.0, 10.0, 1.0)
    gen_a = MockGenerator(rect_polyline_a)
    gen_b = MockGenerator(rect_polyline_b)

    extend_beam_to_closest_element_generators(beam, [gen_a, gen_b], only_start=False, only_end=False)
    assert TOL.is_close(beam.length, 6.0)


def test_extend_beam_to_closest_element_generators_extends_and_trims_only_start():
    beam = Beam2D.from_centerline(Line([0, 0, 0], [4, 0, 0]), width=0.5, height=0.5)
    rect_polyline_a = rectangle_edges(-10.0, -1.0, -1.0, 1.0)
    rect_polyline_b = rectangle_edges(5.0, -1.0, 10.0, 1.0)
    gen_a = MockGenerator(rect_polyline_a)
    gen_b = MockGenerator(rect_polyline_b)

    extend_beam_to_closest_element_generators(beam, [gen_a, gen_b], only_start=True, only_end=False)
    assert TOL.is_close(beam.length, 5.0)


def test_extend_beam_to_closest_element_generators_extends_and_trims_only_end():
    beam = Beam2D.from_centerline(Line([0, 0, 0], [4, 0, 0]), width=0.5, height=0.5)
    rect_polyline_a = rectangle_edges(-10.0, -1.0, -1.0, 1.0)
    rect_polyline_b = rectangle_edges(5.0, -1.0, 10.0, 1.0)
    gen_a = MockGenerator(rect_polyline_a)
    gen_b = MockGenerator(rect_polyline_b)

    extend_beam_to_closest_element_generators(beam, [gen_a, gen_b], only_start=False, only_end=True)
    assert TOL.is_close(beam.length, 5.0)


def test_beam_contains_point():
    beam = Beam2D.from_centerline(Line([0, 0, 0], [4, 0, 0]), width=1.0, height=1.0)
    inside_point = Point(2, 0.1, 0)
    outside_point = Point(2, 2.0, 0)
    assert beam.contains_point(inside_point) is True
    assert beam.contains_point(outside_point) is False


@pytest.fixture
def points() -> list[Point]:
    return [
        Point(x=0.0, y=0.0, z=0.0),
        Point(x=0.0, y=10.0, z=0.0),
        Point(x=10.0, y=10.0, z=0.0),
        Point(x=10.0, y=20.0, z=0.0),
        Point(x=15.0, y=15.0, z=0.0),
        Point(x=20.0, y=20.0, z=0.0),
        Point(x=15.0, y=25.0, z=0.0),
        Point(x=20.0, y=30.0, z=0.0),
        Point(x=30.0, y=20.0, z=0.0),
        Point(x=10.0, y=0.0, z=0.0),
    ]


def test_intersections_from_beam_and_generator(points, beam):
    point_list: list[Point] = [p for p in points]
    for i in range(len(point_list) - 1):
        point_list.append(point_list.pop(0))
        pl = Polyline(point_list + [point_list[0]])
        gen = MockGenerator(pl)
        intersections = BeamGeneratorIntersection.from_beam_and_generator(beam, gen, limit_to_segments=True)
        assert len(intersections) == 4, f"expected 4 intersections, got {len(intersections)}"
        assert len(list(filter(lambda inter: inter.type == "single", intersections))) == 1, (
            f"expected 1 single intersection, got {len(list(filter(lambda inter: inter.type == 'single', intersections)))}"
        )
        assert len(list(filter(lambda inter: inter.type == "corner", intersections))) == 1, (
            f"expected 1 corner intersection, got {len(list(filter(lambda inter: inter.type == 'corner', intersections)))}"
        )
        assert len(list(filter(lambda inter: inter.type == "notch", intersections))) == 1, (
            f"expected 1 notch intersection, got {len(list(filter(lambda inter: inter.type == 'notch', intersections)))}"
        )
        assert len(list(filter(lambda inter: inter.type == "lap", intersections))) == 1, (
            f"expected 1 lap intersection, got {len(list(filter(lambda inter: inter.type == 'lap', intersections)))}"
        )
