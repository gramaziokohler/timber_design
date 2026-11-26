"""Tests for what a PanelJoint writes into its PanelConnectionInterfaces, and LayerStructure.resolve."""

import pytest

from compas.data import json_dumps
from compas.data import json_loads
from compas.geometry import Point
from compas.geometry import Polyline

from compas_timber.connections import JointTopology
from timber_design_arch.connections import PanelLButtJoint
from timber_design_arch.connections import PanelMiterJoint
from timber_design_arch.elements import LayerDefinition
from timber_design_arch.elements import LayerRole
from timber_design_arch.elements import LayerStructure
from timber_design_arch.elements import Panel
from timber_design_arch.panel_features import InterfaceRole
from timber_design_arch.panel_features import Opening


def _three_layer_structure():
    return LayerStructure(
        layer_defs=[
            LayerDefinition("exterior", 0.2),
            LayerDefinition("core"),
            LayerDefinition("interior", 0.2, sublayer_defs=[LayerDefinition("battens", 0.15), LayerDefinition("board")]),
        ]
    )


def _corner_panels():
    """Two 10x10 panels meeting edge-to-edge at a 45 degree corner, thicknesses 1 and 2."""
    polyline_a = Polyline([Point(0, 0, 0), Point(0, 10, 0), Point(10, 10, 0), Point(10, 0, 0), Point(0, 0, 0)])
    panel_a = Panel.from_outline_thickness(polyline_a, 1)
    polyline_b = Polyline([Point(0, 10, 0), Point(10, 10, 0), Point(20, 20, 10), Point(0, 20, 10), Point(0, 10, 0)])
    panel_b = Panel.from_outline_thickness(polyline_b, 2)
    return panel_a, panel_b


def _joined(joint_type=PanelLButtJoint, **kwargs):
    panel_a, panel_b = _corner_panels()
    panel_b.layer_structure = _three_layer_structure()
    joint = joint_type(panel_a, panel_b, topology=JointTopology.TOPO_EDGE_EDGE, a_segment_index=1, b_segment_index=0, **kwargs)
    joint.add_extensions()
    for panel in (panel_a, panel_b):
        panel.apply_edge_extensions()
    joint.add_features()
    return panel_a, panel_b, joint


# ---------------------------------------------------------------------------
# LayerStructure.resolve
# ---------------------------------------------------------------------------


def test_resolve_fills_the_none_slot_and_walks_sublayers():
    slots = _three_layer_structure().resolve(2.0)
    by_path = {slot.layer_path: slot for slot in slots}

    assert [slot.layer_path for slot in slots] == [(0,), (1,), (2,), (2, 0), (2, 1)]
    assert by_path[(1,)].start == pytest.approx(0.2)
    assert by_path[(1,)].end == pytest.approx(1.8)  # fill slot absorbs 2.0 - 0.4
    assert by_path[(2, 0)].start == pytest.approx(1.8)
    assert by_path[(2, 1)].end == pytest.approx(2.0)
    assert by_path[(2, 1)].role == LayerRole.INTERIOR  # sublayers carry their root's role


def test_resolve_matches_attached_layers():
    panel_a, _ = _corner_panels()
    panel_a.layer_structure = _three_layer_structure()
    slots = {slot.layer_path: slot for slot in panel_a.layer_structure.resolve(panel_a.thickness)}

    for layer in panel_a.get_leaf_layers() + panel_a.layers:
        assert slots[layer.layer_path].start == pytest.approx(layer.start_offset)
        assert slots[layer.layer_path].end - slots[layer.layer_path].start == pytest.approx(layer.thickness)


def test_resolve_raises_on_overfull_structure():
    with pytest.raises(ValueError):
        LayerStructure([LayerDefinition("core", 3.0)]).resolve(2.0)


# ---------------------------------------------------------------------------
# roles and details
# ---------------------------------------------------------------------------


def test_butt_joint_sets_main_and_cross_roles():
    panel_a, panel_b, _ = _joined()
    assert panel_a.interfaces[0].interface_role == InterfaceRole.MAIN
    assert panel_b.interfaces[0].interface_role == InterfaceRole.CROSS


def test_miter_joint_roles_are_none():
    panel_a, panel_b, _ = _joined(PanelMiterJoint)
    assert panel_a.interfaces[0].interface_role == InterfaceRole.NONE
    assert panel_b.interfaces[0].interface_role == InterfaceRole.NONE


def test_an_interface_carries_only_its_edge_role_and_detail_set():
    panel_a, _, _ = _joined()
    interface = panel_a.interfaces[0]
    data = interface.__data__
    assert interface.edge_index == 1
    assert interface.detail_set is None  # a plain joint builds no connection detail
    for removed in ("partner_layer_structure", "partner_thickness", "partner_frame", "detail_agents"):
        assert removed not in data


# ---------------------------------------------------------------------------
# detail_set on features
# ---------------------------------------------------------------------------

# The feature treats its detail set as opaque: any data object does here.
DETAIL_SET = Point(1, 2, 3)


def test_detail_set_defaults_to_none_and_serializes():
    panel_a, _ = _corner_panels()
    opening = Opening.from_outline_panel(_outline_on_panel_a(), panel_a, detail_set=DETAIL_SET)
    assert opening.detail_set == DETAIL_SET
    copied = json_loads(json_dumps(opening))
    assert copied.detail_set == DETAIL_SET
    assert Opening.from_outline_panel(_outline_on_panel_a(), panel_a).detail_set is None


def test_interface_serialization_round_trip():
    panel_a, _, _ = _joined()
    interface = panel_a.interfaces[0]
    interface.detail_set = DETAIL_SET
    copied = json_loads(json_dumps(interface))
    assert copied.detail_set == DETAIL_SET
    assert copied.interface_role == InterfaceRole.MAIN
    assert copied.edge_index == interface.edge_index


def _outline_on_panel_a():
    return Polyline([Point(2, 2, 0), Point(4, 2, 0), Point(4, 4, 0), Point(2, 4, 0), Point(2, 2, 0)])
