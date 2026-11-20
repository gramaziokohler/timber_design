import pytest
from compas.data import json_dumps
from compas.data import json_loads
from compas.geometry import Point
from compas.geometry import Polyline
from compas_arch.elements import LayerDefinition
from compas_arch.elements import LayerRole
from compas_arch.elements import LayerStructure
from compas_arch.elements import Panel
from compas_arch.model import ArchModel
from compas_arch.panel_features import LinearService
from compas_arch.panel_features import LinearServiceMode
from compas_arch.panel_features import MEPPenetration
from compas_arch.panel_features import Niche
from compas_arch.panel_features import Opening
from compas_arch.panel_features import OpeningType
from compas_timber.elements import Beam
from compas_timber.elements import Plate
from compas_timber.fabrication import Drilling
from compas_timber.fabrication import FreeContour
from compas_timber.fabrication import Lap

from timber_design_gh.panel_feature_helpers import LinearServiceDefinition
from timber_design_gh.panel_feature_helpers import MEPPenetrationDefinition
from timber_design_gh.panel_feature_helpers import NicheDefinition
from timber_design_gh.panel_feature_helpers import OpeningDefinition
from timber_design_gh.panel_feature_helpers import add_feature_definitions
from timber_design_gh.panel_feature_helpers import layer_mid_z
from timber_design_gh.panel_feature_helpers import layer_outer_face_z
from timber_design_populator import stud_panel


def _rect(*points):
    return Polyline(list(points) + [points[0]])


def _world_rect(xmin, xmax, zmin, zmax, y=500):
    """A rectangle in the world XZ plane at *y*: drawn on the wall built by :func:`_wall`."""
    return _rect(Point(xmin, y, zmin), Point(xmax, y, zmin), Point(xmax, y, zmax), Point(xmin, y, zmax))


def _wall(layered=True):
    """A vertical wall in the world XZ plane at y=500, so panel-local and world coordinates differ."""
    panel = Panel.from_outline_thickness(_world_rect(1000, 5000, 0, 2700), 200)
    if layered:
        panel.layer_structure = LayerStructure(
            layer_defs=[
                LayerDefinition(name="cladding", thickness=20, role=LayerRole.EXTERIOR),
                LayerDefinition(name="studs", role=LayerRole.CORE),
                LayerDefinition(name="osb", thickness=20, role=LayerRole.INTERIOR),
            ]
        )
    return panel


def _local_zs(polyline):
    return sorted({round(point.z, 6) for point in polyline.points})


def test_layer_face_heights():
    panel = _wall()
    assert layer_outer_face_z(panel.exterior_layer) == 0.0
    assert layer_outer_face_z(panel.interior_layer) == 200.0
    assert layer_mid_z(panel.core_layer) == 100.0
    assert layer_outer_face_z(None, default=7.0) == 7.0


def test_definitions_place_outlines_on_their_layer_faces():
    panel = _wall()
    mep = MEPPenetrationDefinition(_world_rect(2000, 2400, 1000, 1300)).feature_for_panel(panel)
    niche = NicheDefinition(_world_rect(3000, 3400, 500, 900), "interior", 10).feature_for_panel(panel)
    service = LinearServiceDefinition(Polyline([Point(1500, 500, 100), Point(1500, 500, 2000)]), 20).feature_for_panel(panel)

    assert isinstance(mep, MEPPenetration)
    assert (_local_zs(mep._outline_interior), _local_zs(mep._outline_core), _local_zs(mep._outline_exterior)) == ([200.0], [100.0], [0.0])
    assert isinstance(niche, Niche) and niche.side == LayerRole.INTERIOR
    assert _local_zs(niche._outline) == [200.0]
    assert isinstance(service, LinearService) and service.routing_mode == LinearServiceMode.CORE_DRILLING
    assert _local_zs(service._polyline) == [100.0]


def test_feature_geometry_maps_back_to_world():
    panel = _wall()
    world = _world_rect(2000, 2400, 1000, 1300)
    niche = NicheDefinition(world, LayerRole.EXTERIOR, 10).feature_for_panel(panel)
    back = niche.outline.transformed(panel.modeltransformation)
    for a, b in zip(world.points, back.points):
        assert a.distance_to_point(b) < 1e-6


def test_opening_definition_keeps_its_outline_unchanged():
    panel = _wall()
    outline = _world_rect(2000, 2800, 0, 2100)
    before = [tuple(p) for p in outline.points]
    opening = OpeningDefinition(outline, OpeningType.DOOR).feature_for_panel(panel)

    assert isinstance(opening, Opening) and opening.opening_type == OpeningType.DOOR
    assert [tuple(p) for p in outline.points] == before


