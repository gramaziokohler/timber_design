"""Tests for connection details built by panel joints: LGenericPanelJoint's layer stagger, priorities.

The stagger replaces the removed ``PanelLLayerButtJoint``.  Its reference result is that joint's
algorithm, replayed in :func:`_old_layer_butt`: one ``PanelLButtJoint`` per same-role layer pair,
with the panel envelope left untouched.
"""

from compas.data import json_dumps
from compas.data import json_loads
from compas.geometry import Plane
from compas.geometry import Point
from compas.geometry import Polyline
from compas.geometry import Vector
from compas.tolerance import TOL
from compas_timber.connections import JointTopology
from compas_timber.utils import get_polyline_segment_perpendicular_vector

from timber_design_arch.connections import PanelJoint
from timber_design_arch.connections import PanelLButtJoint
from timber_design_arch.elements import LayerDefinition
from timber_design_arch.elements import LayerStructure
from timber_design_arch.elements import Panel
from timber_design_arch.model import ArchModel
from timber_design_arch.panel_features import PanelConnectionInterface

from timber_design_populator import EdgeAgent
from timber_design_populator import LayerExtensionDetailAgent
from timber_design_populator import LGenericPanelJoint
from timber_design_populator import PanelPopulator
from timber_design_populator import PanelType
from timber_design_populator import PlateAgent
from timber_design_populator import StudAgent
from timber_design_populator import stud_panel
from timber_design_populator.detail_sets import DetailAgentSet
from timber_design_populator.detail_sets import LGenericPanelJointDetailSet

ROLES = ("exterior_layer", "core_layer", "interior_layer")
EDGE_A = 0  # panel_a's vertical edge at x=0
EDGE_B = 0  # panel_b's vertical edge at y=0


# =============================================================================
# helpers
# =============================================================================


def _structure():
    return LayerStructure([LayerDefinition("exterior", 20.0), LayerDefinition("core"), LayerDefinition("interior", 15.0)])


def _corner_panels(structure=True):
    """Two walls (mm) meeting at a right-angle corner along the z-axis.

    panel_a lies in the XZ plane, 200 thick towards +y; panel_b in the YZ plane, 160 thick
    towards +x.  Their vertical edges at the origin (segment 0 of both) meet.
    """
    polyline_a = Polyline([Point(0, 0, 0), Point(0, 0, 2700), Point(4000, 0, 2700), Point(4000, 0, 0), Point(0, 0, 0)])
    polyline_b = Polyline([Point(0, 0, 0), Point(0, 0, 2700), Point(0, 3000, 2700), Point(0, 3000, 0), Point(0, 0, 0)])
    panel_a = Panel.from_outline_thickness(polyline_a, 200.0, vector=Vector(0, 1, 0))
    panel_b = Panel.from_outline_thickness(polyline_b, 160.0, vector=Vector(1, 0, 0))
    if structure:
        panel_a.layer_structure = _structure()
        panel_b.layer_structure = _structure()
    return panel_a, panel_b


def _model(panels):
    model = ArchModel()
    for panel in panels:
        model.add_element(panel)
        panel.merge_layer_structure(model)
    return model


def _ct_model(structure=True, joint_type=LGenericPanelJoint, **joint_kwargs):
    """What CT: Model does: add panels with layers, create the joint, process joinery."""
    panel_a, panel_b = _corner_panels(structure)
    model = _model([panel_a, panel_b])
    joint_type.create(model, panel_a, panel_b, topology=JointTopology.TOPO_EDGE_EDGE, a_segment_index=EDGE_A, b_segment_index=EDGE_B, **joint_kwargs)
    model.process_joinery()
    return model, panel_a, panel_b


def _ct_populate_model(model, populators):
    """What CT: Populate Model does: copy the model, bind the populators (they bring their layers), re-run the panel joints on the copy, populate."""
    copy = json_loads(json_dumps(model))
    for pop in populators:
        pop.update_panel_from_model(copy)
    panel_joints = [joint for joint in copy.joints if isinstance(joint, PanelJoint)]
    for joint in panel_joints:
        joint.add_extensions()
    for panel in copy.panels:
        panel.apply_edge_extensions()
    for joint in panel_joints:
        joint.add_features()
    for pop in populators:
        pop.populate_elements()
        pop.join_elements()
        pop.process_joinery()
        pop.merge_with_model(copy)
    return copy


