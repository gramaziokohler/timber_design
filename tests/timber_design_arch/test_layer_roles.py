import pytest
from compas.data import json_dumps
from compas.data import json_loads
from compas.geometry import Frame
from compas.geometry import Point
from compas.geometry import Polyline

from timber_design_arch.elements import LayerDefinition
from timber_design_arch.elements import LayerRole
from timber_design_arch.elements import LayerStructure
from timber_design_arch.elements import Panel
from timber_design_arch.panel_features import Niche


@pytest.fixture
def flat_panel():
    """10 x 20 panel, thickness 1, flat in XY."""
    outline_a = Polyline([Point(0, 0, 0), Point(0, 20, 0), Point(10, 20, 0), Point(10, 0, 0), Point(0, 0, 0)])
    return Panel.from_outline_thickness(outline_a, 1)


def _named_structure():
    """Role layers with custom names; the exterior layer is subdivided."""
    return LayerStructure(
        layer_defs=[
            LayerDefinition(
                name="cladding",
                thickness=0.2,
                role=LayerRole.EXTERIOR,
                sublayer_defs=[LayerDefinition(name="boards", thickness=0.05), LayerDefinition(name="battens")],
            ),
            LayerDefinition(name="studs", role=LayerRole.CORE),
            LayerDefinition(name="osb", thickness=0.1, role="interior"),
        ]
    )


def test_role_values_are_explicit_strings():
    assert [role.value for role in LayerRole] == ["exterior", "core", "interior"]
    assert LayerRole("core") is LayerRole.CORE


def test_role_layers_resolve_by_role_not_name(flat_panel):
    flat_panel.layer_structure = _named_structure()

    assert flat_panel.exterior_layer.name == "cladding"
    assert flat_panel.core_layer.name == "studs"
    assert flat_panel.interior_layer.name == "osb"
    assert flat_panel.layer_for_role("core") is flat_panel.core_layer


def test_sublayers_carry_their_root_layer_role(flat_panel):
    flat_panel.layer_structure = _named_structure()

    exterior = flat_panel.exterior_layer
    assert exterior.role == LayerRole.EXTERIOR
    assert [sub.role for sub in exterior.sublayers] == [LayerRole.EXTERIOR, LayerRole.EXTERIOR]
    assert flat_panel.core_layer.role == LayerRole.CORE


def test_define_sublayers_carries_role(flat_panel):
    flat_panel.layer_structure = _named_structure()

    subs = flat_panel.core_layer.define_sublayers([0.1, None])
    assert [sub.role for sub in subs] == [LayerRole.CORE, LayerRole.CORE]


def test_root_definition_named_after_a_role_gets_that_role(flat_panel):
    flat_panel.layer_structure = LayerStructure(
        layer_defs=[LayerDefinition(name="exterior", thickness=0.2), LayerDefinition(name="core"), LayerDefinition(name="interior", thickness=0.2)]
    )

    assert [layer.role for layer in flat_panel.layers] == [LayerRole.EXTERIOR, LayerRole.CORE, LayerRole.INTERIOR]


def test_sublayer_named_after_a_role_gets_no_role():
    structure = LayerStructure(layer_defs=[LayerDefinition(name="frame", sublayer_defs=[LayerDefinition(name="core")])])

    assert structure.layer_defs[0].role is None
    assert structure.layer_defs[0].sublayer_defs[0].role is None
    assert structure.get_path_for_role(LayerRole.CORE) is None


def test_default_structure_is_a_single_core_layer(flat_panel):
    assert [layer.role for layer in flat_panel.layers] == [LayerRole.CORE]
    assert flat_panel.core_layer is flat_panel.layers[0]
    assert flat_panel.exterior_layer is None


def test_repeated_role_raises():
    with pytest.raises(ValueError, match="repeated: core"):
        LayerStructure(layer_defs=[LayerDefinition(name="a", role=LayerRole.CORE), LayerDefinition(name="core", thickness=0.1)])


def test_role_on_sublayer_definition_raises():
    with pytest.raises(ValueError, match="Only root layer definitions"):
        LayerStructure(layer_defs=[LayerDefinition(name="a", sublayer_defs=[LayerDefinition(name="b", role=LayerRole.CORE)])])


def test_roles_survive_serialization(flat_panel):
    flat_panel.layer_structure = _named_structure()

    structure = json_loads(json_dumps(flat_panel.layer_structure))
    assert [d.role for d in structure.layer_defs] == [LayerRole.EXTERIOR, LayerRole.CORE, LayerRole.INTERIOR]

    copied = json_loads(json_dumps(flat_panel))
    assert copied.core_layer.name == "studs"
    assert copied.exterior_layer.sublayers[0].role == LayerRole.EXTERIOR

    layer = json_loads(json_dumps(flat_panel.interior_layer))
    assert layer.role == LayerRole.INTERIOR


def test_niche_side_is_a_surface_role():
    outline = Polyline([Point(0, 0, 0), Point(1, 0, 0), Point(1, 1, 0), Point(0, 1, 0), Point(0, 0, 0)])

    assert Niche(Frame.worldXY(), outline, "exterior", 5).side == LayerRole.EXTERIOR
    with pytest.raises(ValueError, match="side"):
        Niche(Frame.worldXY(), outline, LayerRole.CORE, 5)

    copied = json_loads(json_dumps(Niche(Frame.worldXY(), outline, LayerRole.INTERIOR, 5)))
    assert copied.side == LayerRole.INTERIOR


def test_niche_without_depth_goes_through_the_framing_layer():
    outline = Polyline([Point(0, 0, 0), Point(1, 0, 0), Point(1, 1, 0), Point(0, 1, 0), Point(0, 0, 0)])

    niche = Niche(Frame.worldXY(), outline, LayerRole.EXTERIOR)
    assert niche.depth is None
    assert json_loads(json_dumps(niche)).depth is None
