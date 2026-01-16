import pytest
from compas.geometry import Point, Line, Vector, Frame, Polyline
from compas.tolerance import TOL

from compas_timber.elements import Panel
from compas_timber.elements import Beam

from timber_design.populators import BeamGeneratorIntersection
from timber_design.populators import split_beam_with_element_generators
from timber_design.populators import is_point_between_beam_edges
from timber_design.populators import extend_beam_to_closest_element_generators


class MockGenerator:
    def __init__(self, polyline=None):
        # edges: list[Line]
        polyline = polyline or Polyline([])
        self.edges = {i: e for i, e in enumerate(polyline.lines)}
        self.outline = polyline

    def cull_element_at_point(self, point):
        return False

class MockLineGeneratorIntersection:
    def __init__(self, edge_index:int):
        self.edge_index = edge_index
        self.point = Point(0,0,0)
        self.dot = 0.0
        self.line = Line([0,0,0], [5,5,0])

@pytest.fixture
def simple_intersections():
    ints_a = [MockLineGeneratorIntersection(i) for i in [0,1,2,3]]
    ints_b = [MockLineGeneratorIntersection(i) for i in [1,2,3,4]]
    return ints_a, ints_b

def test_parse_simple_intersections(simple_intersections, beam):
    intersections, leftovers_a, leftovers_b = BeamGeneratorIntersection._parse_simple_intersections(*simple_intersections, beam, MockGenerator())
    assert len(intersections)==3
    assert leftovers_a[0].edge_index == 0
    assert leftovers_b[0].edge_index == 4

@pytest.fixture
def corner_intersections():
    ints_a = [MockLineGeneratorIntersection(i) for i in [0,3,4]]
    ints_b = [MockLineGeneratorIntersection(i) for i in [1,2,6]]
    return ints_a, ints_b

def test_parse_corner_intersections(corner_intersections, beam):
    intersections, leftovers_a, leftovers_b = BeamGeneratorIntersection._parse_corner_intersections(*corner_intersections, beam, MockGenerator())
    found_edge_indices = [{0,1},{2,3}]
    for inter in intersections:
        assert set(inter.edge_indices) in found_edge_indices
    assert len(intersections)==2
    assert leftovers_a[0].edge_index == 4
    assert leftovers_b[0].edge_index == 6

@pytest.fixture
def notch_intersections():
    ints_a = [MockLineGeneratorIntersection(i) for i in [0,1,4,5,7]] #no notch at (0,1) b.c. 0.line starts inside beam
    ints_b = [MockLineGeneratorIntersection(i) for i in [2,4,6,8,9]]
    return ints_a, ints_b

def test_parse_notch_intersections(notch_intersections, beam):
    intersections, leftovers_a, leftovers_b = BeamGeneratorIntersection._parse_notch_intersections(*notch_intersections, beam, MockGenerator())
    found_edge_indices = [{4,5}, {8,9}]
    for inter in intersections:
        assert set(inter.edge_indices) in found_edge_indices
    assert len(intersections)==2
    assert leftovers_a[0].edge_index == 0
    assert leftovers_b[0].edge_index == 2
    assert len(leftovers_a) == 3
    assert len(leftovers_b) == 3





@pytest.fixture
def beam():
    return Beam.from_endpoints((-5, -5, 0), (30, 30, 0), width=1.0, height=1.0)

def rectangle_edges(xmin, ymin, xmax, ymax):
    p0 = Point(xmin, ymin, 0)
    p1 = Point(xmax, ymin, 0)
    p2 = Point(xmax, ymax, 0)
    p3 = Point(xmin, ymax, 0)
    return Polyline([p0, p1, p2, p3, p0])



def test_get_edge_intersections_returns_lists(points, beam):
    gen = MockGenerator(Polyline(points + [points[0]]))

    a, b = BeamGeneratorIntersection._get_edge_intersections(beam, gen, limit_to_segments=True)
    assert isinstance(a, list)
    assert isinstance(b, list)
    # at least one intersection expected on each side (beam edges)
    assert (len(a)==6 and len(b)==2) or (len(a)==2 and len(b)==6)


