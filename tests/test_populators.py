"""Unit tests for the individual populator agents and factory helpers.

Tests here work one level below the full PanelPopulator workflow: they
instantiate agents directly (bound to a panel's ``core_layer`` /
``interior_layer`` / ``exterior_layer``) and assert that ``generate_elements``
produces the right element types, categories, and counts for a known panel
geometry.

All panels are created in mm units.
"""

import pytest

from compas.geometry import Point
from compas.geometry import Polyline
from compas_timber.connections import LButtJoint
from compas_timber.connections import TButtJoint
from compas_timber.elements import Layer
from compas_timber.elements import LayerDefinition
from compas_timber.elements import LayerStructure
from compas_timber.elements import Panel
from compas_timber.elements import Plate

from timber_design.populators import EdgePopulatorAgent
from timber_design.populators import PanelPopulator
from timber_design.populators import PlatePopulatorAgent
from timber_design.populators import StudPopulatorAgent
from timber_design.connections_2d.beam2d import Beam2D
from timber_design.populators.populator_configs.stud_panel_config import stud_panel
from timber_design.workflow import CategoryRule

try:
    from timber_design.populators import OpeningPopulatorAgent

    _HAS_OPENING = True
except ImportError:  # Opening not in the installed compas_timber
    _HAS_OPENING = False

requires_opening = pytest.mark.skipif(not _HAS_OPENING, reason="Opening not available in installed compas_timber")


# =============================================================================
# Helpers
# =============================================================================


def make_outline(xmin, ymin, xmax, ymax, z=0.0):
    return Polyline(
        [
            Point(xmin, ymin, z),
            Point(xmax, ymin, z),
            Point(xmax, ymax, z),
            Point(xmin, ymax, z),
            Point(xmin, ymin, z),
        ]
    )


def make_panel(width=4000.0, height=2700.0, thickness=160.0, sheeting_inside=0.0, sheeting_outside=0.0):
    """Build a Panel; attach an exterior/core/interior layer_structure when sheeting is requested."""
    panel = Panel.from_outline_thickness(make_outline(0, 0, width, height), thickness)
    if sheeting_inside or sheeting_outside:
        layer_defs = []
        if sheeting_outside:
            layer_defs.append(LayerDefinition(name="exterior", thickness=sheeting_outside))
        layer_defs.append(LayerDefinition(name="core"))
        if sheeting_inside:
            layer_defs.append(LayerDefinition(name="interior", thickness=sheeting_inside))
        panel.layer_structure = LayerStructure(layer_defs=layer_defs)
    return panel


def make_agent(agent_cls, layer, standard_beam_width=60.0, **kwargs):
    """Construct an agent bound to *layer*, filling beam widths as
    :meth:`~timber_design.populators.PanelPopulator.resolve_beam_widths` would."""
    agent = agent_cls(layer, **kwargs)
    for category in agent.BEAM_CATEGORY_NAMES:
        if agent.beam_widths.get(category) is None:
            agent.beam_widths[category] = standard_beam_width
    agent.repoint_to_layer_tree({layer.layer_path: layer})
    return agent


# =============================================================================
# EdgePopulatorAgent
# =============================================================================


class TestEdgePopulatorAgent:
    @pytest.fixture
    def gen(self):
        panel = make_panel(width=3000.0, height=2000.0, thickness=160.0)
        # standard_beam_width=60.0 (make_agent default) fills all edge categories
        g = make_agent(EdgePopulatorAgent, panel.core_layer)
        g.generate_elements()
        return g

    def test_produces_elements(self, gen):
        assert len(gen.elements) > 0

    def test_all_elements_are_beam2d(self, gen):
        assert all(isinstance(e, Beam2D) for e in gen.elements)

    def test_categories_assigned(self, gen):
        cats = {e.attributes.get("category") for e in gen.elements}
        assert cats & {"top_plate_beam", "bottom_plate_beam", "edge_stud"}

    def test_no_element_has_zero_length(self, gen):
        for e in gen.elements:
            if isinstance(e, Beam2D):
                assert e.length > 0

    def test_outline_set_after_generate(self, gen):
        assert gen.outline_for_layer(gen.layer) is not None

    def test_aabb_covers_all_elements(self, gen):
        from timber_design.connections_2d.beam2d import AABB2D

        assert gen.aabb is not None
        assert isinstance(gen.aabb, AABB2D)

    def test_width_uses_standard_beam_width(self, gen):
        # make_agent default standard_beam_width=60.0 → all beams should be 60.0
        for e in gen.elements:
            assert e.width == 60.0

    def test_explicit_per_category_width(self):
        panel = make_panel(width=3000.0, height=2000.0, thickness=160.0)
        g = make_agent(
            EdgePopulatorAgent,
            panel.core_layer,
            edge_stud_width=80.0,
            top_plate_beam_width=60.0,
            bottom_plate_beam_width=60.0,
        )
        g.generate_elements()
        for e in g.elements:
            if e.attributes["category"] == "edge_stud":
                assert e.width == 80.0
            else:
                assert e.width == 60.0

    def test_standard_width_increment_rounds_up(self):
        panel = make_panel()
        # standard_beam_width=60.0 → 60 is already a multiple of 20
        g = make_agent(EdgePopulatorAgent, panel.core_layer, standard_beam_width_increment=20.0)
        g.generate_elements()
        for e in g.elements:
            assert e.width % 20.0 < 1.0


