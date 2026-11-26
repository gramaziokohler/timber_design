"""PanelType: a named buildup applied to panels, and the built-in library."""

import os

import pytest
from compas.data import json_dumps
from compas.data import json_loads
from compas.geometry import Point
from compas.geometry import Polyline
from compas_timber.elements import Beam
from compas_timber.elements import Plate

from timber_design_arch.elements import Layer
from timber_design_arch.elements import LayerDefinition
from timber_design_arch.elements import LayerStructure
from timber_design_arch.elements import Panel
from timber_design_arch.model import ArchModel
from timber_design_arch.panel_features import Niche
from timber_design_arch.panel_features import Opening

from timber_design_populator import BoardAgent
from timber_design_populator import CutThroughDetailSet
from timber_design_populator import FramedOpeningDetailSet
from timber_design_populator import PanelPopulator
from timber_design_populator import PanelType
from timber_design_populator import PlateAgent
from timber_design_populator import StudAgent
from timber_design_populator import VoidFramingDetailAgent
from timber_design_populator import get_panel_type
from timber_design_populator import list_panel_types
from timber_design_populator import load_panel_type
from timber_design_populator import save_panel_type
from timber_design_populator import stud_panel

LENGTH, HEIGHT = 4000.0, 2700.0


def _panel(thickness):
    outline = Polyline([Point(0, 0, 0), Point(LENGTH, 0, 0), Point(LENGTH, HEIGHT, 0), Point(0, HEIGHT, 0), Point(0, 0, 0)])
    return Panel.from_outline_thickness(outline, thickness)


def _build(panel_type, thickness=None, make_features=None):
    panel = _panel(thickness or panel_type.thickness or 200.0)
    panel_type.apply(panel)
    for feature in make_features(panel) if make_features else []:
        panel.add_feature(feature)
    model = ArchModel()
    model.add_element(panel)
    panel.merge_layer_structure(model)
    pop = panel_type.populator(panel)
    pop.populate_elements()
    pop.join_elements()
    pop.process_joinery()
    pop.merge_with_model(model)
    return pop, model


def _type():
    layers = LayerStructure(
        [
            LayerDefinition("exterior", 30, sublayer_defs=[LayerDefinition("battens", 30, material="spruce")]),
            LayerDefinition("core", None, material="C24"),
            LayerDefinition("interior", 15, material="OSB"),
        ]
    )
    return PanelType(
        "test_wall",
        layers,
        agents=[BoardAgent("battens", board_width=50, spacing=625, category="batten"), StudAgent("core", stud_spacing=625), PlateAgent("interior")],
        default_detail_sets={Opening: FramedOpeningDetailSet()},
        standard_beam_width=60,
        reference={"source": "test"},
    )


# =============================================================================
# the type
# =============================================================================


def test_agents_refer_to_layers_by_path_after_construction():
    panel_type = _type()
    assert [a.element_layer_paths for a in panel_type.agents] == [[(0, 0)], [(1,)], [(2,)]]
    with pytest.raises(ValueError):
        PanelType("bad", LayerStructure(), agents=[PlateAgent("cladding")])  # no such layer
    with pytest.raises(ValueError):
        PanelType("bad", LayerStructure(), agents=[VoidFramingDetailAgent(layer=(0,))])  # detail agents come from detail sets
    with pytest.raises(ValueError):
        PanelType("bad", LayerStructure(), default_detail_sets={Niche: FramedOpeningDetailSet()})


def test_the_type_round_trips_through_json(tmp_path):
    panel_type = _type()
    for copy in (json_loads(json_dumps(panel_type)), _saved_and_loaded(panel_type, tmp_path)):
        assert type(copy) is PanelType and copy.name == "test_wall" and copy.reference == {"source": "test"}
        assert type(copy.default_detail_sets[Opening]) is FramedOpeningDetailSet
        assert [type(a) for a in copy.agents] == [BoardAgent, StudAgent, PlateAgent]
        assert copy.agents[0].element_layer_paths == [(0, 0)] and copy.layer_structure.layer_defs[1].material == "C24"


def _saved_and_loaded(panel_type, tmp_path):
    filepath = os.path.join(str(tmp_path), "type.json")
    save_panel_type(panel_type, filepath)
    return load_panel_type(filepath)


def test_apply_sets_the_cross_section_and_checks_the_thickness():
    panel = _panel(200)
    _type().apply(panel)
    assert panel.attributes["panel_type"] == "test_wall"
    assert [layer.name for layer in panel.layers] == ["exterior", "core", "interior"]
    assert panel.layers[1].thickness == pytest.approx(155) and panel.layers[1].attributes["material"] == "C24"
    with pytest.raises(ValueError):
        get_panel_type("awrhho05b").apply(_panel(200))  # 247 thick