def _stud_panel(panel):
    return stud_panel(panel, standard_beam_width=60.0, stud_spacing=625.0)


def _populate_both(structure=True, make_populator=_stud_panel, joint_type=LGenericPanelJoint, **joint_kwargs):
    model, panel_a, panel_b = _ct_model(structure, joint_type, **joint_kwargs)
    populators = [make_populator(panel) for panel in (panel_a, panel_b)]
    copy = _ct_populate_model(model, populators)
    return copy, populators, panel_a, panel_b


def _old_layer_butt():
    """Layer outlines produced by the removed PanelLLayerButtJoint (the reference)."""
    main, cross = _corner_panels()
    _model([main, cross])
    a, b = EDGE_A, EDGE_B
    pairs = [
        (cross.interior_layer, main.interior_layer, b, a),
        (main.core_layer, cross.core_layer, a, b),
        (cross.exterior_layer, main.exterior_layer, b, a),
    ]
    for layer_a, layer_b, index_a, index_b in pairs:
        PanelLButtJoint(panel_a=layer_a, panel_b=layer_b, topology=JointTopology.TOPO_EDGE_EDGE, a_segment_index=index_a, b_segment_index=index_b).add_extensions()
    for panel in (main, cross):
        panel.apply_edge_extensions()
    return main, cross


def _assert_same_outlines(layer, expected):
    for outline, expected_outline in zip(layer.outlines, expected.outlines):
        for point, expected_point in zip(outline.points, expected_outline.points):
            assert TOL.is_allclose(point, expected_point, atol=1e-3), "{} differs: {} != {}".format(layer.name, point, expected_point)


def _extension_agents(pop):
    return [a for a in pop.agents if isinstance(a, LayerExtensionDetailAgent)]


# =============================================================================
# the joint hands each panel its half
# =============================================================================


def test_the_joint_gives_each_interface_its_half_as_a_detail_set():
    model, panel_a, panel_b = _ct_model()
    for panel in (panel_a, panel_b):
        (interface,) = panel.interfaces
        assert isinstance(interface.detail_set, LGenericPanelJointDetailSet)
        assert len(interface.detail_set.extensions) == 3  # exterior, core, interior
        assert interface.detail_set.messages == []
        assert interface.detail_set.backing_positions == []  # backing studs off by default


def test_the_halves_are_in_each_panels_local_frame():
    """Applying a panel's planes in its local frame moves its layers exactly as the world-space oracle does."""
    copy, _, panel_a, panel_b = _populate_both()
    old_main, old_cross = _old_layer_butt()
    for panel, old in ((panel_a, old_main), (panel_b, old_cross)):
        for role in ROLES:
            _assert_same_outlines(getattr(copy.element_by_guid(str(panel.guid)), role), getattr(old, role))


def test_the_stagger_actually_moves_the_layers():
    """Guards the comparison above against passing vacuously."""
    staggered, _, *staggered_panels = _populate_both()
    plain, _, *plain_panels = _populate_both(stagger_layers=False)
    moved = 0
    for staggered_panel, plain_panel in zip(staggered_panels, plain_panels):
        for role in ROLES:
            a = getattr(staggered.element_by_guid(str(staggered_panel.guid)), role).outline_a.points
            b = getattr(plain.element_by_guid(str(plain_panel.guid)), role).outline_a.points
            moved += not all(TOL.is_allclose(p, q, atol=1e-3) for p, q in zip(a, b))
    assert moved >= 2


def test_without_stagger_the_layers_keep_the_joint_envelope():
    copy, populators, panel_a, _ = _populate_both(stagger_layers=False)
    for pop in populators:
        assert _extension_agents(pop) == []
        assert pop.debug_info.feature_errors == []
    populated = copy.element_by_guid(str(panel_a.guid))
    envelope = populated.edge_planes[EDGE_A]
    for role in ROLES:
        layer_plane = getattr(populated, role).edge_planes[EDGE_A]
        assert TOL.is_allclose(layer_plane.normal, envelope.normal) or TOL.is_allclose(layer_plane.normal, -envelope.normal)
        assert TOL.is_zero(abs(envelope.normal.dot(layer_plane.point - envelope.point)), tol=1e-3)


