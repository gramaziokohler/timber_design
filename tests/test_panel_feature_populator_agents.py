from types import SimpleNamespace

import pytest

from compas.geometry import Frame
from compas.geometry import Plane
from compas.geometry import Point
from compas.geometry import Polyline
from compas.geometry import Vector
from compas_arch.elements import LayerDefinition
from compas_arch.elements import LayerRole
from compas_arch.elements import LayerStructure
from compas_arch.elements import Panel
from compas_arch.model import ArchModel
from compas_arch.panel_features import LinearService
from compas_arch.panel_features import MEPPenetration
from compas_arch.panel_features import Niche
from compas_timber.elements import Plate
from compas_timber.fabrication import FreeContour

from timber_design_populator import LinearServicePopulatorAgent
from timber_design_populator import MEPPenetrationPopulatorAgent
from timber_design_populator import NichePopulatorAgent
from timber_design_populator import stud_panel


def _outline(xmin, ymin, xmax, ymax, z=0.0):
    return Polyline(
        [
            Point(xmin, ymin, z),
            Point(xmax, ymin, z),
            Point(xmax, ymax, z),
            Point(xmin, ymax, z),
            Point(xmin, ymin, z),
        ]
    )


def _fake_layer(role, z_a, z_b):
    """Stand-in for a Layer with a role and two faces parallel to world XY."""
    return SimpleNamespace(role=role, planes=(Plane(Point(0, 0, z_a), Vector(0, 0, 1)), Plane(Point(0, 0, z_b), Vector(0, 0, 1))), normal=Vector(0, 0, 1))


def _panel_with_layers():
    panel = Panel.from_outline_thickness(_outline(0, 0, 4000, 2700), 200)
    panel.layer_structure = LayerStructure(
        layer_defs=[
            LayerDefinition(name="exterior", thickness=20),
            LayerDefinition(name="core"),
            LayerDefinition(name="interior", thickness=20),
        ]
    )
    return panel


def _add_features(panel):
    mep = MEPPenetration(
        Frame.worldXY(),
        _outline(500, 500, 900, 700, 200),
        _outline(500, 500, 800, 700, 100),
        _outline(500, 500, 700, 700, 0),
    )
    niche = Niche(Frame.worldXY(), _outline(2000, 500, 2500, 1200, 0), LayerRole.EXTERIOR, 10)
    service = LinearService(Frame.worldXY(), Polyline([Point(100, 100, 0), Point(500, 200, 0)]), 20)
    for feature in (mep, niche, service):
        panel.add_feature(feature)
    return mep, niche, service


def test_stud_panel_automatically_dispatches_new_features():
    panel = _panel_with_layers()
    mep, niche, service = _add_features(panel)

    model = ArchModel()
    model.add_element(panel)
    panel.merge_layer_structure(model)
    core_path = panel.core_layer.layer_path
    exterior_path = panel.exterior_layer.layer_path
    interior_path = panel.interior_layer.layer_path
    populator = stud_panel(panel, standard_beam_width=60, stud_spacing=0)
    populator.populate_elements()
    agents = {type(agent): agent for agent in populator.agents if getattr(agent, "feature", None) is not None}

    mep_agent = agents[MEPPenetrationPopulatorAgent]
    niche_agent = agents[NichePopulatorAgent]
    service_agent = agents[LinearServicePopulatorAgent]
    assert mep_agent.feature is mep
    assert niche_agent.feature is niche
    assert service_agent.feature is service
    assert mep_agent.element_layer_paths == [core_path]
    assert set(mep_agent.trimming_layer_paths) == {exterior_path, core_path, interior_path}
    assert niche_agent.element_layer_paths == [core_path]
    assert set(niche_agent.trimming_layer_paths) == {exterior_path, interior_path}
    assert service_agent.element_layer_paths == []
    assert service_agent.trimming_layer_paths == [core_path]
    # framed like a window: header, sill and two king studs
    framing = ["header", "king_stud", "king_stud", "sill"]
    assert sorted(e.attributes["category"] for e in mep_agent.elements) == framing
    assert sorted(e.attributes["category"] for e in niche_agent.elements) == framing
    assert service_agent.elements == []
    exterior_plate = next(plate for plate in populator.model.find_all_elements_of_type(Plate) if plate.parent.name == "exterior")
    niche_depths = [feature.contour_param_object.depth for feature in exterior_plate._features if isinstance(feature, FreeContour)]
    assert sorted(niche_depths) == [10, 20]
    widths = {
        layer_name: max(point.x for point in mep_agent.compute_outline_for_layer(populator.layer_tree[layer_path]).points)
        - min(point.x for point in mep_agent.compute_outline_for_layer(populator.layer_tree[layer_path]).points)
        for layer_name, layer_path in (("exterior", exterior_path), ("core", core_path), ("interior", interior_path))
    }
    assert widths == {"exterior": 200, "core": 300, "interior": 400}


