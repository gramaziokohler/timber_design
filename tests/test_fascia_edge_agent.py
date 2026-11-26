"""Tests for FasciaEdgeAgent: angled fascia beams on sloped panel edges, and the Beam2D footprint they rely on."""

import math

import pytest

from compas.data import json_dumps
from compas.data import json_loads
from compas.geometry import Line
from compas.geometry import Point
from compas.geometry import Polyline
from compas.geometry import Vector
from compas.geometry import dot_vectors
from compas_timber.elements import Beam

from timber_design_arch.elements import Panel
from timber_design_arch.model import ArchModel

from timber_design_populator import EdgeAgent
from timber_design_populator import FasciaEdgeAgent
from timber_design_populator import PanelPopulator
from timber_design_populator import PanelType
from timber_design_populator import StudAgent
from timber_design_populator.connections_2d import Beam2D
from timber_design_populator.connections_2d import FasciaBeam

THICKNESS = 200.0
RISE = 100.0  # the top edge of the b face is this much higher: the top edge plane tilts by atan(RISE / THICKNESS)
TILT = math.atan2(RISE, THICKNESS)
WIDTH = 60.0
MILL_DEPTH = 10.0  # the studs' housing in the plates (StudAgent's stud-plate rules)


def _outline(xmin, ymin, xmax, ymax, z):
    return Polyline([Point(xmin, ymin, z), Point(xmax, ymin, z), Point(xmax, ymax, z), Point(xmin, ymax, z), Point(xmin, ymin, z)])


def _panel(rise=RISE):
    """A 4000 x 2700 wall; with *rise*, its top edge is sloped (the b face's top edge is *rise* higher)."""
    a = _outline(0, 0, 4000, 2700, 0)
    b = Polyline([Point(0, 0, THICKNESS), Point(4000, 0, THICKNESS), Point(4000, 2700 + rise, THICKNESS), Point(0, 2700 + rise, THICKNESS), Point(0, 0, THICKNESS)])
    return Panel.from_outlines(a, b)


def _populate(edge_agent_type=FasciaEdgeAgent, rise=RISE, merge=False, **kwargs):
    panel = _panel(rise)
    model = ArchModel()
    model.add_element(panel)
    panel.merge_layer_structure(model)
    agents = [edge_agent_type(panel.core_layer, **kwargs), StudAgent(panel.core_layer, stud_spacing=600)]
    pop = PanelPopulator(panel, PanelType("test", panel.layer_structure, agents=agents, standard_beam_width=WIDTH))
    pop.populate_elements()
    pop.join_elements()
    pop.process_joinery()
    if merge:
        pop.merge_with_model(model)
        return pop, model
    return pop, pop.model


def _beams(model, category=None):
    beams = [e for e in model.elements() if isinstance(e, Beam)]
    return [b for b in beams if category is None or b.attributes.get("category") == category]


def _fascia(model):
    (fascia,) = [b for b in _beams(model) if isinstance(b, FasciaBeam)]
    return fascia


# =============================================================================
# the footprint
# =============================================================================


def test_a_flat_beam_footprint_is_its_frame_and_width():
    beam = Beam2D.from_centerline(Line(Point(0, 0, 0), Point(1000, 0, 0)), width=60, height=200, z_vector=Vector(0, 0, 1))
    assert beam.footprint_frame == beam.frame
    assert beam.footprint_width == 60


def test_a_tilted_beam_footprint_is_its_level_section():
    tilted_up = Vector(0, math.sin(TILT), math.cos(TILT))
    beam = FasciaBeam.from_centerline(Line(Point(0, 0, 0), Point(1000, 0, 0)), width=60, height=300, z_vector=tilted_up)
    frame = beam.footprint_frame
    assert abs(frame.yaxis[2]) < 1e-9 and abs(dot_vectors(frame.yaxis, frame.xaxis)) < 1e-9  # level, across the beam
    assert beam.footprint_width == pytest.approx(60 / math.cos(TILT))
    assert beam.contains_point(Point(500, 60 / math.cos(TILT) / 2 - 0.1, 0)) and not beam.contains_point(Point(500, 60 / math.cos(TILT) / 2 + 0.1, 0))


def test_a_split_fascia_stays_a_fascia():
    beam = FasciaBeam.from_centerline(Line(Point(0, 0, 0), Point(1000, 0, 0)), width=60, height=300, z_vector=Vector(0, math.sin(TILT), math.cos(TILT)))
    segment = beam.get_beam_segment(100, 400)
    assert type(segment) is FasciaBeam and segment.length == pytest.approx(300)
    assert segment.footprint_width == pytest.approx(beam.footprint_width)


