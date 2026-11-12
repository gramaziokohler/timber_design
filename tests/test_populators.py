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
from timber_design.populators import stud_panel
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


def generate_flat(agent):
    """Run ``generate_elements`` and flatten the per-layer dict into one list."""
    return [e for layer_elements in agent.generate_elements().values() for e in layer_elements]


# =============================================================================
# EdgePopulatorAgent
# =============================================================================


class TestEdgePopulatorAgent:
    @pytest.fixture
    def agent(self):
        panel = make_panel(width=3000.0, height=2000.0, thickness=160.0)
        # standard_beam_width=60.0 (make_agent default) fills all edge categories
        return make_agent(EdgePopulatorAgent, panel.core_layer)

    @pytest.fixture
    def elements(self, agent):
        return generate_flat(agent)

    def test_produces_elements(self, elements):
        assert len(elements) > 0

    def test_all_elements_are_beam2d(self, elements):
        assert all(isinstance(e, Beam2D) for e in elements)

    def test_categories_assigned(self, elements):
        cats = {e.attributes.get("category") for e in elements}
        assert cats & {"top_plate_beam", "bottom_plate_beam", "edge_stud"}

    def test_no_element_has_zero_length(self, elements):
        for e in elements:
            if isinstance(e, Beam2D):
                assert e.length > 0

    def test_outline_set_after_generate(self, agent, elements):
        assert agent.outline_for_layer(agent.layer) is not None

    def test_aabb_covers_all_elements(self, elements):
        from timber_design.connections_2d.beam2d import AABB2D

        aabb = AABB2D.from_points([p for e in elements for p in e.aabb.points])
        for e in elements:
            assert aabb.xmin <= e.aabb.xmin and aabb.xmax >= e.aabb.xmax
            assert aabb.ymin <= e.aabb.ymin and aabb.ymax >= e.aabb.ymax

    def test_width_uses_standard_beam_width(self, elements):
        # make_agent default standard_beam_width=60.0 → all beams should be 60.0
        for e in elements:
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
        for e in generate_flat(g):
            if e.attributes["category"] == "edge_stud":
                assert e.width == 80.0
            else:
                assert e.width == 60.0

    def test_standard_width_increment_rounds_up(self):
        panel = make_panel()
        # standard_beam_width=60.0 → 60 is already a multiple of 20
        g = make_agent(EdgePopulatorAgent, panel.core_layer, standard_beam_width_increment=20.0)
        for e in generate_flat(g):
            assert e.width % 20.0 < 1.0


# =============================================================================
# StudPopulatorAgent
# =============================================================================


class TestStudPopulatorAgent:
    @pytest.fixture
    def elements(self):
        panel = make_panel(width=4000.0, height=2700.0, thickness=160.0)
        g = make_agent(StudPopulatorAgent, panel.core_layer, stud_spacing=625.0)
        return generate_flat(g)

    def test_produces_studs(self, elements):
        assert len(elements) > 0

    def test_all_elements_are_beam2d(self, elements):
        assert all(isinstance(e, Beam2D) for e in elements)

    def test_all_are_stud_category(self, elements):
        assert all(e.attributes.get("category") == "stud" for e in elements)

    def test_stud_height_equals_layer_thickness(self, elements):
        for e in elements:
            assert abs(e.height - 160.0) < 1.0

    def test_stud_width_equals_standard(self, elements):
        for e in elements:
            assert abs(e.width - 60.0) < 1.0

    def test_stud_count_matches_spacing(self, elements):
        assert 4 <= len(elements) <= 7

    def test_no_element_has_zero_length(self, elements):
        for e in elements:
            assert e.length > 0

    def test_fewer_studs_with_wider_spacing(self):
        panel = make_panel(width=4000.0, height=2700.0)

        g_narrow = make_agent(StudPopulatorAgent, panel.core_layer, stud_spacing=300.0)
        g_wide = make_agent(StudPopulatorAgent, panel.core_layer, stud_spacing=900.0)

        assert len(generate_flat(g_narrow)) > len(generate_flat(g_wide))


# =============================================================================
# PlatePopulatorAgent
# =============================================================================