def test_definitions_validate_inputs():
    open_outline = Polyline([Point(0, 0, 0), Point(1, 0, 0), Point(1, 1, 0)])
    with pytest.raises(ValueError, match="closed"):
        OpeningDefinition(open_outline)
    with pytest.raises(ValueError, match="closed"):
        MEPPenetrationDefinition(_world_rect(0, 1, 0, 1), outline_exterior=open_outline)
    with pytest.raises(ValueError, match="side"):
        NicheDefinition(_world_rect(0, 1, 0, 1), LayerRole.CORE, 5)
    with pytest.raises(ValueError, match="depth"):
        NicheDefinition(_world_rect(0, 1, 0, 1), LayerRole.EXTERIOR, 0)
    with pytest.raises(ValueError, match="thickness"):
        LinearServiceDefinition(Polyline([Point(0, 0, 0), Point(1, 0, 0)]), 0)


def test_definitions_off_the_panel_are_skipped():
    panel = _wall()
    on_panel = NicheDefinition(_world_rect(2000, 2400, 1000, 1300), LayerRole.EXTERIOR, 10)
    beside_panel = NicheDefinition(_world_rect(6000, 6400, 1000, 1300), LayerRole.EXTERIOR, 10)
    # inside the outline when seen along the panel normal, but on a wall 3 m away
    parallel_wall = NicheDefinition(_world_rect(2000, 2400, 1000, 1300, y=3500), LayerRole.EXTERIOR, 10)
    # a door touching the panel edge still belongs to it
    door = OpeningDefinition(_world_rect(3000, 3800, 0, 2100), OpeningType.DOOR)

    added, skipped, messages = add_feature_definitions(panel, [on_panel, beside_panel, parallel_wall, door, None])

    assert [type(f) for f in added] == [Niche, Opening]
    assert skipped == 2
    assert messages == []
    assert panel.features == added


def test_add_feature_definitions_reports_problems():
    panel = _wall(layered=False)

    added, skipped, messages = add_feature_definitions(panel, [NicheDefinition(_world_rect(2000, 2400, 1000, 1300), LayerRole.EXTERIOR, 10), "not a definition"])

    assert len(added) == 1
    assert any("no exterior layer" in m for m in messages)
    assert any("Not a panel feature definition" in m for m in messages)


def test_features_from_definitions_are_framed_and_trimmed_on_rotated_wall():
    panel = _wall()
    definitions = [
        MEPPenetrationDefinition(_world_rect(2000, 2400, 1000, 1300)),
        NicheDefinition(_world_rect(3500, 4200, 500, 1500), LayerRole.EXTERIOR, 10),
    ]
    add_feature_definitions(panel, definitions)

    model = ArchModel()
    model.add_element(panel)
    panel.merge_layer_structure(model)
    populator = stud_panel(panel, standard_beam_width=60, stud_spacing=0)
    populator.populate_elements()
    populator.join_elements()
    populator.process_joinery()
    populator.merge_with_model(model)

    assert not populator.debug_info.joint_errors
    assert not populator.debug_info.feature_errors

    # the king studs flank each feature in world space
    king_xs = sorted(round(b.centerline.start.x) for b in model.find_all_elements_of_type(Beam) if b.attributes.get("category") == "king_stud")
    assert king_xs == [1970, 2430, 3470, 4230]

    contours = {plate.parent.name: sum(isinstance(f, FreeContour) for f in plate.features) for plate in model.find_all_elements_of_type(Plate)}
    # cladding (exterior): outer contour + MEP + niche; osb (interior): outer contour + MEP
    assert contours == {"cladding": 3, "osb": 2}


def _populate_with_niche(depth):
    panel = _wall()
    add_feature_definitions(panel, [NicheDefinition(_world_rect(3500, 4200, 500, 1500), LayerRole.EXTERIOR, depth)])
    model = ArchModel()
    model.add_element(panel)
    panel.merge_layer_structure(model)
    populator = stud_panel(panel, standard_beam_width=60, stud_spacing=400)
    populator.populate_elements()
    populator.join_elements()
    populator.process_joinery()
    populator.merge_with_model(model)
    assert not populator.debug_info.joint_errors
    assert not populator.debug_info.feature_errors
    # vertical extents of the studs that lie within the niche's width
    studs = [b for b in model.find_all_elements_of_type(Beam) if b.attributes.get("category") == "stud" and 3500 < b.centerline.start.x < 4200]
    stud_spans = sorted(tuple(sorted((round(b.centerline.start.z), round(b.centerline.end.z)))) for b in studs)
    depths = {}
    for plate in model.find_all_elements_of_type(Plate):
        depths[plate.parent.name] = sorted(round(f.contour_param_object.depth, 3) for f in plate.features if isinstance(f, FreeContour))
    return stud_spans, depths