# =============================================================================
# the fascia
# =============================================================================


def test_only_the_sloped_edge_gets_a_fascia():
    pop, model = _populate()
    assert pop.debug_info.joint_errors == [] and pop.debug_info.feature_errors == []
    fascia = _fascia(model)
    assert fascia.attributes["category"] == "top_plate_beam"
    others = [b for b in _beams(model) if b.attributes.get("category") in ("bottom_plate_beam", "edge_stud")]
    assert len(others) == 3 and all(type(b) is Beam2D for b in others)


def test_the_fascia_is_tilted_onto_the_edge_plane_and_higher_than_the_layer():
    _, model = _populate()
    fascia = _fascia(model)
    assert fascia.width == WIDTH
    # its height direction runs up the sloped edge plane: tilted by the edge's slope from the panel normal
    assert abs(fascia.frame.zaxis[2]) == pytest.approx(math.cos(TILT)) and abs(fascia.frame.zaxis[0]) < 1e-9
    expected = THICKNESS / math.cos(TILT) + WIDTH * math.tan(TILT)  # covers the layer on both faces
    assert fascia.height == pytest.approx(expected) and fascia.height > THICKNESS


def test_the_studs_get_angled_cuts_on_the_fascia_inner_face():
    _, model = _populate()
    fascia = _fascia(model)
    across = fascia.frame.yaxis  # the fascia's width direction: normal to its faces
    studs = _beams(model, "stud")
    assert studs
    for stud in studs:
        top_cuts = []
        for feature in stud.features:
            if type(feature).__name__ != "JackRafterCutProxy":
                continue
            plane = feature.unproxified().plane_from_params_and_beam(stud)
            if abs(abs(dot_vectors(Vector(*plane.normal).unitized(), across)) - 1.0) < 1e-6:
                top_cuts.append(plane)
        (plane,) = top_cuts  # parallel to the sloped fascia faces, so not square to the stud
        assert abs(plane.normal[2]) > 0.1
        offset = abs(dot_vectors(Vector.from_start_end(fascia.frame.point, plane.point), across))
        assert offset == pytest.approx(WIDTH / 2 - MILL_DEPTH)  # on the inner face, housed like into a plate


def test_flush_cuts_are_optional():
    _, model = _populate()
    assert not any(type(f).__name__ == "LongitudinalCutProxy" for f in _fascia(model).features)
    _, model = _populate(flush_cuts=True)
    assert sum(type(f).__name__ == "LongitudinalCutProxy" for f in _fascia(model).features) == 2  # one per layer face


def test_a_square_panel_is_framed_like_the_edge_agent_frames_it():
    def fingerprint(agent_type):
        _, model = _populate(agent_type, rise=0.0)
        return sorted((b.attributes.get("category"), round(b.width, 3), round(b.height, 3), round(b.length, 3), type(b).__name__) for b in _beams(model))

    assert fingerprint(FasciaEdgeAgent) == fingerprint(EdgeAgent)


def test_the_edge_agent_still_uses_a_flat_beam_on_a_sloped_edge():
    _, model = _populate(EdgeAgent)
    assert not any(isinstance(b, FasciaBeam) for b in _beams(model))


def test_merging_turns_the_fascia_into_a_plain_beam():
    pop, model = _populate(merge=True, flush_cuts=True)
    fasciae = [b for b in model.find_all_elements_of_type(Beam) if b.attributes.get("category") == "top_plate_beam"]
    assert fasciae and all(type(b) is Beam for b in fasciae)
    assert all(b.height > THICKNESS for b in fasciae)


def test_the_agent_keeps_flush_cuts_through_clone_and_json():
    agent = FasciaEdgeAgent((0,), flush_cuts=True, top_plate_beam_width=80.0)
    for copy in (agent.clone(), json_loads(json_dumps(agent))):
        assert type(copy) is FasciaEdgeAgent and copy.flush_cuts and copy.beam_widths["top_plate_beam"] == 80.0


def test_the_fascia_height_is_rounded_with_the_width_increment():
    _, model = _populate(standard_beam_width_increment=20.0)
    fascia = _fascia(model)
    assert fascia.height % 20.0 == pytest.approx(0.0) and fascia.width % 20.0 == pytest.approx(0.0)

