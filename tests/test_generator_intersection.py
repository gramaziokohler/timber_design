import pytest
from compas.geometry import Point, Line, Vector, Frame, Polyline

from compas_timber.elements import Panel
from compas_timber.elements import Beam

from timber_design.populators import BeamGeneratorIntersection
from timber_design.populators import split_beam_with_element_generators
from timber_design.populators import is_point_between_beam_edges
from timber_design.populators import extend_beam_to_closest_element_generators


class MockGenerator:
    def __init__(self, edges):
        # edges: list[Line]
        self.edges = {i: e for i, e in enumerate(edges)}
        self.outline = Polyline([e.start for e in edges] + [edges[0].start])

    def cull_element_at_point(self, point):
        return False

@pytest.fixture
def points():
        points: list[Point] = [
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

@pytest.fixture
def beam():
    beam = Beam((-5, -5, 0), (30, 30, 0), width=1.0)

def rectangle_edges(xmin, ymin, xmax, ymax):
    p0 = Point(xmin, ymin, 0)
    p1 = Point(xmax, ymin, 0)
    p2 = Point(xmax, ymax, 0)
    p3 = Point(xmin, ymax, 0)
    return [Line(p0, p1), Line(p1, p2), Line(p2, p3), Line(p3, p0)]


def test_get_edge_intersections_returns_lists(points, beam):
    gen = MockGenerator(Polyline(points + [points[0]])

    a, b = BeamGeneratorIntersection._get_edge_intersections(beam, gen, limit_to_segments=True)
    assert isinstance(a, list)
    assert isinstance(b, list)
    # at least one intersection expected on each side (beam edges)
    assert len(a)==6 or len(b)==2


def test_from_beam_and_generator_produces_intersections_types():
    beam = Beam.from_endpoints((0, 0, 0), (3, 0, 0), width=0.5)
    edges = rectangle_edges(1.0, -1.0, 2.0, 1.0)
    gen = MockGenerator(edges)

    intersections = gi.BeamGeneratorIntersection.from_beam_and_generator(beam, gen, limit_to_segments=True)
    assert isinstance(intersections, list)
    # intersections should include BeamGeneratorIntersection objects
    assert all(hasattr(i, "type") and hasattr(i, "point") for i in intersections)


def test_split_beam_with_element_generators_no_intersection_returns_beam():
    beam = Beam((0, 0, 0), (1, 0, 0), width=0.1)
    # generator far away
    edges = rectangle_edges(10.0, 10.0, 11.0, 11.0)
    gen = MockGenerator(edges)

    tuples, rules = split_beam_with_element_generators(beam, [gen])
    # no intersections -> should return original beam tuple
    assert len(tuples) == 1
    seg, pair = tuples[0]
    assert seg is beam
    assert pair == (None, None)
    assert rules == []


def test_split_beam_with_element_generators_splits_beam():
    beam = Beam((0, 0, 0), (4, 0, 0), width=0.5)
    edges = rectangle_edges(1.0, -1.0, 3.0, 1.0)  # beam passes through rectangle from x=1 to x=3
    gen = MockGenerator(edges)

    tuples, rules = split_beam_with_element_generators(beam, [gen])
    # should have segments: before rectangle, inside removed, after rectangle -> expect at least two segments
    assert isinstance(tuples, list)
    assert len(tuples) >= 2
    # ensure returned segments are Beam-like (have centerline)
    for seg, pair in tuples:
        assert hasattr(seg, "centerline") or seg is None


def test_extend_beam_to_closest_element_generators_extends_and_trims():
    beam = Beam((0, 0, 0), (5, 0, 0), width=0.5)
    # create generator outline such that intersections at x=1 and x=4
    edges = rectangle_edges(1.0, -1.0, 4.0, 1.0)
    gen = MockGenerator(edges)

    extended, bottom_int, top_int = extend_beam_to_closest_element_generators(beam, [gen], only_start=False, only_end=False)
    # extended beam returned (maybe same object) and intersections identified
    assert hasattr(extended, "centerline")
    # bottom and top may be BeamGeneratorIntersection or None
    assert (bottom_int is None) or hasattr(bottom_int, "dot")
    assert (top_int is None) or hasattr(top_int, "dot")


def test_is_point_between_beam_edges_true_and_false():
    beam = Beam((0, 0, 0), (4, 0, 0), width=1.0)
    inside_point = Point(2, 0.1, 0)
    outside_point = Point(2, 2.0, 0)
    assert is_point_between_beam_edges(inside_point, beam) is True
    assert is_point_between_beam_edges(outside_point, beam) is False


def test_intersections_from_beam_and_generator(points):
    point_list: list[Point] = [p for p in points]

    for i in range(len(point_list) - 1):
        point_list.append(point_list.pop(0))
        pl = Polyline(point_list + [point_list[0]])
        gen = MockGenerator({i: e for i, e in enumerate(pl.lines)})
        intersections = BeamGeneratorIntersection.from_beam_and_generator(beam, gen, limit_to_segments=True)
        assert len(intersections) == 4, f"expected 4 intersections, got {len(intersections)}"
        assert len(list(filter(lambda inter: inter.type == "single", intersections))) == 1)), f"expected 1 single intersection, got {len(list(filter(lambda inter: inter.type == 'single', intersections)))}"
        assert len(list(filter(lambda inter: inter.type == "corner", intersections))) == 1)), f"expected 1 single intersection, got {len(list(filter(lambda inter: inter.type == 'corner', intersections)))}"
        assert len(list(filter(lambda inter: inter.type == "notch", intersections))) == 1)), f"expected 1 single intersection, got {len(list(filter(lambda inter: inter.type == 'notch', intersections)))}"
        assert len(list(filter(lambda inter: inter.type == "lap", intersections))) == 1)), f"expected 1 single intersection, got {len(list(filter(lambda inter: inter.type == 'lap', intersections)))}"