def test_missing_layers_are_reported_by_each_panel():
    _, populators, _, _ = _populate_both(structure=False)  # default structure: core only
    for pop in populators:
        messages = [error.message for error in pop.debug_info.feature_errors]
        assert len(messages) == 2  # exterior and interior; the core is staggered
        assert all("missing" in message for message in messages)


def test_a_populator_built_from_explicit_agents_builds_the_detail_too():
    def explicit(panel):
        return PanelPopulator(panel, PanelType("test", panel.layer_structure, agents=[EdgeAgent(panel.core_layer)], standard_beam_width=60.0))

    copy, populators, panel_a, panel_b = _populate_both(make_populator=explicit)
    old_main, old_cross = _old_layer_butt()
    for pop in populators:
        assert len(_extension_agents(pop)) == 1
    for panel, old in ((panel_a, old_main), (panel_b, old_cross)):
        for role in ROLES:
            _assert_same_outlines(getattr(copy.element_by_guid(str(panel.guid)), role), getattr(old, role))


def test_stagger_and_backing_studs_combine():
    copy, populators, panel_a, panel_b = _populate_both(backing_studs=True)
    old_main, old_cross = _old_layer_butt()
    for pop in populators:
        assert pop.debug_info.feature_errors == []
    for panel, old in ((panel_a, old_main), (panel_b, old_cross)):
        for role in ROLES:
            _assert_same_outlines(getattr(copy.element_by_guid(str(panel.guid)), role), getattr(old, role))
    cross = copy.element_by_guid(str(panel_b.guid))
    backing = [e for layer in cross.layers for e in layer.children if e.attributes.get("category") == "backing_stud"]
    assert len(backing) == 1


def test_repeated_solves_give_the_same_layers():
    model, panel_a, panel_b = _ct_model()
    populators = [_stud_panel(panel) for panel in (panel_a, panel_b)]
    first = _ct_populate_model(model, populators)
    second = _ct_populate_model(model, populators)
    for panel in (panel_a, panel_b):
        for role in ROLES:
            _assert_same_outlines(getattr(second.element_by_guid(str(panel.guid)), role), getattr(first.element_by_guid(str(panel.guid)), role))


def test_panels_enter_the_model_without_layers_and_their_panel_type_brings_them():
    """The GH workflow: CT: Model gets bare panels; the populators carry the type's layers."""
    panel_a, panel_b = _corner_panels(structure=False)
    model = ArchModel()
    for panel in (panel_a, panel_b):
        model.add_element(panel)  # no layers in the model
    LGenericPanelJoint.create(model, panel_a, panel_b, topology=JointTopology.TOPO_EDGE_EDGE, a_segment_index=EDGE_A, b_segment_index=EDGE_B)
    model.process_joinery()
    wall = PanelType("wall", _structure(), agents=[EdgeAgent("core")], standard_beam_width=60.0)
    populators = [wall.populator(panel) for panel in (panel_a, panel_b)]
    copy = _ct_populate_model(model, populators)
    for pop in populators:
        assert pop.debug_info.feature_errors == []  # the joint saw all three role layers
    old_main, old_cross = _old_layer_butt()
    for panel, old in ((panel_a, old_main), (panel_b, old_cross)):
        for role in ROLES:
            _assert_same_outlines(getattr(copy.element_by_guid(str(panel.guid)), role), getattr(old, role))
    assert model.element_by_guid(str(panel_a.guid)).layers == []  # the input model is left alone


def test_the_joint_serializes_its_flags():
    model, _, _ = _ct_model(backing_studs=True, backing_stud_width=45.0)
    (joint,) = [j for j in json_loads(json_dumps(model)).joints if isinstance(j, LGenericPanelJoint)]
    assert joint.stagger_layers and joint.backing_studs and joint.backing_stud_width == 45.0


# =============================================================================
# priority
# =============================================================================


def test_layer_extensions_run_first_and_edges_before_studs():
    _, populators, _, _ = _populate_both()
    for pop in populators:
        priorities = [a.priority for a in pop.agents]
        assert priorities == sorted(priorities)
        assert isinstance(pop.agents[0], LayerExtensionDetailAgent)