class TestPlatePopulatorAgent:
    def test_interior_plate_produced(self):
        panel = make_panel(thickness=160.0, sheeting_inside=15.0)
        g = make_agent(PlatePopulatorAgent, panel.interior_layer)
        assert any(isinstance(e, Plate) for e in generate_flat(g))

    def test_exterior_plate_produced(self):
        panel = make_panel(thickness=160.0, sheeting_outside=22.0)
        g = make_agent(PlatePopulatorAgent, panel.exterior_layer)
        assert any(isinstance(e, Plate) for e in generate_flat(g))

    def test_both_plates_produced(self):
        panel = make_panel(thickness=160.0, sheeting_inside=15.0, sheeting_outside=22.0)
        g_i = make_agent(PlatePopulatorAgent, panel.interior_layer)
        g_e = make_agent(PlatePopulatorAgent, panel.exterior_layer)
        plates = [e for e in generate_flat(g_i) + generate_flat(g_e) if isinstance(e, Plate)]
        assert len(plates) == 2

    def test_no_sheeting_no_interior_exterior(self):
        panel = make_panel(thickness=160.0)
        assert panel.interior_layer is None
        assert panel.exterior_layer is None

    def test_plate_category(self):
        panel = make_panel(thickness=160.0, sheeting_inside=15.0)
        g = make_agent(PlatePopulatorAgent, panel.interior_layer)
        plates = [e for e in generate_flat(g) if isinstance(e, Plate)]
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
# Panel-level joint rules stay on the populator
# =============================================================================


class TestPanelLevelJointRules:
    """Rules given to the populator are held by it and never merged into an agent.

    They are a panel-wide *fallback*, tried by ``_join_cluster`` only after the
    owning agents' own rules have failed — so no agent's rule lists change when
    they are supplied.
    """

    def _pop(self, *agents, **kwargs):
        return PanelPopulator(panel=make_panel(), agents=list(agents), **kwargs)

    def test_none_gives_an_empty_list(self):
        pop = self._pop(EdgePopulatorAgent(None))
        assert pop.joint_rule_overrides == []

    def test_rules_are_kept_on_the_populator(self):
        rule = CategoryRule(LButtJoint, "edge_stud", "top_plate_beam", mill_depth=5.0)
        pop = self._pop(EdgePopulatorAgent(None), joint_rule_overrides=[rule])
        assert pop.joint_rule_overrides == [rule]

    def test_agent_rule_lists_are_untouched(self):
        """Even when one agent owns both of a rule's categories, its rule lists
        must be exactly what its own constructor produced."""
        edge = EdgePopulatorAgent(None)
        stud = StudPopulatorAgent(None)
        internal_before = {a: list(a.internal_rules) for a in (edge, stud)}
        external_before = {a: list(a.external_rules) for a in (edge, stud)}

        owned_rule = CategoryRule(LButtJoint, "edge_stud", "top_plate_beam", mill_depth=5.0)
        cross_rule = CategoryRule(TButtJoint, "stud", "top_plate_beam", mill_depth=10.0)
        self._pop(edge, stud, joint_rule_overrides=[owned_rule, cross_rule])

        for agent in (edge, stud):
            assert agent.internal_rules == internal_before[agent]
            assert agent.external_rules == external_before[agent]
            assert not agent.internal_overrides
            assert not agent.external_overrides

    def test_the_populator_list_is_a_copy(self):
        """Mutating the populator's list must not write back to the caller's."""
        rule = CategoryRule(LButtJoint, "edge_stud", "top_plate_beam")
        caller_list = [rule]
        pop = self._pop(EdgePopulatorAgent(None), joint_rule_overrides=caller_list)
        pop.joint_rule_overrides.append(CategoryRule(LButtJoint, "foo", "bar"))
        assert caller_list == [rule]

    def test_rules_reach_the_populator_via_stud_panel(self):
        """End-to-end: ``joint_rule_overrides`` passed to ``stud_panel()`` land on
        the populator, not in any agent's rule lists."""
        edge_rule = CategoryRule(LButtJoint, "edge_stud", "top_plate_beam", mill_depth=5.0)
        cross_rule = CategoryRule(TButtJoint, "stud", "top_plate_beam", mill_depth=10.0)

        pop = stud_panel(
            panel=make_panel(),
            standard_beam_width=60.0,
            stud_spacing=625.0,
            joint_rule_overrides=[edge_rule, cross_rule],
        )
        assert pop.joint_rule_overrides == [edge_rule, cross_rule]
        for agent in pop.agents:
            assert edge_rule not in agent.internal_rules
            assert edge_rule not in agent.external_rules
            assert cross_rule not in agent.internal_rules
            assert cross_rule not in agent.external_rules


# =============================================================================
# Per-agent joint-rule overrides
# =============================================================================


