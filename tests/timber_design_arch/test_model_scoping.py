"""Scoping of the connect_adjacent_* calls with panels as a third element type, moved here from compas_timber."""

from compas.geometry import Line
from compas.geometry import Point
from compas.geometry import Polyline

from compas_timber.connections import JointCandidate
from compas_timber.connections import JointTopology
from compas_timber.elements import Beam
from compas_timber.elements import Plate

from compas_arch.elements import Panel
from compas_arch.model import ArchModel


def _mixed_type_model():
    """A model holding one adjacent beam pair, one adjacent plate pair and one adjacent panel pair.

    The three pairs are placed far apart from each other so each type's `connect_adjacent_*` call
    yields exactly one candidate.
    """
    line1 = Line(Point(0, 0, 0), Point(1, 0, 0))
    line2 = Line(Point(0.5, -0.5, 0), Point(0.5, 0.5, 0))
    beam_a = Beam.from_centerline(line1, 0.1, 0.1)
    beam_b = Beam.from_centerline(line2, 0.1, 0.1)

    plate_outline_a = Polyline([Point(0, 0, 10), Point(0, 20, 10), Point(10, 20, 10), Point(10, 0, 10), Point(0, 0, 10)])
    plate_outline_b = Polyline([Point(0, 10, 10), Point(10, 10, 10), Point(20, 20, 20), Point(0, 20, 20), Point(0, 10, 10)])
    plate_a = Plate.from_outline_thickness(plate_outline_a, 1)
    plate_b = Plate.from_outline_thickness(plate_outline_b, 1)

    panel_outline_a = Polyline([Point(0, 0, 50), Point(0, 20, 50), Point(10, 20, 50), Point(10, 0, 50), Point(0, 0, 50)])
    panel_outline_b = Polyline([Point(0, 10, 50), Point(10, 10, 50), Point(20, 20, 60), Point(0, 20, 60), Point(0, 10, 50)])
    panel_a = Panel.from_outline_thickness(panel_outline_a, 1)
    panel_b = Panel.from_outline_thickness(panel_outline_b, 1)

    model = ArchModel()
    model.add_elements([beam_a, beam_b, plate_a, plate_b, panel_a, panel_b])
    return model, (beam_a, beam_b), (plate_a, plate_b), (panel_a, panel_b)


def _candidate_element_sets(model):
    return [set(candidate.elements) for candidate in model.joint_candidates]


def test_connect_adjacent_beams_keeps_plate_and_panel_candidates():
    """connect_adjacent_beams() is scoped to beams, so it must not clear plate-plate or
    panel-panel candidates created by earlier calls."""
    model, beams, plates, panels = _mixed_type_model()

    model.connect_adjacent_plates()
    model.connect_adjacent_panels()
    assert len(model.joint_candidates) == 2

    model.connect_adjacent_beams()

    element_sets = _candidate_element_sets(model)
    assert len(element_sets) == 3
    assert set(beams) in element_sets
    assert set(plates) in element_sets
    assert set(panels) in element_sets


def test_connect_adjacent_plates_keeps_beam_and_panel_candidates():
    """connect_adjacent_plates() is scoped to plates, so it must not clear beam-beam or
    panel-panel candidates created by earlier calls."""
    model, beams, plates, panels = _mixed_type_model()

    model.connect_adjacent_beams()
    model.connect_adjacent_panels()
    assert len(model.joint_candidates) == 2

    model.connect_adjacent_plates()

    element_sets = _candidate_element_sets(model)
    assert len(element_sets) == 3
    assert set(beams) in element_sets
    assert set(plates) in element_sets
    assert set(panels) in element_sets


def test_connect_adjacent_panels_keeps_beam_and_plate_candidates():
    """connect_adjacent_panels() is scoped to panels, so it must not clear beam-beam or
    plate-plate candidates created by earlier calls."""
    model, beams, plates, panels = _mixed_type_model()

    model.connect_adjacent_beams()
    model.connect_adjacent_plates()
    assert len(model.joint_candidates) == 2

    model.connect_adjacent_panels()

    element_sets = _candidate_element_sets(model)
    assert len(element_sets) == 3
    assert set(beams) in element_sets
    assert set(plates) in element_sets
    assert set(panels) in element_sets