def test_equal_priorities_keep_the_given_order():
    panel, _ = _corner_panels()
    _model([panel])
    stud, plate_a, plate_b = StudAgent(panel.core_layer), PlateAgent(panel.exterior_layer), PlateAgent(panel.interior_layer)
    edge = EdgeAgent(panel.core_layer)
    pop = PanelPopulator(panel, PanelType("test", panel.layer_structure, agents=[stud, plate_a, edge, plate_b], standard_beam_width=60.0))
    assert [type(a) for a in pop.agents] == [EdgeAgent, StudAgent, PlateAgent, PlateAgent]
    assert [a.layer_path for a in pop.agents[2:]] == [plate_a.layer_path, plate_b.layer_path]


REACHES = (50.0, 80.0)


class _TwoExtensions(DetailAgentSet):
    """Two layer extensions of the same core edge, to different planes, with the given priorities."""

    FEATURE_TYPES = (PanelConnectionInterface,)

    def __init__(self, first=0, second=0):
        super().__init__()
        self.first, self.second = first, second

    @property
    def __data__(self):
        return {"first": self.first, "second": self.second}

    def expand(self, feature, panel, layer_tree, standard_beam_width=None):
        core = self.root_layer(layer_tree, "core")
        midpoint, outward = _edge(core, feature.edge_index)
        planes = [Plane(midpoint + outward * reach, outward) for reach in REACHES]
        agents = [
            LayerExtensionDetailAgent(edge_index=feature.edge_index, extensions=[{"layer_path": core.layer_path, "plane": plane}], feature=feature, priority=priority)
            for plane, priority in zip(planes, (self.first, self.second))
        ]
        return agents, []


def _edge(layer, edge_index):
    """The midpoint of *layer*'s edge and its outward direction, in the layer's frame."""
    outline = layer.outline_a
    return outline.lines[edge_index].midpoint, get_polyline_segment_perpendicular_vector(outline, edge_index).unitized()


def _core_edge_reach(first, second):
    """Populate panel_a with two competing core extensions; return the errors and how far the core edge moved out."""
    model, panel_a, _ = _ct_model(stagger_layers=False)
    edge_index = panel_a.interfaces[0].edge_index
    core_path = panel_a.layer_structure.get_path_for_role("core")
    panel_a.interfaces[0].detail_set = _TwoExtensions(first, second)
    pop = PanelPopulator(panel_a, PanelType("test", panel_a.layer_structure, agents=[EdgeAgent(panel_a.core_layer)], standard_beam_width=60.0))
    before, outward = _edge(panel_a.core_layer, edge_index)
    before = before.transformed(panel_a.modeltransformation.inverse())
    outward = outward.transformed(panel_a.modeltransformation.inverse())
    pop.populate_elements()
    after, _ = _edge(pop.layer_tree[core_path], edge_index)
    return pop.debug_info.feature_errors, outward.dot(after - before)


def test_two_details_moving_the_same_layer_edge_are_reported_and_priority_decides():
    errors, reach = _core_edge_reach(first=0, second=0)
    assert any("both set the extension" in e.message for e in errors)
    assert abs(reach - REACHES[1]) < 1e-3  # equal priority: the later agent wins

    _, reach = _core_edge_reach(first=5, second=0)
    assert abs(reach - REACHES[0]) < 1e-3  # a higher priority runs later, and wins


# =============================================================================
# Grasshopper joint rules
# =============================================================================


def test_gh_joint_rules_offer_the_detail_joints_and_their_flags():
    from timber_design_gh.ghcomponent_helpers import panel_joint_classes
    from timber_design_gh.ghcomponent_helpers import panel_joint_flag_names

    from timber_design_populator import TGenericPanelJoint

    edge_edge = panel_joint_classes(JointTopology.TOPO_EDGE_EDGE)
    edge_face = panel_joint_classes(JointTopology.TOPO_EDGE_FACE)
    assert edge_edge["LGenericPanelJoint"] is LGenericPanelJoint and "PanelMiterJoint" in edge_edge
    assert edge_face["TGenericPanelJoint"] is TGenericPanelJoint and "LGenericPanelJoint" not in edge_face
    assert panel_joint_flag_names(LGenericPanelJoint) == ["stagger_layers", "backing_studs", "backing_stud_width", "backing_stud_inset"]
    assert panel_joint_flag_names(PanelLButtJoint) == []