class TestJointRuleOverrides:
    def test_matching_override_replaces_default(self):
        override = CategoryRule(TButtJoint, "stud", "top_plate_beam", mill_depth=3.0)
        agent = StudPopulatorAgent(None, external_joint_overrides=[override])
        matching = [r for r in agent.external_rules if (r.category_a, r.category_b) == ("stud", "top_plate_beam")]
        assert matching == [override]
        assert len(agent.external_rules) == len(StudPopulatorAgent.EXTERNAL_JOINT_RULES)

    def test_override_for_new_pair_is_appended(self):
        override = CategoryRule(TButtJoint, "stud", "custom_beam")
        agent = StudPopulatorAgent(None, external_joint_overrides=[override])
        assert override in agent.external_rules
        assert len(agent.external_rules) == len(StudPopulatorAgent.EXTERNAL_JOINT_RULES) + 1

    def test_override_with_other_topology_is_appended(self):
        """The same category pair may carry one rule per topology."""
        override = CategoryRule(LButtJoint, "stud", "top_plate_beam")
        agent = StudPopulatorAgent(None, external_joint_overrides=[override])
        pair_rules = [r for r in agent.external_rules if (r.category_a, r.category_b) == ("stud", "top_plate_beam")]
        assert len(pair_rules) == 2
        assert override in pair_rules

    def test_class_defaults_not_mutated(self):
        before = list(StudPopulatorAgent.EXTERNAL_JOINT_RULES)
        StudPopulatorAgent(None, external_joint_overrides=[CategoryRule(TButtJoint, "stud", "custom_beam")])
        assert StudPopulatorAgent.EXTERNAL_JOINT_RULES == before


# =============================================================================
# Beam width validation
# =============================================================================


class TestBeamWidthValidation:
    def test_unset_width_raises_value_error(self):
        with pytest.raises(ValueError, match="stud"):
            StudPopulatorAgent(None).beam_width("stud")

    def test_unknown_category_raises_value_error(self):
        with pytest.raises(ValueError, match="header"):
            StudPopulatorAgent(None).beam_width("header")

    def test_generate_without_widths_raises_value_error(self):
        panel = make_panel()
        agent = EdgePopulatorAgent(panel.core_layer)
        agent.repoint_to_layer_tree({panel.core_layer.layer_path: panel.core_layer})
        with pytest.raises(ValueError, match="standard_beam_width"):
            agent.generate_elements()


# =============================================================================
# Agents passed to a populator are cloned, not mutated
# =============================================================================


class TestAgentCloning:
    def test_clone_keeps_construction_parameters(self):
        agent = StudPopulatorAgent("core", stud_width=45.0, stud_spacing=500.0)
        clone = agent.clone()
        assert clone is not agent
        assert type(clone) is StudPopulatorAgent
        assert clone.__data__ == agent.__data__

    def test_populator_does_not_mutate_caller_agents(self):
        stud = StudPopulatorAgent(None)
        pop = PanelPopulator(panel=make_panel(), agents=[stud], standard_beam_width=60.0)
        assert stud.beam_widths["stud"] is None
        assert pop.agents[0] is not stud
        assert pop.agents[0].beam_widths["stud"] == 60.0

    def test_shared_agent_across_populators_stays_independent(self):
        stud = StudPopulatorAgent(None)
        pop_a = PanelPopulator(panel=make_panel(), agents=[stud], standard_beam_width=60.0)
        pop_b = PanelPopulator(panel=make_panel(), agents=[stud], standard_beam_width=80.0)
        assert pop_a.agents[0].beam_widths["stud"] == 60.0
        assert pop_b.agents[0].beam_widths["stud"] == 80.0

    @requires_opening
    def test_stud_panel_does_not_mutate_instance_feature_agents(self):
        instance_agent = OpeningPopulatorAgent(element_layers=["foo"], trimming_layers=["bar"])
        stud_panel(panel=make_panel(sheeting_inside=15.0), standard_beam_width=60.0, instance_feature_configs=[instance_agent])
        assert instance_agent.element_layer_paths == ["foo"]
        assert instance_agent.trimming_layer_paths == ["bar"]

    @requires_opening
    def test_clone_shares_feature_reference(self):
        from compas_timber.panel_features import Opening
        from compas_timber.panel_features import OpeningType

        panel = make_panel()
        opening = Opening.from_outline_panel(make_outline(1000, 900, 2400, 2200), panel, opening_type=OpeningType.WINDOW)
        agent = OpeningPopulatorAgent(feature=opening)
        clone = agent.clone()
        assert clone.feature is opening
        assert type(clone) is type(agent)
