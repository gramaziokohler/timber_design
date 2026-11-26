from types import SimpleNamespace

import pytest

from compas.geometry import Frame
from compas.geometry import Plane
from compas.geometry import Point
from compas.geometry import Polyline
from compas.geometry import Vector
from timber_design_arch.elements import LayerDefinition
from timber_design_arch.elements import LayerRole
from timber_design_arch.elements import LayerStructure
from timber_design_arch.elements import Panel
from timber_design_arch.model import ArchModel
from timber_design_arch.panel_features import LinearService
from timber_design_arch.panel_features import MEPPenetration
from timber_design_arch.panel_features import Niche
from compas_timber.elements import Plate
from compas_timber.fabrication import FreeContour

from timber_design_populator import LayerCutDetailAgent
from timber_design_populator import ServiceDrillingDetailAgent
from timber_design_populator import VoidFramingDetailAgent
from timber_design_populator import stud_panel
from timber_design_populator.detail_sets import FramedPenetrationDetailSet


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


def _agents_by_feature(populator):
    agents = {}
    for agent in populator.agents:
        feature = getattr(agent, "feature", None)
        if feature is not None:
            agents.setdefault(id(feature), []).append(agent)
    return agents


def test_stud_panel_builds_new_features_with_their_detail_sets():
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
    agents = _agents_by_feature(populator)

    mep_framing, *mep_cuts = agents[id(mep)]
    niche_framing, niche_cut = agents[id(niche)]
    (service_agent,) = agents[id(service)]
    assert type(mep_framing) is VoidFramingDetailAgent and all(type(c) is LayerCutDetailAgent for c in mep_cuts)
    assert (type(niche_framing), type(niche_cut)) == (VoidFramingDetailAgent, LayerCutDetailAgent)
    assert type(service_agent) is ServiceDrillingDetailAgent
    assert mep_framing.element_layer_paths == [core_path]
    mep_cut = {c.trimming_layer_paths[0]: c for c in mep_cuts}  # one cut agent per role layer
    assert sorted(mep_cut) == sorted([exterior_path, core_path, interior_path])
    assert niche_framing.element_layer_paths == [core_path]
    assert niche_cut.trimming_layer_paths == [exterior_path]  # only the niche's side
    assert service_agent.element_layer_paths == []
    assert service_agent.trimming_layer_paths == [core_path]
    # framed like a window: header, sill and two king studs
    framing = ["header", "king_stud", "king_stud", "sill"]
    assert sorted(e.attributes["category"] for e in mep_framing.elements) == framing
    assert sorted(e.attributes["category"] for e in niche_framing.elements) == framing
    assert service_agent.elements == []
    exterior_plate = next(plate for plate in populator.model.find_all_elements_of_type(Plate) if plate.parent.name == "exterior")
    niche_depths = [feature.contour_param_object.depth for feature in exterior_plate._features if isinstance(feature, FreeContour)]
    assert sorted(niche_depths) == [10, 20]  # the niche's blind pocket, and the MEP cut through the 20 thick plate

    def width(outline):
        xs = [point.x for point in outline.points]
        return max(xs) - min(xs)

    widths = {
        "exterior": width(mep_cut[exterior_path].outline_for_layer(populator.layer_tree[exterior_path])),
        "core": width(mep_framing.boundary),
        "interior": width(mep_cut[interior_path].outline_for_layer(populator.layer_tree[interior_path])),
    }
    assert widths == {"exterior": 200, "core": 300, "interior": 400}


def test_mep_detail_set_uses_the_outline_of_each_layer_role():
    feature = MEPPenetration(Frame.worldXY(), _outline(0, 0, 10, 10, 0), _outline(0, 0, 20, 20, 20), _outline(0, 0, 30, 30, 40))
    assert FramedPenetrationDetailSet.outline_for_role(feature, LayerRole.INTERIOR).points == feature.outline_interior.points
    assert FramedPenetrationDetailSet.outline_for_role(feature, LayerRole.CORE).points == feature.outline_core.points
    assert FramedPenetrationDetailSet.outline_for_role(feature, LayerRole.EXTERIOR).points == feature.outline_exterior.points