def test_mep_agent_uses_layer_specific_outline_for_trim(monkeypatch):
    feature = MEPPenetration(
        Frame.worldXY(),
        _outline(0, 0, 10, 10, 0),
        _outline(0, 0, 20, 20, 20),
        _outline(0, 0, 30, 30, 40),
    )
    agent = MEPPenetrationPopulatorAgent(feature=feature)
    added = []
    calls = []

    def fake_free_contour(outline, plate, **kwargs):
        calls.append((outline, plate, kwargs))
        return "free-contour"

    monkeypatch.setattr(FreeContour, "from_polyline_and_element", fake_free_contour)
    layer = _fake_layer(LayerRole.EXTERIOR, 40, 60)
    plate = SimpleNamespace(parent=layer, thickness=20, add_feature=added.append)

    agent.trim_plate(plate)

    ((outline, called_plate, kwargs),) = calls
    assert outline.points == feature.outline_exterior.points
    assert (called_plate, kwargs) == (plate, {"depth": 20, "interior": True})
    assert added == ["free-contour"]


def test_mep_agent_projects_outline_onto_sublayer_plate_face(monkeypatch):
    feature = MEPPenetration(Frame.worldXY(), _outline(0, 0, 10, 10, 0), _outline(0, 0, 20, 20, 20), _outline(0, 0, 30, 30, 40))
    agent = MEPPenetrationPopulatorAgent(feature=feature)
    calls = []
    monkeypatch.setattr(FreeContour, "from_polyline_and_element", lambda outline, plate, **kwargs: calls.append(outline))
    # an inner sublayer of a subdivided exterior layer: same role, different faces
    plate = SimpleNamespace(parent=_fake_layer(LayerRole.EXTERIOR, 45, 50), thickness=5, add_feature=lambda f: None)

    agent.trim_plate(plate)

    assert [point.z for point in calls[0].points] == [45] * 5
    assert [(point.x, point.y) for point in calls[0].points] == [(point.x, point.y) for point in feature.outline_exterior.points]


def test_mep_agent_ignores_layers_without_a_role(monkeypatch):
    feature = MEPPenetration(Frame.worldXY(), _outline(0, 0, 10, 10, 0), _outline(0, 0, 20, 20, 20), _outline(0, 0, 30, 30, 40))
    agent = MEPPenetrationPopulatorAgent(feature=feature)
    calls = []
    monkeypatch.setattr(FreeContour, "from_polyline_and_element", lambda *args, **kwargs: calls.append(args))

    agent.trim_plate(SimpleNamespace(parent=_fake_layer(None, 0, 10), thickness=10, add_feature=lambda f: None))

    assert calls == []


def test_niche_agent_trims_only_selected_surface_with_blind_depth(monkeypatch):
    feature = Niche(Frame.worldXY(), _outline(0, 0, 10, 10), LayerRole.INTERIOR, 8)
    agent = NichePopulatorAgent(feature=feature)
    calls = []
    added = []

    def fake_free_contour(outline, plate, **kwargs):
        calls.append((outline, plate, kwargs))
        return "free-contour"

    monkeypatch.setattr(FreeContour, "from_polyline_and_element", fake_free_contour)
    interior_plate = SimpleNamespace(parent=_fake_layer(LayerRole.INTERIOR, 0, 20), add_feature=added.append)
    exterior_plate = SimpleNamespace(parent=_fake_layer(LayerRole.EXTERIOR, 180, 200), add_feature=added.append)
    # inner sublayer of the interior layer: right role, but the outline is not on its faces
    inner_interior_plate = SimpleNamespace(parent=_fake_layer(LayerRole.INTERIOR, 20, 40), add_feature=added.append)

    agent.trim_plate(exterior_plate)
    agent.trim_plate(inner_interior_plate)
    agent.trim_plate(interior_plate)

    assert calls == [(feature.outline, interior_plate, {"depth": 8, "interior": True})]
    assert added == ["free-contour"]


def test_linear_service_agent_does_not_modify_framing():
    agent = LinearServicePopulatorAgent()

    assert agent.generate_elements_for_layer(object()) == ([], None)


def test_service_only_machines_beams_it_runs_through():
    from compas.geometry import Line
    from compas_timber.elements import Beam

    from timber_design_populator.populator_agents.panel_feature_populator_agents import _crossings

    service = Polyline([Point(0, 500, 150), Point(1000, 500, 150)])  # on the core mid-plane, z=150
    # vertical members in the panel plane at x=500, with z_vector along the panel normal
    core_stud = Beam.from_centerline(Line(Point(500, 0, 150), Point(500, 2000, 150)), width=60, height=160, z_vector=Vector(0, 0, 1))
    batten = Beam.from_centerline(Line(Point(500, 0, 35), Point(500, 2000, 35)), width=30, height=30, z_vector=Vector(0, 0, 1))

    ((point, direction),) = _crossings(service, core_stud)
    assert (round(point.x), round(point.y), round(point.z)) == (500, 500, 150)
    assert _crossings(service, batten) == []  # the batten spans z=20..50


def test_service_cut_does_not_recurse_while_being_built():
    from compas.geometry import Line
    from compas_timber.elements import Beam

    from timber_design_populator.populator_agents.panel_feature_populator_agents import _ServiceDrillingProxy

    beam = Beam.from_centerline(Line(Point(0, 0, 0), Point(0, 1000, 0)), width=60, height=160)
    proxy = _ServiceDrillingProxy(Line(Point(-100, 500, 0), Point(100, 500, 0)), beam, 20)

    # while the drilling is being built, a nested request for the beam geometry skips this cut
    proxy._building = True
    geometry = object()
    assert proxy.apply(geometry, beam) is geometry

    # an instance without __init__ (as when copying) does not forward its own private attributes
    bare = _ServiceDrillingProxy.__new__(_ServiceDrillingProxy)
    with pytest.raises(AttributeError):
        bare._processing
