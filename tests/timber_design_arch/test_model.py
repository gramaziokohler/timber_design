import pytest

from compas.data import json_dumps, json_loads
from compas.geometry import Frame
from compas.geometry import Point
from compas.geometry import Polyline
from compas_pb import pb_dump_bts

from compas_timber.connections import JointTopology
from compas_timber.connections import PlateJointCandidate
from compas_timber.connections.candidate_dispatch import _plate_connection_candidate
from compas_timber.connections.candidate_dispatch import find_connection_handler
from compas_timber.elements import Beam
from compas_timber.model import TimberModel

from timber_design_arch.connections import PanelMiterJoint
from timber_design_arch.elements import Layer
from timber_design_arch.elements import LayerDefinition
from timber_design_arch.elements import LayerStructure
from timber_design_arch.elements import Panel
from timber_design_arch.model import ArchModel


def _corner_panels():
    polyline_a = Polyline([Point(0, 0, 0), Point(0, 10, 0), Point(10, 10, 0), Point(10, 0, 0), Point(0, 0, 0)])
    polyline_b = Polyline([Point(0, 10, 0), Point(10, 10, 0), Point(20, 20, 10), Point(0, 20, 10), Point(0, 10, 0)])
    return Panel.from_outline_thickness(polyline_a, 1), Panel.from_outline_thickness(polyline_b, 1)


def test_arch_model_is_a_timber_model():
    assert isinstance(ArchModel(), TimberModel)


def test_panels_and_layers_return_arch_types():
    model = ArchModel()
    structure = LayerStructure([LayerDefinition(name="a", thickness=0.5), LayerDefinition(name="b", thickness=0.5)])
    panel = Panel(frame=Frame.worldXY(), length=10, width=10, thickness=1, layer_structure=structure)
    model.add_element(panel)
    panel.merge_layer_structure(model)
    model.add_element(Beam(Frame.worldXY(), 10, 1, 1))

    assert model.panels == [panel]
    assert len(model.layers) == 2
    assert all(isinstance(layer, Layer) for layer in model.layers)
    assert len(model.beams) == 1


def test_panel_pair_dispatches_to_plate_handler():
    panel_a, panel_b = _corner_panels()
    assert find_connection_handler(panel_a, panel_b) is _plate_connection_candidate


def test_compute_topologies_finds_arch_panels():
    model = ArchModel()
    panel_a, panel_b = _corner_panels()
    model.add_element(panel_a)
    model.add_element(panel_b)

    model.connect_adjacent_panels()

    candidates = list(model.joint_candidates)
    assert len(candidates) == 1
    assert isinstance(candidates[0], PlateJointCandidate)
    assert candidates[0].topology == JointTopology.TOPO_EDGE_EDGE
    assert set(candidates[0].elements) == {panel_a, panel_b}


def test_json_round_trip_keeps_arch_types():
    model = ArchModel()
    panel_a, panel_b = _corner_panels()
    model.add_element(panel_a)
    model.add_element(panel_b)
    model.add_joint(PanelMiterJoint(panel_a, panel_b, topology=JointTopology.TOPO_EDGE_EDGE, a_segment_index=1, b_segment_index=0))

    restored = json_loads(json_dumps(model))

    assert isinstance(restored, ArchModel)
    assert len(restored.panels) == 2
    assert all(isinstance(p, Panel) for p in restored.panels)
    joints = list(restored.joints)
    assert len(joints) == 1
    assert isinstance(joints[0], PanelMiterJoint)


@pytest.mark.parametrize("model_cls", [ArchModel, TimberModel])
def test_protobuf_refuses_arch_types_instead_of_losing_them(model_cls):
    # compas_timber's protobuf wrappers have no slot for timber_design_arch types, so writing one
    # would silently fall back to a compas_timber base class. The guard must raise instead.
    model = model_cls()
    panel_a, _ = _corner_panels()
    model.add_element(panel_a)

    with pytest.raises(NotImplementedError, match="timber_design_arch does not support protobuf"):
        pb_dump_bts(model)


def test_protobuf_still_works_for_timber_only_models():
    model = TimberModel()
    model.add_element(Beam(Frame.worldXY(), 10, 1, 1))
    assert pb_dump_bts(model)