def test_a_through_cut_cuts_the_plate_through(monkeypatch):
    outline = _outline(0, 0, 30, 30, 40)
    added = []
    calls = []

    def fake_free_contour(outline, plate, **kwargs):
        calls.append((outline, plate, kwargs))
        return "free-contour"

    monkeypatch.setattr(FreeContour, "from_polyline_and_element", fake_free_contour)
    layer = _fake_layer(LayerRole.EXTERIOR, 40, 60)
    plate = SimpleNamespace(parent=layer, thickness=20, add_feature=added.append)

    LayerCutDetailAgent((0,), outline_a=outline).trim_plate(plate)

    ((called_outline, called_plate, kwargs),) = calls
    assert called_outline.points == outline.points
    assert (called_plate, kwargs) == (plate, {"depth": 20, "interior": True})
    assert added == ["free-contour"]


def test_a_through_cut_projects_its_outline_onto_a_sublayer_plate_face(monkeypatch):
    outline = _outline(0, 0, 30, 30, 40)
    calls = []
    monkeypatch.setattr(FreeContour, "from_polyline_and_element", lambda outline, plate, **kwargs: calls.append(outline))
    # an inner sublayer of a subdivided exterior layer: same role, different faces
    plate = SimpleNamespace(parent=_fake_layer(LayerRole.EXTERIOR, 45, 50), thickness=5, add_feature=lambda f: None)

    LayerCutDetailAgent((0,), outline_a=outline).trim_plate(plate)

    assert [point.z for point in calls[0].points] == [45] * 5
    assert [(point.x, point.y) for point in calls[0].points] == [(point.x, point.y) for point in outline.points]


def test_a_cut_agent_trims_its_layer_and_creates_nothing():
    agent = LayerCutDetailAgent((0,), outline_a=_outline(0, 0, 10, 10, 0))
    assert agent.trimming_layer_paths == [(0,)] and agent.element_layer_paths == []
    clone = agent.clone()
    assert clone.trimming_layer_paths == [(0,)] and clone.element_layer_paths == [] and clone.outline_a.points == agent.outline_a.points


def test_a_cut_that_leaves_beams_alone_has_no_boundary():
    layer = _fake_layer(LayerRole.CORE, 0, 10)
    assert LayerCutDetailAgent((0,), outline_a=_outline(0, 0, 10, 10, 0), cut_beams=False).compute_outline_for_layer(layer) is None


def test_a_blind_cut_only_cuts_the_plate_whose_face_holds_the_outline(monkeypatch):
    outline = _outline(0, 0, 10, 10)
    cut = LayerCutDetailAgent((2,), outline_a=outline, depth=8)
    calls = []
    added = []

    def fake_free_contour(outline, plate, **kwargs):
        calls.append((outline, plate, kwargs))
        return "free-contour"

    monkeypatch.setattr(FreeContour, "from_polyline_and_element", fake_free_contour)
    face_plate = SimpleNamespace(parent=_fake_layer(LayerRole.INTERIOR, 0, 20), add_feature=added.append)
    # an inner sublayer: the outline is not on its faces
    inner_plate = SimpleNamespace(parent=_fake_layer(LayerRole.INTERIOR, 20, 40), add_feature=added.append)

    cut.trim_plate(inner_plate)
    cut.trim_plate(face_plate)

    assert calls == [(outline, face_plate, {"depth": 8, "interior": True})]
    assert added == ["free-contour"]


def test_service_agents_do_not_modify_framing():
    agent = ServiceDrillingDetailAgent(path=Polyline([Point(0, 0, 0), Point(1, 0, 0)]), diameter=20)

    assert agent.generate_elements_for_layer(object()) == ([], None)


def test_service_only_machines_beams_it_runs_through():
    from compas.geometry import Line
    from compas_timber.elements import Beam

    from timber_design_populator.populator_agents.service_geometry import crossings

    service = Polyline([Point(0, 500, 150), Point(1000, 500, 150)])  # on the core mid-plane, z=150
    # vertical members in the panel plane at x=500, with z_vector along the panel normal
    core_stud = Beam.from_centerline(Line(Point(500, 0, 150), Point(500, 2000, 150)), width=60, height=160, z_vector=Vector(0, 0, 1))
    batten = Beam.from_centerline(Line(Point(500, 0, 35), Point(500, 2000, 35)), width=30, height=30, z_vector=Vector(0, 0, 1))

    ((point, direction),) = crossings(service, core_stud)
    assert (round(point.x), round(point.y), round(point.z)) == (500, 500, 150)
    assert crossings(service, batten) == []  # the batten spans z=20..50


def test_service_cut_does_not_recurse_while_being_built():
    from compas.geometry import Line
    from compas_timber.elements import Beam

    from timber_design_populator.populator_agents.service_geometry import _ServiceDrillingProxy

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
