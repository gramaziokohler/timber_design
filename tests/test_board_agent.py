"""BoardAgent: parallel members on a panel-anchored grid (battens, cladding), and StudAgent as one of them."""

import pytest
from compas.data import json_dumps
from compas.data import json_loads
from compas.geometry import Point
from compas.geometry import Polyline
from compas.geometry import Vector
from compas_timber.elements import Beam

from timber_design_arch.elements import LayerDefinition
from timber_design_arch.elements import LayerStructure
from timber_design_arch.elements import Panel
from timber_design_arch.model import ArchModel

from timber_design_populator import BoardAgent
from timber_design_populator import EdgeAgent
from timber_design_populator import PanelPopulator
from timber_design_populator import PanelType
from timber_design_populator import StudAgent

LENGTH, HEIGHT = 4000.0, 2700.0


def _structure():
    return LayerStructure(
        [
            LayerDefinition("core", None),
            LayerDefinition("exterior", 54, sublayer_defs=[LayerDefinition("battens", 30), LayerDefinition("cladding", 24)]),
        ]
    )


def _panel(outline=None):
    outline = outline or Polyline([Point(0, 0, 0), Point(LENGTH, 0, 0), Point(LENGTH, HEIGHT, 0), Point(0, HEIGHT, 0), Point(0, 0, 0)])
    return Panel.from_outline_thickness(outline, 214, layer_structure=_structure())


def _populate(panel, make_agents):
    model = ArchModel()
    model.add_element(panel)
    panel.merge_layer_structure(model)
    pop = PanelPopulator(panel, PanelType("test", panel.layer_structure, agents=make_agents(panel), standard_beam_width=60))
    pop.populate_elements()
    return pop


def _path(panel, name):
    return panel.layer_structure.get_path_for_name(name)


def _beams(pop, category):
    return [b for b in pop.model.elements() if isinstance(b, Beam) and b.attributes.get("category") == category]


def _x(beam):
    return round((beam.centerline.start[0] + beam.centerline.end[0]) / 2.0, 6)


def test_battens_sit_on_the_grid_inside_the_layer_and_are_clipped_to_it():
    pop = _populate(_panel(), lambda p: [BoardAgent(_path(p, "battens"), board_width=50, spacing=625, category="batten")])
    battens = _beams(pop, "batten")
    assert sorted(_x(b) for b in battens) == [625.0 * k for k in range(1, 7)]  # x = 0 would stick out by half a width
    for batten in battens:
        assert batten.width == 50 and batten.height == pytest.approx(30)
        assert batten.length == pytest.approx(HEIGHT)


def test_an_offset_moves_the_grid():
    pop = _populate(_panel(), lambda p: [BoardAgent(_path(p, "battens"), board_width=50, spacing=625, offset=25, category="batten")])
    assert sorted(_x(b) for b in _beams(pop, "batten")) == [25.0 + 625.0 * k for k in range(0, 7)]


def test_horizontal_boards_run_along_x():
    pop = _populate(_panel(), lambda p: [BoardAgent(_path(p, "cladding"), board_width=146, spacing=150, direction=Vector(1, 0, 0), category="cladding")])
    boards = _beams(pop, "cladding")
    assert len(boards) == 17  # y = 150 k, k = 1..17: at y = 0 and 2700 a board would stick out by half its width
    for board in boards:
        assert abs(board.centerline.direction[1]) < 1e-9 and board.length == pytest.approx(LENGTH)


def test_battens_line_up_with_the_studs_below():
    def agents(p):
        return [
            EdgeAgent(p.core_layer),
            StudAgent(p.core_layer, stud_spacing=625),
            BoardAgent(_path(p, "battens"), board_width=50, spacing=625, category="batten"),
        ]

    pop = _populate(_panel(), agents)
    stud_x = {_x(s) for s in _beams(pop, "stud")}
    assert stud_x and stud_x <= {_x(b) for b in _beams(pop, "batten")}


def test_boards_are_clipped_to_a_sloped_outline():
    outline = Polyline([Point(0, 0, 0), Point(LENGTH, 0, 0), Point(LENGTH, HEIGHT + 1000, 0), Point(0, HEIGHT, 0), Point(0, 0, 0)])
    pop = _populate(_panel(outline), lambda p: [BoardAgent(_path(p, "battens"), board_width=50, spacing=1000, category="batten")])
    lengths = sorted(round(b.length, 3) for b in _beams(pop, "batten"))
    assert lengths == pytest.approx([HEIGHT + 250, HEIGHT + 500, HEIGHT + 750])


