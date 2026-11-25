"""Tests for backing studs (``backing_studs=True`` on the generic panel joints), end to end through the Grasshopper sequence."""

import pytest

from compas.data import json_dumps
from compas.data import json_loads
from compas.geometry import Point
from compas.geometry import Polyline
from compas.geometry import Vector
from compas_timber.connections import JointTopology
from compas_timber.elements import Beam

from compas_arch.connections import PanelJoint
from compas_arch.connections import PanelTButtJoint
from compas_arch.elements import Panel
from compas_arch.model import ArchModel

from timber_design_populator import BackingStudDetailAgent
from timber_design_populator import LGenericPanelJoint
from timber_design_populator import TGenericPanelJoint
from timber_design_populator import stud_panel

WIDTH = 60.0  # standard_beam_width


# =============================================================================
# geometry: a 6 m through-wall in the XZ plane (160 thick towards +y)
# =============================================================================


def _through_wall():
    outline = Polyline([Point(0, 0, 0), Point(6000, 0, 0), Point(6000, 0, 2700), Point(0, 0, 2700), Point(0, 0, 0)])
    return Panel.from_outline_thickness(outline, 160.0, vector=Vector(0, 1, 0))


def _partition(x=3000.0, thickness=100.0):
    """A wall in the YZ plane at *x*, *thickness* towards +x, whose edge 0 lands on the through-wall's +y face."""
    outline = Polyline([Point(x, 160, 0), Point(x, 160, 2700), Point(x, 3160, 2700), Point(x, 3160, 0), Point(x, 160, 0)])
    return Panel.from_outline_thickness(outline, thickness, vector=Vector(1, 0, 0))


def _corner_walls():
    """An L corner: main in the XZ plane (200 thick, +y), cross in the YZ plane (160 thick, +x); edges 0 meet."""
    main = Panel.from_outline_thickness(Polyline([Point(0, 0, 0), Point(0, 0, 2700), Point(4000, 0, 2700), Point(4000, 0, 0), Point(0, 0, 0)]), 200.0, vector=Vector(0, 1, 0))
    cross = Panel.from_outline_thickness(Polyline([Point(0, 0, 0), Point(0, 0, 2700), Point(0, 3000, 2700), Point(0, 3000, 0), Point(0, 0, 0)]), 160.0, vector=Vector(1, 0, 0))
    return main, cross


# =============================================================================
# workflow
# =============================================================================


def _solve(main, cross, joint_type, **joint_kwargs):
    """CT: Model then CT: Populate Model on *main* and *cross*; returns the populated copy and the populators."""
    model = ArchModel()
    for panel in (main, cross):
        model.add_element(panel)
        panel.merge_layer_structure(model)
    joint_type.create(model, main, cross, **joint_kwargs)
    model.process_joinery()

    populators = [stud_panel(panel, standard_beam_width=WIDTH, stud_spacing=600.0) for panel in (main, cross)]
    copy = json_loads(json_dumps(model))
    panel_joints = [joint for joint in copy.joints if isinstance(joint, PanelJoint)]
    for joint in panel_joints:
        joint.add_extensions()
    for panel in copy.panels:
        panel.apply_edge_extensions()
    for joint in panel_joints:
        joint.add_features()
    for pop in populators:
        pop.update_panel_from_model(copy)
        pop.populate_elements()
        pop.join_elements()
        pop.process_joinery()
        pop.merge_with_model(copy)
    return copy, populators


def _t_junction(joint_type=TGenericPanelJoint, **kwargs):
    cross, main = _through_wall(), _partition(**{k: kwargs.pop(k) for k in ("x", "thickness") if k in kwargs})
    if joint_type is TGenericPanelJoint:
        kwargs.setdefault("backing_studs", True)
    copy, populators = _solve(main, cross, joint_type, topology=JointTopology.TOPO_EDGE_FACE, a_segment_index=0, b_segment_index=None, **kwargs)
    return copy, populators, main, cross


def _beams(model, panel, category):
    """Beams of *category* under *panel* in *model*."""
    panel = model.element_by_guid(str(panel.guid))
    result = []

    def walk(element):
        for child in element.children:
            if isinstance(child, Beam) and child.attributes.get("category") == category:
                result.append(child)
            walk(child)

    walk(panel)
    return result


def _x(beam):
    return beam.centerline.midpoint[0]


# =============================================================================
# construction
# =============================================================================


def test_backing_stud_agent_has_its_joint_rules_and_category():
    agent = BackingStudDetailAgent()
    assert agent.external_rules and all("backing_stud" in (rule.category_a, rule.category_b) for rule in agent.external_rules)
    assert "backing_stud" in agent.beam_widths


def test_clone_keeps_positions_direction_and_width():
    agent = BackingStudDetailAgent(positions=[Point(1, 2, 3)], direction=Vector(0, 0, 1), width=45.0)
    clone = agent.clone()
    assert clone.beam_widths["backing_stud"] == 45.0
    assert clone.positions == [Point(1, 2, 3)] and clone.direction == Vector(0, 0, 1)


def test_backing_studs_are_off_by_default():
    copy, _, _, cross = _t_junction(backing_studs=False)
    assert _beams(copy, cross, "backing_stud") == []


