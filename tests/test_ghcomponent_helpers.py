from types import SimpleNamespace

from timber_design.ghpython.ghcomponent_helpers import brep_loop_vertex_indices


def _loop(*edges):
    vertex = lambda i: SimpleNamespace(native_vertex=SimpleNamespace(VertexIndex=i))  # noqa: E731
    return SimpleNamespace(edges=[SimpleNamespace(start_vertex=vertex(a), end_vertex=vertex(b)) for a, b in edges])


def test_loop_forward_edges():
    assert brep_loop_vertex_indices(_loop((0, 1), (1, 2), (2, 3), (3, 0)), None) == [0, 1, 2, 3, 0]


def test_loop_first_edge_reversed():
    # the loop runs 0-1-2-3 but its first edge is stored 1->0; the old helper returned [1, 0, 2, 3, 1]
    assert brep_loop_vertex_indices(_loop((1, 0), (1, 2), (2, 3), (3, 0)), None) == [0, 1, 2, 3, 0]


def test_loop_middle_edges_reversed():
    assert brep_loop_vertex_indices(_loop((0, 1), (2, 1), (3, 2), (3, 0)), None) == [0, 1, 2, 3, 0]


def test_loop_vertex_lookup_without_native_vertices():
    points = [(0, 0, 0), (1, 0, 0), (1, 1, 0)]
    brep = SimpleNamespace(vertices=[SimpleNamespace(point=p) for p in points])
    vertex = lambda i: SimpleNamespace(point=points[i])  # noqa: E731
    loop = SimpleNamespace(edges=[SimpleNamespace(start_vertex=vertex(a), end_vertex=vertex(b)) for a, b in ((1, 0), (1, 2), (2, 0))])
    assert brep_loop_vertex_indices(loop, brep) == [0, 1, 2, 0]