def test_the_populator_brings_the_types_layers():
    """A panel can enter the model without the type's layers: the populator gives them to it."""
    panel = _panel(200)
    model = ArchModel()
    model.add_element(panel)
    pop = _type().populator(panel)
    assert pop.layer_structure is not None and panel.layers == []
    pop.populate_elements()
    pop.join_elements()
    pop.process_joinery()
    pop.merge_with_model(model)
    assert [layer.name for layer in panel.layers] == ["exterior", "core", "interior"]
    assert {"batten", "stud"} <= {b.attributes.get("category") for b in model.elements() if isinstance(b, Beam)}
    with pytest.raises(ValueError):
        get_panel_type("awrhho05b").populator(_panel(200))  # 247 thick


def test_a_type_builds_its_layers():
    _, model = _build(_type(), 200)
    categories = {b.attributes.get("category") for b in model.elements() if isinstance(b, Beam)}
    assert {"batten", "stud"} <= categories
    assert any(isinstance(p, Plate) for p in model.elements())


def test_a_derived_type_adds_agents_and_replaces_settings():
    panel = _panel(200)
    panel_type = _type()
    panel_type.apply(panel)
    derived = panel_type.derive(name="variant", default_detail_sets={Opening: CutThroughDetailSet()}, standard_beam_width=80, agents=[PlateAgent("battens")])
    pop = PanelPopulator(panel, derived)
    assert pop.panel_type is derived and derived.name == "variant" and derived.reference == {"source": "test"}
    assert type(pop.default_detail_sets[Opening]) is CutThroughDetailSet and pop.standard_beam_width == 80
    assert len(pop.agents) == 4 and derived.agents[-1].element_layer_paths == [(0, 0)]
    assert type(panel_type.default_detail_sets[Opening]) is FramedOpeningDetailSet and len(panel_type.agents) == 3  # the type is unchanged


# =============================================================================
# stud_panel is a stud wall type
# =============================================================================


def test_stud_panel_builds_the_stud_wall_type():
    panel = _panel(200)
    _type().apply(panel)
    pop = stud_panel(panel, standard_beam_width=60, stud_spacing=400)
    assert [type(a).__name__ for a in sorted(pop.agents, key=lambda a: a.layer_path)] == ["PlateAgent", "EdgeAgent", "StudAgent", "PlateAgent"]
    assert next(a for a in pop.agents if isinstance(a, StudAgent)).stud_spacing == 400
    assert {t.__name__ for t in pop.default_detail_sets} == {"Opening", "MEPPenetration", "Niche", "LinearService"}
    assert stud_panel(_panel(200), standard_beam_width=60, stud_spacing=0).agents[-1].__class__.__name__ == "EdgeAgent"


# =============================================================================
# the library
# =============================================================================


@pytest.mark.parametrize("name", list_panel_types())
def test_every_built_in_type_populates_a_wall_with_a_window(name):
    def window(panel):
        outline = Polyline([Point(1200, 900, 0), Point(2400, 900, 0), Point(2400, 2100, 0), Point(1200, 2100, 0), Point(1200, 900, 0)])
        return [Opening.from_outline_panel(outline, panel)]

    pop, model = _build(get_panel_type(name), make_features=window)
    assert pop.debug_info.feature_errors == []
    assert [e for e in pop.debug_info.joint_errors] == []
    layers = [e for e in model.elements() if isinstance(e, Layer)]
    built = {layer.name for layer in layers if any(not isinstance(c, Layer) for c in layer.children)}
    leaves = {layer.name for layer in layers if not layer.sublayers}
    assert built == leaves  # every leaf layer is built


def test_a_stud_wall_builds_its_layers_from_the_sheeting_thicknesses():
    from timber_design_populator import stud_wall_layers
    from timber_design_populator import stud_wall_type

    wall = stud_wall_type(exterior_sheeting_thickness=15, interior_sheeting_thickness=12.5, standard_beam_width=60)
    assert [(d.name, d.thickness) for d in wall.layer_structure.layer_defs] == [("exterior", 15), ("core", None), ("interior", 12.5)]
    assert wall.thickness is None  # fits any panel
    assert [type(a).__name__ for a in wall.agents] == ["PlateAgent", "PlateAgent", "EdgeAgent", "StudAgent"]
    assert [d.name for d in stud_wall_layers(interior_sheeting_thickness=12.5).layer_defs] == ["core", "interior"]
    assert get_panel_type("stud_wall", exterior_sheeting_thickness=15).agents[0].element_layer_paths == [(0,)]
    with pytest.raises(ValueError):
        stud_wall_type(_type().layer_structure, exterior_sheeting_thickness=15)
    _, model = _build(wall, 200)
    plates = {e.parent.name for e in model.elements() if isinstance(e, Plate)}
    assert plates == {"exterior", "interior"}
    assert {"stud"} <= {b.attributes.get("category") for b in model.elements() if isinstance(b, Beam)}


def _without_guids(value):
    if isinstance(value, dict):
        return {k: _without_guids(v) for k, v in value.items() if k != "guid"}
    if isinstance(value, list):
        return [_without_guids(v) for v in value]
    return value