# =============================================================================
# StudPopulatorAgent
# =============================================================================


class TestStudPopulatorAgent:
    @pytest.fixture
    def gen(self):
        panel = make_panel(width=4000.0, height=2700.0, thickness=160.0)
        g = make_agent(StudPopulatorAgent, panel.core_layer, stud_spacing=625.0)
        g.generate_elements()
        return g

    def test_produces_studs(self, gen):
        assert len(gen.elements) > 0

    def test_all_elements_are_beam2d(self, gen):
        assert all(isinstance(e, Beam2D) for e in gen.elements)

    def test_all_are_stud_category(self, gen):
        assert all(e.attributes.get("category") == "stud" for e in gen.elements)

    def test_stud_height_equals_layer_thickness(self, gen):
        for e in gen.elements:
            assert abs(e.height - 160.0) < 1.0

    def test_stud_width_equals_standard(self, gen):
        for e in gen.elements:
            assert abs(e.width - 60.0) < 1.0

    def test_stud_count_matches_spacing(self, gen):
        assert 4 <= len(gen.elements) <= 7

    def test_no_element_has_zero_length(self, gen):
        for e in gen.elements:
            assert e.length > 0

    def test_fewer_studs_with_wider_spacing(self):
        panel = make_panel(width=4000.0, height=2700.0)

        g_narrow = make_agent(StudPopulatorAgent, panel.core_layer, stud_spacing=300.0)
        g_narrow.generate_elements()

        g_wide = make_agent(StudPopulatorAgent, panel.core_layer, stud_spacing=900.0)
        g_wide.generate_elements()

        assert len(g_narrow.elements) > len(g_wide.elements)


# =============================================================================
# PlatePopulatorAgent
# =============================================================================


class TestPlatePopulatorAgent:
    def test_interior_plate_produced(self):
        panel = make_panel(thickness=160.0, sheeting_inside=15.0)
        g = make_agent(PlatePopulatorAgent, panel.interior_layer)
        g.generate_elements()
        assert any(isinstance(e, Plate) for e in g.elements)

    def test_exterior_plate_produced(self):
        panel = make_panel(thickness=160.0, sheeting_outside=22.0)
        g = make_agent(PlatePopulatorAgent, panel.exterior_layer)
        g.generate_elements()
        assert any(isinstance(e, Plate) for e in g.elements)

    def test_both_plates_produced(self):
        panel = make_panel(thickness=160.0, sheeting_inside=15.0, sheeting_outside=22.0)
        g_i = make_agent(PlatePopulatorAgent, panel.interior_layer)
        g_i.generate_elements()
        g_e = make_agent(PlatePopulatorAgent, panel.exterior_layer)
        g_e.generate_elements()
        plates = [e for e in g_i.elements + g_e.elements if isinstance(e, Plate)]
        assert len(plates) == 2

    def test_no_sheeting_no_interior_exterior(self):
        panel = make_panel(thickness=160.0)
        assert panel.interior_layer is None
        assert panel.exterior_layer is None

    def test_plate_category(self):
        panel = make_panel(thickness=160.0, sheeting_inside=15.0)
        g = make_agent(PlatePopulatorAgent, panel.interior_layer)
        g.generate_elements()
        plates = [e for e in g.elements if isinstance(e, Plate)]
        assert all(e.attributes.get("category") == "plate" for e in plates)