def test_niche_with_depth_is_a_blind_pocket_in_the_side_sheathing():
    stud_spans, depths = _populate_with_niche(10)

    assert stud_spans == [(60, 2640)]  # the stud behind the niche runs through
    assert depths == {"cladding": [10, 20], "osb": [20]}  # outer contour + 10 deep pocket


def test_niche_without_depth_goes_through_the_framing_layer():
    stud_spans, depths = _populate_with_niche(None)

    assert stud_spans == [(60, 500), (1500, 2640)]  # the stud is cut at the niche
    assert depths == {"cladding": [20, 20], "osb": [20]}  # cladding cut through, osb left as the back


# ------------------------------------------------------------------
# Linear services: drilling and notching the framing
# ------------------------------------------------------------------


def _populate_with_service(diameter, mode, interior_first=False):
    panel = _wall()
    if interior_first:
        panel.layer_structure = LayerStructure(
            layer_defs=[
                LayerDefinition(name="osb", thickness=20, role=LayerRole.INTERIOR),
                LayerDefinition(name="studs", role=LayerRole.CORE),
                LayerDefinition(name="cladding", thickness=20, role=LayerRole.EXTERIOR),
            ]
        )
    # a horizontal run at z=1000 crossing the studs at x=1800, 2200, 2600 and 3000
    add_feature_definitions(panel, [LinearServiceDefinition(Polyline([Point(1500, 500, 1000), Point(3000, 500, 1000)]), diameter, mode)])
    model = ArchModel()
    model.add_element(panel)
    panel.merge_layer_structure(model)
    populator = stud_panel(panel, standard_beam_width=60, stud_spacing=400)
    populator.populate_elements()
    populator.join_elements()
    populator.process_joinery()
    populator.merge_with_model(model)
    assert not populator.debug_info.joint_errors
    machined = {}
    for beam in model.find_all_elements_of_type(Beam):
        cuts = [f.unproxified() for f in beam.features if hasattr(f, "unproxified")]
        cuts = [c for c in cuts if isinstance(c, (Drilling, Lap))]
        if cuts:
            machined[round(beam.centerline.start.x)] = (beam, cuts)
    return model, machined, [e.message for e in populator.debug_info.feature_errors]


def test_core_drilling_drills_through_every_crossed_stud():
    model, machined, warnings = _populate_with_service(30, LinearServiceMode.CORE_DRILLING)

    assert sorted(machined) == [1800, 2200, 2600, 3000]
    for beam, cuts in machined.values():
        (drilling,) = cuts
        assert isinstance(drilling, Drilling)
        assert not drilling.is_joinery
        assert not drilling.depth_limited  # through the stud
        assert drilling.diameter == 30
        assert drilling.start_y == pytest.approx(beam.height / 2)  # on the core mid-plane
        assert drilling.start_x == pytest.approx(1000 - beam.centerline.start.z)  # at the service height
    assert warnings == []
    # the drillings survive copying the model
    copy = json_loads(json_dumps(model))
    assert sum(isinstance(f, Drilling) for b in copy.find_all_elements_of_type(Beam) for f in b.features) == 4


def test_frame_notching_cuts_a_lap_into_the_interior_face():
    _, machined, warnings = _populate_with_service(30, LinearServiceMode.FRAME_NOTCHING)

    assert sorted(machined) == [1800, 2200, 2600, 3000]
    for beam, cuts in machined.values():
        (lap,) = cuts
        assert isinstance(lap, Lap)
        assert not lap.is_joinery
        volume = lap.volume_from_params_and_beam(beam)
        ys = [p[1] for p in volume.vertices]
        zs = [p[2] for p in volume.vertices]
        # the studs span y=520..680 and the interior (osb) is on the +y side
        assert (min(ys), max(ys)) == pytest.approx((650, 680), abs=0.01)
        assert (min(zs), max(zs)) == pytest.approx((985, 1015), abs=0.01)
    assert warnings == []


def test_frame_notching_follows_the_interior_layer():
    _, machined, _ = _populate_with_service(30, LinearServiceMode.FRAME_NOTCHING, interior_first=True)

    for beam, (lap,) in machined.values():
        ys = [p[1] for p in lap.volume_from_params_and_beam(beam).vertices]
        assert (min(ys), max(ys)) == pytest.approx((520, 550), abs=0.01)  # interior now on the -y side


@pytest.mark.parametrize(
    "diameter, mode, expected",
    [
        (70, LinearServiceMode.CORE_DRILLING, "hole is more than 40%"),
        (50, LinearServiceMode.FRAME_NOTCHING, "notch is more than 25%"),
    ],
)
def test_oversized_service_cuts_are_reported(diameter, mode, expected):
    _, machined, warnings = _populate_with_service(diameter, mode)

    assert len(machined) == 4  # still cut
    assert len(warnings) == 4
    assert all(expected in w for w in warnings)