def test_the_shipped_json_files_are_the_factories_defaults():
    """Regenerate them with write_panel_type_files() after changing a factory."""
    import json

    from timber_design_populator.panel_types.library import BUNDLED_TYPES
    from timber_design_populator import list_panel_type_files

    files = list_panel_type_files()
    assert sorted(files) == sorted(BUNDLED_TYPES)
    for name, path in files.items():
        shipped = json.load(open(path, encoding="utf-8"))
        assert _without_guids(shipped) == _without_guids(json.loads(json_dumps(get_panel_type(name)))), name
        assert load_panel_type(name).name == name  # by name, too


def test_written_files_load_and_build(tmp_path):
    from timber_design_populator import write_panel_type_files

    paths = write_panel_type_files(str(tmp_path))
    assert len(paths) == 3
    _, model = _build(load_panel_type(paths[0]))
    assert any(isinstance(e, Beam) and e.attributes.get("category") == "cladding" for e in model.elements())


def test_dataholz_types_cite_their_entry():
    for name in ("awrhho05b", "awrhhi01a", "awmhhi01a"):
        panel_type = get_panel_type(name)
        assert panel_type.reference["source"] == "dataholz.eu" and panel_type.reference["id"] == name
        assert name in panel_type.reference["url"]


def test_library_factories_take_parameters():
    assert get_panel_type("awrhho05b", stud_spacing=400).agents[4].stud_spacing == 400
    with pytest.raises(KeyError):
        get_panel_type("no_such_type")


# =============================================================================
# Grasshopper helpers
# =============================================================================


class _Component:
    def __init__(self):
        self.messages = []

    def AddRuntimeMessage(self, level, text):
        self.messages.append(text)


class _Env:
    def __init__(self):
        self.Component = _Component()


def test_gh_resolve_panel_type(monkeypatch):
    import timber_design_gh.ghcomponent_helpers as helpers

    monkeypatch.setattr(helpers, "Grasshopper", _FakeGrasshopper, raising=False)
    env = _Env()
    assert helpers.resolve_panel_type(env, _type()).name == "test_wall"
    assert helpers.resolve_panel_type(env, "awrhho05b") is None  # names go through CT: Panel Type From JSON
    assert helpers.resolve_panel_type(env, None) is None
    assert len(env.Component.messages) == 2


def test_gh_resolve_panel_type_recreates_a_type_from_a_reloaded_module(monkeypatch):
    """After a module reload, upstream components hold PanelTypes of the previous class object."""
    import timber_design_gh.ghcomponent_helpers as helpers
    import timber_design_populator

    class Reloaded(PanelType):  # stands in for the current class, which the old object is not an instance of
        pass

    monkeypatch.setattr(helpers, "Grasshopper", _FakeGrasshopper, raising=False)
    monkeypatch.setattr(timber_design_populator, "PanelType", Reloaded)
    stale = _type()
    resolved = helpers.resolve_panel_type(_Env(), stale)
    assert resolved is not stale and resolved.name == "test_wall" and len(resolved.agents) == 3


def test_gh_describe_panel_type():
    from timber_design_gh.ghcomponent_helpers import describe_panel_type

    info = describe_panel_type(get_panel_type("awrhho05b"))
    assert info.startswith("awrhho05b (247") and "BoardAgent" in info and "Opening -> FramedOpeningDetailSet" in info


def test_features_made_before_the_layers_are_built_on_them():
    """GH makes features on a layerless panel; the populator gives it layers afterwards."""
    from timber_design_gh.panel_feature_helpers import LinearServiceDefinition
    from timber_design_gh.panel_feature_helpers import MEPPenetrationDefinition
    from timber_design_gh.panel_feature_helpers import NicheDefinition
    from timber_design_gh.panel_feature_helpers import add_feature_definitions

    def square(x, y, size, z=0.0):
        return Polyline([Point(x, y, z), Point(x + size, y, z), Point(x + size, y + size, z), Point(x, y + size, z), Point(x, y, z)])

    panel = _panel(247)
    definitions = [
        NicheDefinition(square(600, 600, 300, z=247), "interior", depth=12),
        MEPPenetrationDefinition(square(2800, 1200, 150, z=100)),
        LinearServiceDefinition(Polyline([Point(100, 300, 0), Point(3900, 300, 0)]), 20),
    ]
    added, skipped, messages = add_feature_definitions(panel, definitions)
    assert len(added) == 3 and not skipped and not messages
    panel_type = get_panel_type("awrhho05b")
    panel = panel.copy()
    panel_type.apply(panel)
    model = ArchModel()
    model.add_element(panel)
    panel.merge_layer_structure(model)
    pop = panel_type.populator(panel)
    pop.populate_elements()
    pop.join_elements()
    pop.process_joinery()
    pop.merge_with_model(model)
    assert pop.debug_info.feature_errors == []
    plates = {e.parent.name: e for e in model.elements() if isinstance(e, Plate)}
    assert len(plates["interior"].features) == len(plates["sheathing"].features) + 1  # the niche pocket, on the interior side only
    machined = [b for b in model.elements() if isinstance(b, Beam) and b.features]
    assert machined  # the service drilled the studs


class _FakeGrasshopper:
    class Kernel:
        class GH_RuntimeMessageLevel:
            Warning, Error, Remark = "warning", "error", "remark"
