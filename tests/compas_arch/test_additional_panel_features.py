import pytest

from compas.data import json_dumps
from compas.data import json_loads
from compas.geometry import Frame
from compas.geometry import Point
from compas.geometry import Polyline
from compas.geometry import Vector
from compas.tolerance import TOL

from compas_arch.panel_features import LinearService
from compas_arch.panel_features import MEPPenetration
from compas_arch.panel_features import Niche
from compas_arch.elements import LayerRole
from compas_arch.panel_features import PanelFeatureType


@pytest.fixture
def outline():
    return Polyline([Point(0, 0, 0), Point(1, 0, 0), Point(1, 1, 0), Point(0, 1, 0), Point(0, 0, 0)])


def test_mep_penetration_stores_three_local_outlines(outline):
    feature = MEPPenetration(Frame.worldXY(), outline, outline, outline)

    assert feature.__data__["outline_interior"] is outline
    assert feature.__data__["outline_core"] is outline
    assert feature.__data__["outline_exterior"] is outline
    assert len(feature.geometry) == 3
    assert feature.panel_feature_type == PanelFeatureType.OPENING


def test_mep_penetration_requires_closed_outlines(outline):
    open_outline = Polyline([Point(0, 0, 0), Point(1, 0, 0), Point(1, 1, 0)])

    with pytest.raises(ValueError, match="core MEP outline"):
        MEPPenetration(Frame.worldXY(), outline, open_outline, outline)


def test_mep_penetration_outlines_follow_frame_transform(outline):
    frame = Frame(Point(0, 0, 2), Vector(1, 0, 0), Vector(0, 1, 0))
    feature = MEPPenetration(frame, outline, outline, outline)

    assert all(TOL.is_close(polyline[0].z, 2) for polyline in feature.geometry)


def test_new_features_round_trip_through_compas_json(outline):
    features = [
        MEPPenetration(Frame.worldXY(), outline, outline, outline),
        LinearService(Frame.worldXY(), outline, 12),
        Niche(Frame.worldXY(), outline, LayerRole.INTERIOR, 30),
    ]

    for feature in features:
        restored = json_loads(json_dumps(feature))
        assert type(restored) is type(feature)
        assert restored.__data__ == feature.__data__


def test_linear_service_stores_its_path_and_diameter(outline):
    feature = LinearService(Frame.worldXY(), outline, 12)

    assert feature.geometry == outline
    assert feature.thickness == 12
    assert not hasattr(feature, "routing_mode")  # drilling or notching is a detail set's choice
    assert feature.__data__["polyline"] is outline
    assert feature.panel_feature_type == PanelFeatureType.LINEAR


def test_linear_service_rejects_nonpositive_thickness(outline):
    with pytest.raises(ValueError, match="thickness"):
        LinearService(Frame.worldXY(), outline, 0)


def test_niche_stores_outline_side_and_depth(outline):
    feature = Niche(Frame.worldXY(), outline, LayerRole.INTERIOR, 30)

    assert feature.geometry == outline
    assert feature.side == LayerRole.INTERIOR
    assert feature.depth == 30
    assert feature.__data__["outline"] is outline
    assert feature.__data__["side"] == LayerRole.INTERIOR
    assert feature.__data__["depth"] == 30
    assert feature.panel_feature_type == PanelFeatureType.RECESS


def test_niche_rejects_nonpositive_depth(outline):
    with pytest.raises(ValueError, match="depth"):
        Niche(Frame.worldXY(), outline, LayerRole.EXTERIOR, 0)


def test_niche_requires_closed_outline():
    open_outline = Polyline([Point(0, 0, 0), Point(1, 0, 0), Point(1, 1, 0)])

    with pytest.raises(ValueError, match="closed"):
        Niche(Frame.worldXY(), open_outline, LayerRole.INTERIOR, 10)