def test_a_plain_panel_joint_carries_no_detail():
    copy, populators, _, cross = _t_junction(joint_type=PanelTButtJoint)
    assert _beams(copy, cross, "backing_stud") == []
    for pop in populators:
        assert pop.debug_info.feature_errors == []


# =============================================================================
# T junction
# =============================================================================


def test_t_junction_backs_both_inside_corners_of_the_through_wall():
    copy, _, main, cross = _t_junction()
    backing = sorted(_beams(copy, cross, "backing_stud"), key=_x)

    assert [round(_x(b)) for b in backing] == [3000, 3100]  # centred on the partition's two faces
    for beam in backing:
        assert abs(beam.centerline.direction.unitized()[2]) == pytest.approx(1.0)  # vertical, like the junction
        assert beam.width == pytest.approx(WIDTH)
        assert 2400 < beam.centerline.length < 2700  # trimmed between the plates


def test_t_junction_main_panel_gets_nothing():
    copy, _, main, _ = _t_junction()
    assert _beams(copy, main, "backing_stud") == []


def test_regular_studs_overlapping_a_backing_stud_are_removed():
    copy, _, _, cross = _t_junction()
    # stud_spacing 600 puts a regular stud at x=3000 on a 6000 wall
    studs = _beams(copy, cross, "stud")
    assert studs, "expected regular studs elsewhere on the wall"
    assert not any(abs(_x(stud) - 3000) < WIDTH for stud in studs)


def test_backing_studs_are_joined_to_the_plates():
    copy, _, _, cross = _t_junction()
    backing = _beams(copy, cross, "backing_stud")
    joined = [b for b in backing if any(b in joint.elements for joint in copy.joints)]
    assert len(joined) == len(backing)


def test_no_errors_reported():
    _, populators, _, _ = _t_junction()
    for pop in populators:
        assert pop.debug_info.feature_errors == []


# =============================================================================
# parameters
# =============================================================================


def test_width_param_sets_the_backing_stud_width():
    copy, _, _, cross = _t_junction(backing_stud_width=45.0)
    backing = _beams(copy, cross, "backing_stud")
    assert backing and all(beam.width == pytest.approx(45.0) for beam in backing)


def test_inset_moves_studs_into_the_footprint_and_merges_them_when_close():
    copy, _, _, cross = _t_junction(backing_stud_inset=30.0)  # 3030 and 3070: closer than one width
    backing = _beams(copy, cross, "backing_stud")
    assert [round(_x(b)) for b in backing] == [3050]


def test_thin_partition_gets_one_centred_stud():
    copy, _, _, cross = _t_junction(thickness=50.0)
    assert [round(_x(b)) for b in _beams(copy, cross, "backing_stud")] == [3025]


# =============================================================================
# floor landing on a wall: horizontal backing studs
# =============================================================================


def _floor(z=1200.0, thickness=220.0):
    """A floor whose edge 0 (along x at y=160) lands on the through-wall's +y face, *thickness* upwards from *z*."""
    outline = Polyline([Point(0, 160, z), Point(6000, 160, z), Point(6000, 3160, z), Point(0, 3160, z), Point(0, 160, z)])
    return Panel.from_outline_thickness(outline, thickness, vector=Vector(0, 0, 1))


def _floor_on_wall(backing_studs=True):
    wall, floor = _through_wall(), _floor()
    copy, _ = _solve(floor, wall, TGenericPanelJoint, backing_studs=backing_studs, topology=JointTopology.TOPO_EDGE_FACE, a_segment_index=0, b_segment_index=None)
    return copy, wall


def test_floor_on_wall_gets_horizontal_backing_studs_at_the_floor_faces():
    copy, wall = _floor_on_wall()
    backing = _beams(copy, wall, "backing_stud")
    assert sorted(round(b.centerline.midpoint[2]) for b in backing) == [1200, 1420]
    for beam in backing:
        assert abs(beam.centerline.direction.unitized()[0]) == pytest.approx(1.0)  # horizontal, along the junction


def test_backing_studs_across_the_studs_do_not_remove_them():
    """Only regular studs parallel to a backing stud are removed; these cross it."""
    with_details, wall = _floor_on_wall()
    without_details, plain_wall = _floor_on_wall(backing_studs=False)
    assert len(_beams(with_details, wall, "stud")) == len(_beams(without_details, plain_wall, "stud")) > 0


# =============================================================================
# L corner
# =============================================================================


def test_l_corner_backs_only_the_inside_corner():
    main, cross = _corner_walls()
    copy, populators = _solve(
        main, cross, LGenericPanelJoint, stagger_layers=False, backing_studs=True, topology=JointTopology.TOPO_EDGE_EDGE, a_segment_index=0, b_segment_index=0
    )

    backing = _beams(copy, cross, "backing_stud")
    # the main wall spans y=0..200; the y=0 face is the outer corner, already backed by the edge stud
    assert [round(b.centerline.midpoint[1]) for b in backing] == [200]
    assert _beams(copy, main, "backing_stud") == []
    for pop in populators:
        assert pop.debug_info.feature_errors == []