def test_from_beam_and_generator_produces_intersections_types():
    beam = Beam.from_endpoints((0, 0, 0), (3, 0, 0), width=0.5, height=0.5)
    rect_polyline = rectangle_edges(1.0, -1.0, 2.0, 1.0)
    gen = MockGenerator(rect_polyline)

    intersections = BeamGeneratorIntersection.from_beam_and_generator(beam, gen, limit_to_segments=True)
    assert isinstance(intersections, list)
    # intersections should include BeamGeneratorIntersection objects
    assert all(hasattr(i, "type") and hasattr(i, "point") for i in intersections)





def test_split_beam_with_element_generators_no_intersection_returns_beam():
    beam = Beam.from_endpoints((0, 0, 0), (1, 0, 0), width=0.1, height=0.1)
    # generator far away
    rect_polyline = rectangle_edges(10.0, 10.0, 11.0, 11.0)
    gen = MockGenerator(rect_polyline)

    tuples, rules = split_beam_with_element_generators(beam, [gen])
    # no intersections -> should return original beam tuple
    assert len(tuples) == 1
    seg, pair = tuples[0]
    assert seg is beam
    assert pair == (None, None)
    assert rules == []


def test_split_beam_with_element_generators_splits_beam():
    beam = Beam.from_endpoints((0, 0, 0), (4, 0, 0), width=0.5, height=0.5)
    rect_polyline = rectangle_edges(1.0, -1.0, 3.0, 1.0)  # beam passes through rectangle from x=1 to x=3
    gen = MockGenerator(rect_polyline)

    tuples, rules = split_beam_with_element_generators(beam, [gen])
    # should have segments: before rectangle, inside removed, after rectangle -> expect at least two segments
    assert isinstance(tuples, list)
    assert len(tuples) >= 2
    # ensure returned segments are Beam-like (have centerline)
    for seg, pair in tuples:
        assert hasattr(seg, "centerline") or seg is None


def test_extend_beam_to_closest_element_generators_extends_and_trims_end():
    beam = Beam.from_endpoints((-5, 0, 0), (0, 0, 0), width=0.5, height=0.5)
    # create generator outline such that intersections at x=1 and x=4
    rect_polyline = rectangle_edges(1.0, -1.0, 4.0, 1.0)
    gen = MockGenerator(rect_polyline)

    extended, bottom_int, top_int = extend_beam_to_closest_element_generators(beam, [gen], only_start=False, only_end=False)
    # extended beam returned (maybe same object) and intersections identified
    assert TOL.is_close(extended.length, 6.0)
    # bottom and top may be BeamGeneratorIntersection or None
    assert bottom_int is None
    assert top_int.generator == gen

def test_extend_beam_to_closest_element_generators_extends_and_trims_start():
    beam = Beam.from_endpoints((5, 0, 0), (10, 0, 0), width=0.5, height=0.5)
    # create generator outline such that intersections at x=1 and x=4
    rect_polyline = rectangle_edges(1.0, -1.0, 4.0, 1.0)
    gen = MockGenerator(rect_polyline)

    extended, bottom_int, top_int = extend_beam_to_closest_element_generators(beam, [gen], only_start=False, only_end=False)
    # extended beam returned (maybe same object) and intersections identified
    assert TOL.is_close(extended.length, 6.0)
    # bottom and top may be BeamGeneratorIntersection or None
    assert top_int is None
    assert bottom_int.generator == gen

def test_extend_beam_to_closest_element_generators_extends_and_trims_start_and_end():
    beam = Beam.from_endpoints((0, 0, 0), (4, 0, 0), width=0.5, height=0.5)
    # create generator outline such that intersections at x=1 and x=4
    rect_polyline_a = rectangle_edges(-10.0, -1.0, -1.0, 1.0)
    rect_polyline_b = rectangle_edges(5.0, -1.0, 10.0, 1.0)
    gen_a = MockGenerator(rect_polyline_a)
    gen_b = MockGenerator(rect_polyline_b)

    extended, bottom_int, top_int = extend_beam_to_closest_element_generators(beam, [gen_a, gen_b], only_start=False, only_end=False)
    # extended beam returned (maybe same object) and intersections identified
    assert TOL.is_close(extended.length, 6.0)
    # bottom and top may be BeamGeneratorIntersection or None
    assert top_int.generator == gen_b
    assert bottom_int.generator == gen_a