def test_connect_adjacent_beams_recomputes_only_beam_candidates():
    """Repeated connect_adjacent_* calls stay idempotent per scope: the beam candidate is replaced,
    the out-of-scope candidates are neither cleared nor duplicated."""
    model, beams, plates, panels = _mixed_type_model()

    model.connect_adjacent_beams()
    model.connect_adjacent_plates()
    model.connect_adjacent_panels()
    assert len(model.joint_candidates) == 3

    before = {candidate for candidate in model.joint_candidates if set(candidate.elements) != set(beams)}

    model.connect_adjacent_beams()

    assert len(model.joint_candidates) == 3
    after = {candidate for candidate in model.joint_candidates if set(candidate.elements) != set(beams)}
    assert after == before  # same candidate objects, not recreated


def test_connect_adjacent_beams_keeps_partially_scoped_candidate():
    """A candidate spanning two scopes (here beam-to-plate) is only cleared when *all* of its
    elements are in scope, so a beams-only pass must leave it alone."""
    model, beams, plates, _ = _mixed_type_model()

    mixed_candidate = JointCandidate(beams[0], plates[0], topology=JointTopology.TOPO_T)
    model.add_joint_candidate(mixed_candidate)
    assert len(model.joint_candidates) == 1

    model.connect_adjacent_beams()

    candidates = list(model.joint_candidates)
    assert mixed_candidate in candidates
    assert set(beams) in _candidate_element_sets(model)
    assert len(candidates) == 2


def test_connect_adjacent_plates_keeps_partially_scoped_candidate():
    """The same guard applies from the plate side: a beam-to-plate candidate survives a
    plates-only pass because its beam is out of scope."""
    model, beams, plates, _ = _mixed_type_model()

    mixed_candidate = JointCandidate(beams[0], plates[0], topology=JointTopology.TOPO_T)
    model.add_joint_candidate(mixed_candidate)
    assert len(model.joint_candidates) == 1

    model.connect_adjacent_plates()

    candidates = list(model.joint_candidates)
    assert mixed_candidate in candidates
    assert set(plates) in _candidate_element_sets(model)
    assert len(candidates) == 2


def test_compute_topologies_unscoped_clears_all_candidates():
    """Without an `elements` argument every element is in scope, so all existing candidates -
    including cross-type ones - are cleared and recomputed."""
    model, beams, plates, panels = _mixed_type_model()

    mixed_candidate = JointCandidate(beams[0], plates[0], topology=JointTopology.TOPO_T)
    model.add_joint_candidate(mixed_candidate)

    model.compute_topologies()

    candidates = list(model.joint_candidates)
    assert mixed_candidate not in candidates  # beam-plate isn't a registered combination, so it isn't recreated
    element_sets = _candidate_element_sets(model)
    assert len(element_sets) == 3
    assert set(beams) in element_sets
    assert set(plates) in element_sets
    assert set(panels) in element_sets


def test_connect_adjacent_plates_and_panels_equivalent():
    """connect_adjacent_plates() and connect_adjacent_panels() should produce equivalent candidates
    for equivalent geometry, since both dispatch through the same plate/panel handler."""
    polyline_a = Polyline([Point(0, 0, 0), Point(0, 20, 0), Point(10, 20, 0), Point(10, 0, 0), Point(0, 0, 0)])
    polyline_b = Polyline([Point(0, 10, 0), Point(10, 10, 0), Point(20, 20, 10), Point(0, 20, 10), Point(0, 10, 0)])

    plate_model = ArchModel()
    plate_a = Plate.from_outline_thickness(polyline_a, 1)
    plate_b = Plate.from_outline_thickness(polyline_b, 1)
    plate_model.add_elements([plate_a, plate_b])
    plate_model.connect_adjacent_plates()

    panel_model = ArchModel()
    panel_a = Panel.from_outline_thickness(polyline_a, 1)
    panel_b = Panel.from_outline_thickness(polyline_b, 1)
    panel_model.add_elements([panel_a, panel_b])
    panel_model.connect_adjacent_panels()

    plate_candidates = list(plate_model.joint_candidates)
    panel_candidates = list(panel_model.joint_candidates)
    assert len(plate_candidates) == len(panel_candidates) == 1
    assert plate_candidates[0].topology == panel_candidates[0].topology
    assert plate_candidates[0].a_segment_index == panel_candidates[0].a_segment_index
