"""LayerDefinition material and attributes: what a buildup says about a layer beyond its thickness."""

import pytest
from compas.data import json_dumps
from compas.data import json_loads
from compas.geometry import Point
from compas.geometry import Polyline

from timber_design_arch.elements import LayerDefinition
from timber_design_arch.elements import LayerStructure
from timber_design_arch.elements import Panel


def _structure():
    return LayerStructure(
        [
            LayerDefinition("interior", 18, material="gypsum fibre board"),
            LayerDefinition("core", None, material="C24", attributes={"fill": "mineral wool", "membrane_a": "vapour retarder"}),
            LayerDefinition("exterior", 69, sublayer_defs=[LayerDefinition("sheathing", 15, material="MDF"), LayerDefinition("battens", 30), LayerDefinition("cladding", 24)]),
        ]
    )


def _panel(structure=None):
    outline = Polyline([Point(0, 0, 0), Point(4000, 0, 0), Point(4000, 2700, 0), Point(0, 2700, 0), Point(0, 0, 0)])
    return Panel.from_outline_thickness(outline, 247, layer_structure=structure or _structure())


def _by_name(layers):
    result = {}
    for layer in layers:
        result[layer.name] = layer
        result.update(_by_name(layer.sublayers))
    return result


def test_definitions_keep_material_and_attributes_through_json():
    copy = json_loads(json_dumps(_structure()))
    core = copy.layer_defs[1]
    assert core.material == "C24" and core.attributes == {"fill": "mineral wool", "membrane_a": "vapour retarder"}
    assert copy.layer_defs[2].sublayer_defs[0].material == "MDF"
    assert copy.layer_defs[2].material is None and copy.layer_defs[2].attributes == {}


def test_layers_carry_their_definition_material_and_attributes():
    layers = _by_name(_panel().layers)
    assert layers["interior"].attributes == {"material": "gypsum fibre board"}
    assert layers["core"].attributes == {"material": "C24", "fill": "mineral wool", "membrane_a": "vapour retarder"}
    assert layers["core"].thickness == pytest.approx(160)
    assert layers["sheathing"].attributes["material"] == "MDF"
    assert "material" not in layers["battens"].attributes


def test_layers_keep_material_through_panel_json():
    layers = _by_name(json_loads(json_dumps(_panel())).layers)
    assert layers["core"].attributes["material"] == "C24" and layers["core"].attributes["fill"] == "mineral wool"
    assert layers["sheathing"].attributes["material"] == "MDF"


def test_reserved_keys_are_refused():
    with pytest.raises(ValueError):
        LayerDefinition("core", attributes={"name": "x"})
    with pytest.raises(ValueError):
        LayerDefinition("core", attributes={"material": "C24"})  # use material=