def test_the_category_and_width_are_per_agent():
    batten = BoardAgent((1, 0), board_width=50, category="batten")
    board = BoardAgent((1, 1), category="cladding")
    assert batten.BEAM_CATEGORY_NAMES == ["batten"] and board.BEAM_CATEGORY_NAMES == ["cladding"]
    assert BoardAgent.BEAM_CATEGORY_NAMES == []
    pop = _populate(_panel(), lambda p: [BoardAgent(_path(p, "battens"), category="batten")])  # width from standard_beam_width
    assert all(b.width == 60 for b in _beams(pop, "batten"))


def test_board_agents_round_trip():
    agent = BoardAgent((1, 1), board_width=146, spacing=150, direction=Vector(1, 1, 0), offset=10, category="cladding")
    for copy in (agent.clone(), json_loads(json_dumps(agent))):
        assert type(copy) is BoardAgent and copy.category == "cladding" and copy.beam_widths == {"cladding": 146}
        assert copy.spacing == 150 and copy.offset == 10 and list(copy.direction) == pytest.approx(list(Vector(1, 1, 0).unitized()))


def test_the_stud_agent_is_a_board_agent_of_studs():
    agent = StudAgent((0,), stud_width=60, stud_spacing=625)
    assert isinstance(agent, BoardAgent) and agent.category == "stud" and agent.stud_spacing == 625
    for copy in (agent.clone(), json_loads(json_dumps(agent))):
        assert type(copy) is StudAgent and copy.beam_widths == {"stud": 60} and copy.stud_spacing == 625
    assert StudAgent((0,), category="batten").category == "stud"  # other agents rely on "stud"


def test_a_direction_out_of_the_panel_plane_is_refused():
    with pytest.raises(ValueError):
        BoardAgent((0,), direction=Vector(0, 0, 1))


def _boards_in_model(direction, opening=None):
    """Boards (in model space) of a cladding layer cut through by *opening* (x0, x1, y0, y1)."""
    from timber_design_arch.panel_features import Opening
    from timber_design_populator import CutThroughDetailSet

    panel = _panel()
    if opening:
        x0, x1, y0, y1 = opening
        outline = Polyline([Point(x0, y0, 0), Point(x1, y0, 0), Point(x1, y1, 0), Point(x0, y1, 0), Point(x0, y0, 0)])
        panel.add_feature(Opening.from_outline_panel(outline, panel))
    spacing, width = (150, 146) if direction[0] else (625, 50)
    model = ArchModel()
    model.add_element(panel)
    panel.merge_layer_structure(model)
    pop = PanelPopulator(
        panel,
        PanelType(
            "test",
            panel.layer_structure,
            agents=[BoardAgent(_path(panel, "cladding"), board_width=width, spacing=spacing, direction=direction, category="board")],
            default_detail_sets={Opening: CutThroughDetailSet()},
            standard_beam_width=60,
        ),
    )
    pop.populate_elements()
    pop.merge_with_model(model)
    return [b for b in model.elements() if isinstance(b, Beam) and b.attributes.get("category") == "board"]


def _across(beam, direction):
    """The board's position across its direction, in model space."""
    return round(beam.centerline.midpoint[1] if direction[0] else beam.centerline.midpoint[0], 6)


@pytest.mark.parametrize("direction", [Vector(1, 0, 0), Vector(0, 1, 0)])
def test_boards_straddling_an_opening_edge_are_cut_back_in_any_direction(direction):
    """A board whose width an opening's edge runs through loses the piece beside the opening."""
    centres = sorted({_across(b, direction) for b in _boards_in_model(direction)})
    edge = centres[len(centres) // 2]  # an opening edge right on a board's centerline
    if direction[0]:
        opening = (1250.0, 2500.0, edge, edge + 1200.0)
    else:
        opening = (edge, edge + 1200.0, 900.0, 2100.0)
    x0, x1, y0, y1 = opening
    boards = _boards_in_model(direction, opening)
    for board in boards:
        xs = [p[0] for p in board.blank.points]
        ys = [p[1] for p in board.blank.points]
        overlap_x = min(max(xs), x1) - max(min(xs), x0)
        overlap_y = min(max(ys), y1) - max(min(ys), y0)
        assert not (overlap_x > 1 and overlap_y > 1), "a board overlaps the opening"
    assert len([b for b in boards if _across(b, direction) == edge]) == 2  # the straddling board is kept on both sides