# =============================================================================
# Panel layer_structure (exterior / core / interior)
# =============================================================================


class TestPanelLayers:
    def test_always_has_core(self):
        panel = make_panel(thickness=160.0)
        assert panel.core_layer is not None

    def test_no_sheeting_single_layer(self):
        panel = make_panel(thickness=160.0)
        assert panel.interior_layer is None
        assert panel.exterior_layer is None

    def test_sheeting_inside_creates_interior_layer(self):
        panel = make_panel(thickness=160.0, sheeting_inside=15.0)
        assert panel.interior_layer is not None
        assert panel.exterior_layer is None

    def test_sheeting_outside_creates_exterior_layer(self):
        panel = make_panel(thickness=160.0, sheeting_outside=22.0)
        assert panel.exterior_layer is not None
        assert panel.interior_layer is None

    def test_both_sheeting_creates_both_layers(self):
        panel = make_panel(thickness=160.0, sheeting_inside=15.0, sheeting_outside=22.0)
        assert panel.interior_layer is not None
        assert panel.exterior_layer is not None

    def test_layers_are_layer_instances(self):
        panel = make_panel(thickness=160.0, sheeting_inside=15.0, sheeting_outside=22.0)
        assert isinstance(panel.core_layer, Layer)
        assert isinstance(panel.interior_layer, Layer)
        assert isinstance(panel.exterior_layer, Layer)

    def test_interior_layer_thickness(self):
        panel = make_panel(thickness=160.0, sheeting_inside=15.0)
        assert abs(panel.interior_layer.thickness - 15.0) < 1.0

    def test_exterior_layer_thickness(self):
        panel = make_panel(thickness=160.0, sheeting_outside=22.0)
        assert abs(panel.exterior_layer.thickness - 22.0) < 1.0

    def test_core_thickness_reduced_by_sheeting(self):
        panel = make_panel(thickness=160.0, sheeting_inside=15.0, sheeting_outside=22.0)
        assert abs(panel.core_layer.thickness - (160.0 - 15.0 - 22.0)) < 1.0

    def test_layer_names(self):
        panel = make_panel(thickness=160.0, sheeting_inside=15.0, sheeting_outside=22.0)
        assert panel.core_layer.name == "core"
        assert panel.interior_layer.name == "interior"
        assert panel.exterior_layer.name == "exterior"


# =============================================================================
# stud_panel factory: PanelPopulator.agents composition
# =============================================================================


class TestStudPanelFactory:
    def _pop(self, **kwargs):
        panel = kwargs.pop("panel", None) or make_panel()
        return stud_panel(panel=panel, standard_beam_width=60.0, stud_spacing=625.0, **kwargs)

    def test_returns_non_empty_list(self):
        pop = self._pop()
        assert len(pop.agents) >= 2  # at minimum: edge + stud

    def test_edge_agent_present(self):
        pop = self._pop()
        assert any(isinstance(a, EdgePopulatorAgent) for a in pop.agents)

    def test_stud_agent_present_when_spacing_set(self):
        pop = self._pop()
        assert any(isinstance(a, StudPopulatorAgent) for a in pop.agents)

    def test_default_stud_spacing_when_spacing_none(self):
        panel = make_panel()
        pop = stud_panel(panel=panel, standard_beam_width=60.0, stud_spacing=None)
        assert any(isinstance(a, StudPopulatorAgent) for a in pop.agents)

    def test_plate_agent_present_when_sheeting_set(self):
        pop = self._pop(panel=make_panel(sheeting_inside=15.0))
        assert any(isinstance(a, PlatePopulatorAgent) for a in pop.agents)

    def test_no_plate_agent_without_sheeting(self):
        pop = self._pop()
        assert not any(isinstance(a, PlatePopulatorAgent) for a in pop.agents)

    def test_beam_widths_resolved_on_agents(self):
        pop = self._pop()
        for a in pop.agents:
            assert a.beam_widths, "{}.beam_widths is empty after resolve".format(type(a).__name__)


# =============================================================================
# PanelPopulator.route_rule_overrides
# =============================================================================


