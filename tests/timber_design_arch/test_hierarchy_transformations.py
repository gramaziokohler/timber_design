"""Placement of panels, their layers and their children in the model tree, moved here from compas_timber."""

import math

import pytest
from compas.data import json_dumps
from compas.data import json_loads
from compas.geometry import Frame
from compas.geometry import Line
from compas.geometry import Point
from compas.geometry import Polyline
from compas.geometry import Reflection
from compas.geometry import Rotation
from compas.geometry import Scale
from compas.geometry import Translation
from compas.geometry import Vector
from compas.tolerance import TOL

from compas_timber.elements import Beam
from compas_timber.elements import Plate

from timber_design_arch.elements import LayerDefinition
from timber_design_arch.elements import LayerStructure
from timber_design_arch.elements import Panel
from timber_design_arch.model import ArchModel

T = Translation.from_vector([500, -300, 1000]) * Rotation.from_axis_and_angle([0, 0, 1], math.radians(35))


def assert_same_frame(a, b):
    assert TOL.is_allclose(a.point, b.point)
    assert TOL.is_allclose(a.xaxis, b.xaxis)
    assert TOL.is_allclose(a.yaxis, b.yaxis)


@pytest.fixture
def panel_model():
    model = ArchModel()
    outline = Polyline([Point(1000, 0, 0), Point(4000, 0, 0), Point(4000, 2400, 0), Point(1000, 2400, 0), Point(1000, 0, 0)])
    panel = Panel.from_outline_thickness(outline, 200)
    panel.layer_structure = LayerStructure(layer_defs=[LayerDefinition("exterior", 50), LayerDefinition("core"), LayerDefinition("interior", 50)])
    model.add_element(panel)
    panel.merge_layer_structure(model)
    # beams are placed in the panel's local coordinates
    beam_a = Beam.from_centerline(Line(Point(0, 0, 0), Point(1200, 0, 0)), 80, 160)
    beam_b = Beam.from_centerline(Line(Point(0, 0, 0), Point(0, 1200, 0)), 80, 160)
    model.add_element(beam_a, parent=panel)
    model.add_element(beam_b, parent=panel)
    return model, panel, beam_a, beam_b


def test_child_layer_follows_transformed_panel(panel_model):
    _, panel, _, _ = panel_model
    layer = panel.layers[0]
    outline_before = layer.outline_a

    panel.transform(T)

    assert TOL.is_allclose(layer.outline_a.points[1], outline_before.points[1].transformed(T))


def test_transformed_panel_survives_serialization(panel_model):
    model, panel, beam_a, _ = panel_model
    panel.transform(T)
    expected_outline = panel.outline_a
    expected_beam_frame = beam_a.frame

    model_copy = json_loads(json_dumps(model))
    panel_copy = model_copy.panels[0]
    beam_copy = next(e for e in panel_copy.children if isinstance(e, Beam) and TOL.is_allclose(e.frame.point, beam_a.frame.point))

    assert TOL.is_allclose(panel_copy.outline_a.points[1], expected_outline.points[1])
    assert_same_frame(beam_copy.frame, expected_beam_frame)


def test_transformed_hierarchy_survives_serialization():
    """Every element of a moved panel tree loads back where it was: layers, sublayers, and children with their own placement.

    JSON only: timber_design_arch does not support protobuf yet.
    """
    model = ArchModel()
    outline = Polyline([Point(1000, 0, 0), Point(4000, 0, 0), Point(4000, 2400, 0), Point(1000, 2400, 0), Point(1000, 0, 0)])
    panel = Panel.from_outline_thickness(outline, 200)
    exterior = LayerDefinition("exterior", 50, sublayer_defs=[LayerDefinition("cladding", 20), LayerDefinition("battens")])
    panel.layer_structure = LayerStructure([exterior, LayerDefinition("core"), LayerDefinition("interior", 50)])
    model.add_element(panel)
    panel.merge_layer_structure(model)
    # children placed in the panel's local coordinates, rotated relative to it
    plate = Plate(Frame([300, 400, 200], [0, 1, 0], [-1, 0, 0]), 600, 300, 20)
    nested_panel = Panel(Frame([1500, 200, 200], [1, 1, 0], [-1, 1, 0]), 800, 600, 50)
    beam = Beam.from_centerline(Line(Point(0, 0, 0), Point(1200, 0, 0)), 80, 160)
    for child in (plate, nested_panel, beam):
        model.add_element(child, parent=panel)
    plate.transform(Translation.from_vector([100, 50, 0]))  # moved on its own, then with its parent
    panel.transform(T)

    def placement(element):
        outline = list(element.outline_a.points) if hasattr(element, "outline_a") else []
        return [element.frame.point, element.frame.xaxis, element.frame.yaxis] + outline

    expected = {str(e.guid): placement(e) for e in model.elements()}
    assert len(expected) == 9  # panel, 5 layers, plate, nested panel, beam

    model_copy = json_loads(json_dumps(model))

    for element in model_copy.elements():
        for actual, wanted in zip(placement(element), expected.pop(str(element.guid))):
            assert TOL.is_allclose(actual, wanted), type(element).__name__
    assert not expected


@pytest.mark.parametrize("transformation", [Scale.from_factors([2, 2, 2]), Reflection.from_frame(Frame.worldYZ())], ids=["scale", "mirror"])
def test_panel_rejects_non_rigid_transformations(transformation):
    panel = Panel(Frame.worldXY(), 100, 100, 10)
    with pytest.raises(ValueError):
        panel.transform(transformation)


def test_model_transform_moves_panel_children(panel_model):
    model, panel, beam_a, beam_b = panel_model
    elements = [panel, beam_a, beam_b, *panel.layers]
    before = [element.frame.point for element in elements]

    model.transform(Translation.from_vector([0, 0, 250]))

    for element, point in zip(elements, before):
        assert TOL.is_allclose(element.frame.point, point + Vector(0, 0, 250))