def test_extend_beam_to_closest_element_generators_extends_and_trims_only_start():
    beam = Beam.from_endpoints((0, 0, 0), (4, 0, 0), width=0.5, height=0.5)
    # create generator outline such that intersections at x=1 and x=4
    rect_polyline_a = rectangle_edges(-10.0, -1.0, -1.0, 1.0)
    rect_polyline_b = rectangle_edges(5.0, -1.0, 10.0, 1.0)
    gen_a = MockGenerator(rect_polyline_a)
    gen_b = MockGenerator(rect_polyline_b)

    extended, bottom_int, top_int = extend_beam_to_closest_element_generators(beam, [gen_a, gen_b], only_start=True, only_end=False)
    # extended beam returned (maybe same object) and intersections identified
    assert TOL.is_close(extended.length, 5.0)
    # bottom and top may be BeamGeneratorIntersection or None
    assert top_int == None
    assert bottom_int.generator == gen_a

def test_extend_beam_to_closest_element_generators_extends_and_trims_only_end():
    beam = Beam.from_endpoints((0, 0, 0), (4, 0, 0), width=0.5, height=0.5)
    # create generator outline such that intersections at x=1 and x=4
    rect_polyline_a = rectangle_edges(-10.0, -1.0, -1.0, 1.0)
    rect_polyline_b = rectangle_edges(5.0, -1.0, 10.0, 1.0)
    gen_a = MockGenerator(rect_polyline_a)
    gen_b = MockGenerator(rect_polyline_b)

    extended, bottom_int, top_int = extend_beam_to_closest_element_generators(beam, [gen_a, gen_b], only_start=False, only_end=True)
    # extended beam returned (maybe same object) and intersections identified
    assert TOL.is_close(extended.length, 5.0)
    # bottom and top may be BeamGeneratorIntersection or None
    assert top_int.generator == gen_b
    assert bottom_int == None

def test_is_point_between_beam_edges_true_and_false():
    beam = Beam.from_endpoints((0, 0, 0), (4, 0, 0), width=1.0, height=1.0)
    inside_point = Point(2, 0.1, 0)
    outside_point = Point(2, 2.0, 0)
    assert is_point_between_beam_edges(inside_point, beam) is True
    assert is_point_between_beam_edges(outside_point, beam) is False


@pytest.fixture
def points()->list[Point]:
        return  [
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
    expected_indices = [[6], [8, 9], [0, 1], [2, 4]]
    for i in range(len(point_list) - 1):
        point_list.append(point_list.pop(0))
        pl = Polyline(point_list + [point_list[0]])
        gen = MockGenerator(pl)
        intersections = BeamGeneratorIntersection.from_beam_and_generator(beam, gen, limit_to_segments=True)
        assert len(intersections) == 4, f"expected 4 intersections, got {len(intersections)}"
        assert len(list(filter(lambda inter: inter.type == "single", intersections))) == 1, f"expected 1 single intersection, got {len(list(filter(lambda inter: inter.type == 'single', intersections)))}"
        assert len(list(filter(lambda inter: inter.type == "corner", intersections))) == 1, f"expected 1 corner intersection, got {len(list(filter(lambda inter: inter.type == 'corner', intersections)))}"
        assert len(list(filter(lambda inter: inter.type == "notch", intersections))) == 1, f"expected 1 notch intersection, got {len(list(filter(lambda inter: inter.type == 'notch', intersections)))}"
        assert len(list(filter(lambda inter: inter.type == "lap", intersections))) == 1, f"expected 1 lap intersection, got {len(list(filter(lambda inter: inter.type == 'lap', intersections)))}"
        for inter in intersections:
            assert inter.edge_indices in expected_indices
        for i in expected_indices: #increment expected edge_indices to test that they "go around the corner"
            for j in range(len(i)):
                i[j]= (i[j]-1)%(len(points))