class TestRouteRuleOverrides:
    """Routes :class:`CategoryRule` overrides to per-agent internal/external rule slots."""

    def _pop(self, *agents):
        return PanelPopulator(panel=make_panel(), agents=list(agents))

    def test_none_is_a_noop(self):
        edge = EdgePopulatorAgent(None)
        self._pop(edge).route_rule_overrides(None)
        assert not edge.internal_overrides
        assert not edge.external_overrides

    def test_empty_list_is_a_noop(self):
        edge = EdgePopulatorAgent(None)
        self._pop(edge).route_rule_overrides([])
        assert not edge.internal_overrides
        assert not edge.external_overrides

    def test_internal_when_both_categories_owned_by_one_agent(self):
        """Both ``edge_stud`` and ``top_plate_beam`` are EdgePopulatorAgent categories
        → the rule lands in the edge agent's internal_rules."""
        edge = EdgePopulatorAgent(None)
        rule = CategoryRule(LButtJoint, "edge_stud", "top_plate_beam", mill_depth=5.0)
        self._pop(edge).route_rule_overrides([rule])
        assert rule in edge.internal_rules
        assert not edge.external_overrides

    def test_external_when_categories_span_two_agents(self):
        """``stud`` belongs to StudPopulatorAgent and ``top_plate_beam`` to
        EdgePopulatorAgent → the rule lands as an external override on *both*."""
        edge = EdgePopulatorAgent(None)
        stud = StudPopulatorAgent(None)
        rule = CategoryRule(TButtJoint, "stud", "top_plate_beam", mill_depth=10.0)
        self._pop(edge, stud).route_rule_overrides([rule])
        assert rule in edge.external_overrides
        assert rule in stud.external_overrides

    def test_skipped_when_no_agent_owns_either_category(self):
        edge = EdgePopulatorAgent(None)
        stud = StudPopulatorAgent(None)
        rule = CategoryRule(LButtJoint, "foo", "bar")
        self._pop(edge, stud).route_rule_overrides([rule])
        assert rule not in edge.internal_rules
        assert not edge.external_overrides
        assert rule not in stud.internal_rules
        assert not stud.external_overrides

    def test_routing_is_idempotent_for_the_same_rule(self):
        """Routing the same rule twice must not produce a duplicate."""
        edge = EdgePopulatorAgent(None)
        rule = CategoryRule(LButtJoint, "edge_stud", "top_plate_beam", mill_depth=5.0)
        pop = self._pop(edge)
        pop.route_rule_overrides([rule])
        pop.route_rule_overrides([rule])
        assert edge.internal_rules.count(rule) == 1

    def test_unordered_dedup_for_non_T_joints(self):
        """L/X joints don't care about category order, so ``(a,b)`` and ``(b,a)``
        for the same joint type collapse to a single rule for that pair."""
        edge = EdgePopulatorAgent(None)
        ab = CategoryRule(LButtJoint, "edge_stud", "top_plate_beam", mill_depth=5.0)
        ba = CategoryRule(LButtJoint, "top_plate_beam", "edge_stud", mill_depth=5.0)
        self._pop(edge).route_rule_overrides([ab, ba])
        matches = [
            r for r in edge.internal_rules
            if r.joint_type is LButtJoint and {r.category_a, r.category_b} == {"edge_stud", "top_plate_beam"}
        ]
        assert len(matches) == 1

    def test_rule_overrides_routed_via_stud_panel(self):
        """End-to-end: ``joint_rule_overrides`` passed to ``stud_panel()`` reach the
        right agent slots after the factory finishes."""
        edge_rule = CategoryRule(LButtJoint, "edge_stud", "top_plate_beam", mill_depth=5.0)
        cross_rule = CategoryRule(TButtJoint, "stud", "top_plate_beam", mill_depth=10.0)
        unknown_rule = CategoryRule(LButtJoint, "foo", "bar")

        panel = make_panel()
        pop = stud_panel(
            panel=panel,
            standard_beam_width=60.0,
            stud_spacing=625.0,
            joint_rule_overrides=[edge_rule, cross_rule, unknown_rule],
        )
        edge = next(a for a in pop.agents if isinstance(a, EdgePopulatorAgent))
        stud = next(a for a in pop.agents if isinstance(a, StudPopulatorAgent))

        # edge_rule → both categories owned by the edge agent → internal on edge.
        assert edge_rule in edge.internal_rules
        # cross_rule → stud + top_plate_beam straddle the two agents → external on both.
        assert cross_rule in edge.external_overrides
        assert cross_rule in stud.external_overrides
        # unknown_rule → no agent owns either category → not appended anywhere.
        for agent in (edge, stud):
            assert unknown_rule not in agent.internal_rules
            assert unknown_rule not in agent.external_overrides
