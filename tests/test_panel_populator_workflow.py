"""Integration tests for the PanelPopulator workflow.

Two helpers define the test patterns:

* ``run_workflow(panel, **kwargs)`` — simple first-use helper: adds panel to a
  fresh model and runs the full population pipeline once.

* ``simulate_solve(panel, **kwargs)`` — matches the exact sequence CT_Model
  performs each Grasshopper solve: ``panel.reset()``, fresh ``TimberModel``,
  ``add_panel(model, panel)``, then full pipeline.  Running this several
  times on the same panel object is the standard GH re-solve pattern and is
  the main scenario under test in ``TestMultiSolve``.

All geometry uses mm units.
"""

import pytest

from compas.geometry import Point
from compas.geometry import Polyline
from compas.geometry import Translation
from compas.geometry import Vector
from compas_timber.connections import LButtJoint
from compas_timber.connections import TButtJoint
from compas_timber.elements import LayerDefinition
from compas_timber.elements import LayerStructure
from compas_timber.elements import Panel
from compas_timber.elements import Plate
from compas_timber.model import TimberModel

from timber_design.populators.populator_configs.stud_panel_config import stud_panel
from timber_design.connections_2d.beam2d import Beam2D

try:
    from compas_timber.panel_features.opening import Opening
    from compas_timber.panel_features.opening import OpeningType
    HAS_OPENING = True
except ImportError:
    HAS_OPENING = False

requires_opening = pytest.mark.skipif(not HAS_OPENING, reason="Opening not available in installed compas_timber")

W = 4000.0
H = 2700.0
T = 160.0


# =============================================================================
# Geometry helpers
# =============================================================================


def make_outline(xmin, ymin, xmax, ymax, z=0.0):
    return Polyline([
        Point(xmin, ymin, z),
        Point(xmax, ymin, z),
        Point(xmax, ymax, z),
        Point(xmin, ymax, z),
        Point(xmin, ymin, z),
    ])


def make_panel(width=W, height=H, thickness=T, sheeting_inside=0.0, sheeting_outside=0.0):
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


# =============================================================================
# Workflow helpers
# =============================================================================


def add_panel(model, panel):
    """Add *panel* to *model* together with its layer_structure's Layer children.

    ``model.add_element(panel)`` alone does not bring the panel's layers into
    the model tree, so ``panel.core_layer`` / ``exterior_layer`` /
    ``interior_layer`` resolve to ``None`` until ``merge_layer_structure`` runs.
    """
    model.add_element(panel)
    panel.merge_layer_structure(model)


def run_workflow(panel, **stud_kwargs):
    """Run full stud_panel pipeline once on a freshly-added panel.

    Does NOT call ``panel.reset()`` — use ``simulate_solve`` when you need
    the exact GH re-solve sequence.
    """
    model = TimberModel()
    add_panel(model, panel)
    pop = stud_panel(panel, **stud_kwargs)
    pop.populate_elements()
    pop.join_elements()
    pop.process_joinery()
    pop.merge_with_model(model)
    return pop, model


def simulate_solve(panel, config_fn=stud_panel, **kwargs):
    """Simulate one Grasshopper CT_Model solve on *panel*.

    Sequence mirrors CT_Model.RunScript exactly:
        1. Fresh TimberModel
        2. panel.reset()
        3. add_panel(model, panel)
        4. create populator from the panel's existing layer_structure
        5. populate_elements / join_elements / process_joinery / merge_with_model

    Run this on the same panel object multiple times to reproduce the
    multi-solve / stale-layer scenario.
    """
    model = TimberModel()
    panel.reset()
    add_panel(model, panel)
    pop = config_fn(panel, **kwargs)
    pop.populate_elements()
    pop.join_elements()
    pop.process_joinery()
    pop.merge_with_model(model)
    return model


# =============================================================================
# Query helpers
# =============================================================================


def categories(model):
    return {e.attributes.get("category") for e in model.elements()
            if hasattr(e, "attributes") and e.attributes.get("category")}


def by_category(model, cat):
    return [e for e in model.elements()
            if hasattr(e, "attributes") and e.attributes.get("category") == cat]


def framing_count(model):
    return sum(1 for e in model.elements()
               if hasattr(e, "attributes") and e.attributes.get("category"))


# =============================================================================
# Multi-solve (GH re-solve) — THE KEY REGRESSION TESTS
# =============================================================================


class TestMultiSolve:
    """Simulate multiple Grasshopper solves on the same Panel object.

    GH caches element objects between solves.  Each solve must reuse the
    panel's existing ``core_layer`` / ``exterior_layer`` / ``interior_layer``
    objects (not create new ones) so that agent layer references stay valid.
    """

    KWARGS = dict(standard_beam_width=60.0, stud_spacing=625.0)

    def test_three_consecutive_solves_do_not_raise(self):
        panel = make_panel()
        for _ in range(3):
            simulate_solve(panel, **self.KWARGS)

    def test_core_layer_object_preserved_on_second_solve(self):
        """The panel's core_layer object must be reused across solves."""
        panel = make_panel()
        simulate_solve(panel, **self.KWARGS)
        layer_after_first = panel.core_layer
        simulate_solve(panel, **self.KWARGS)
        assert panel.core_layer is layer_after_first, (
            "panel.core_layer was replaced with a new object on the second solve; "
            "this will break any agent that captured the first-solve reference"
        )

    def test_element_count_identical_across_solves(self):
        panel = make_panel()
        counts = []
        for _ in range(3):
            m = simulate_solve(panel, **self.KWARGS)
            counts.append(framing_count(m))
        assert counts[0] == counts[1] == counts[2], (
            f"Framing element counts differ across solves: {counts}"
        )

    def test_stud_category_present_on_every_solve(self):
        panel = make_panel()
        for i in range(3):
            m = simulate_solve(panel, **self.KWARGS)
            assert "stud" in categories(m), f"No studs on solve {i + 1}"

    def test_multi_solve_with_sheeting(self):
        """Sheathing layers (exterior/interior) must also survive re-solve."""
        panel = make_panel(sheeting_inside=15.0, sheeting_outside=22.0)
        for _ in range(3):
            simulate_solve(panel, standard_beam_width=60.0)


# =============================================================================
# Basic stud wall (single solve)
# =============================================================================


class TestBasicStudWall:
    @pytest.fixture(scope="class")
    def result(self):
        _, model = run_workflow(make_panel(), standard_beam_width=60.0, stud_spacing=625.0)
        return model

    def test_produces_elements(self, result):
        assert len(list(result.elements())) > 0

    def test_top_plate_present(self, result):
        assert "top_plate_beam" in categories(result)

    def test_bottom_plate_present(self, result):
        assert "bottom_plate_beam" in categories(result)

    def test_edge_studs_present(self, result):
        assert "edge_stud" in categories(result)

    def test_intermediate_studs_present(self, result):
        assert "stud" in categories(result)

    def test_stud_count_reasonable(self, result):
        """4000 mm panel / 625 mm spacing ≈ 5 intermediate studs."""
        studs = by_category(result, "stud")
        assert 4 <= len(studs) <= 7

    def test_framing_elements_are_beam2d(self, result):
        beam_cats = {"top_plate_beam", "bottom_plate_beam", "edge_stud", "stud"}
        for e in result.elements():
            if hasattr(e, "attributes") and e.attributes.get("category") in beam_cats:
                assert isinstance(e, Beam2D)

    def test_all_beams_positive_length(self, result):
        for e in result.elements():
            if isinstance(e, Beam2D):
                assert e.length > 0


# =============================================================================
# Edge-only wall (stud_spacing=0)
# =============================================================================


class TestEdgeOnlyWall:
    def test_no_studs_when_spacing_zero(self):
        _, model = run_workflow(make_panel(), standard_beam_width=60.0, stud_spacing=0)
        assert "stud" not in categories(model)

    def test_plates_still_created(self):
        _, model = run_workflow(make_panel(), standard_beam_width=60.0, stud_spacing=0)
        cats = categories(model)
        assert "top_plate_beam" in cats
        assert "bottom_plate_beam" in cats

    def test_none_spacing_produces_studs(self):
        _, model = run_workflow(make_panel(), standard_beam_width=60.0, stud_spacing=None)
        assert "stud" in categories(model)


# =============================================================================
# Sheathing plates
# =============================================================================


class TestSheathing:
    def test_inside_plate_created(self):
        _, model = run_workflow(make_panel(sheeting_inside=15.0), standard_beam_width=60.0)
        assert any(isinstance(e, Plate) for e in model.elements())

    def test_outside_plate_created(self):
        _, model = run_workflow(make_panel(sheeting_outside=22.0), standard_beam_width=60.0)
        assert any(isinstance(e, Plate) for e in model.elements())

    def test_both_plates_when_both_specified(self):
        _, model = run_workflow(make_panel(sheeting_inside=15.0, sheeting_outside=22.0),
                                standard_beam_width=60.0)
        plates = [e for e in model.elements() if isinstance(e, Plate)]
        assert len(plates) >= 2

    def test_stud_height_equals_frame_thickness(self):
        si, so = 15.0, 22.0
        _, model = run_workflow(make_panel(sheeting_inside=si, sheeting_outside=so),
                                standard_beam_width=60.0)
        frame_t = T - si - so
        for stud in by_category(model, "stud"):
            assert abs(stud.height - frame_t) < 1.0


# =============================================================================
# Repopulation (clear_panel=True)
# =============================================================================


class TestRepopulation:
    """Running the full pipeline twice on the same panel must not duplicate framing."""

    def test_repopulation_same_count(self):
        panel = make_panel()

        # Reference: single run
        _, ref_model = run_workflow(make_panel(), standard_beam_width=60.0, stud_spacing=625.0)
        ref_count = framing_count(ref_model)

        # Double run with clear_panel=True (simulate GH re-solve)
        model = TimberModel()
        add_panel(model, panel)
        for _ in range(2):
            pop = stud_panel(panel, standard_beam_width=60.0, stud_spacing=625.0)
            pop.populate_elements()
            pop.join_elements()
            pop.process_joinery()
            pop.merge_with_model(model, clear_panel=True)

        assert framing_count(model) == ref_count

    def test_three_solves_same_count_as_one(self):
        panel = make_panel()
        _, ref = run_workflow(make_panel(), standard_beam_width=60.0, stud_spacing=625.0)
        ref_count = framing_count(ref)

        model = TimberModel()
        add_panel(model, panel)
        for _ in range(3):
            pop = stud_panel(panel, standard_beam_width=60.0, stud_spacing=625.0)
            pop.populate_elements()
            pop.join_elements()
            pop.process_joinery()
            pop.merge_with_model(model, clear_panel=True)

        assert framing_count(model) == ref_count


# =============================================================================
# Multi-panel workflow
# =============================================================================


class TestMultiPanelWorkflow:
    @pytest.fixture(scope="class")
    def result(self):
        model = TimberModel()
        panels = []
        for i in range(3):
            p = make_panel()
            p.transform(Translation.from_vector(Vector(0, 0, i * (T + 10.0))))
            add_panel(model, p)
            panels.append(p)
        for p in panels:
            pop = stud_panel(p, standard_beam_width=60.0, stud_spacing=625.0)
            pop.populate_elements()
            pop.join_elements()
            pop.process_joinery()
            pop.merge_with_model(model)
        return model, panels

    def test_model_contains_framing(self, result):
        model, _ = result
        assert "stud" in categories(model)

    def test_stud_count_scales_with_panels(self, result):
        model, _ = result
        _, single = run_workflow(make_panel(), standard_beam_width=60.0, stud_spacing=625.0)
        assert len(by_category(model, "stud")) == 3 * len(by_category(single, "stud"))


# =============================================================================
# Window / door openings
# =============================================================================


@requires_opening
class TestWindowOpening:
    @pytest.fixture(scope="class")
    def result(self):
        from timber_design.populators import OpeningPopulatorAgent

        panel = make_panel()
        opening = Opening.from_outline_panel(
            make_outline(1000, 900, 2400, 2200), panel, opening_type=OpeningType.WINDOW
        )
        panel.add_feature(opening)
        model = TimberModel()
        add_panel(model, panel)
        pop = stud_panel(
            panel,
            standard_beam_width=60.0,
            stud_spacing=625.0,
            default_feature_configs={Opening: OpeningPopulatorAgent(
                element_layers=[panel.core_layer],
                trimming_layers=[panel.core_layer],
            )},
        )
        pop.populate_elements()
        pop.join_elements()
        pop.process_joinery()
        pop.merge_with_model(model)
        return model

    def test_header_created(self, result):
        assert "header" in categories(result)

    def test_sill_created(self, result):
        assert "sill" in categories(result)

    def test_two_king_studs(self, result):
        assert len(by_category(result, "king_stud")) == 2


@requires_opening
class TestDoorOpening:
    @pytest.fixture(scope="class")
    def result(self):
        from timber_design.populators import DoorPopulatorAgent
        from timber_design.populators import OpeningPopulatorAgent

        panel = make_panel()
        opening = Opening.from_outline_panel(
            make_outline(1000, 0, 2200, 2200), panel, opening_type=OpeningType.DOOR
        )
        panel.add_feature(opening)
        model = TimberModel()
        add_panel(model, panel)
        pop = stud_panel(
            panel,
            standard_beam_width=60.0,
            stud_spacing=625.0,
            default_feature_configs={Opening: OpeningPopulatorAgent(
                element_layers=[panel.core_layer],
                trimming_layers=[panel.core_layer],
            )},
        )
        pop.populate_elements()
        pop.join_elements()
        pop.process_joinery()
        pop.merge_with_model(model)
        opening_agents = [a for a in pop.agents if isinstance(a, OpeningPopulatorAgent)]
        assert len(opening_agents) == 1
        assert isinstance(opening_agents[0], DoorPopulatorAgent)
        return model

    def test_header_created(self, result):
        assert "header" in categories(result)

    def test_no_sill(self, result):
        assert "sill" not in categories(result)

    def test_two_king_studs(self, result):
        assert len(by_category(result, "king_stud")) == 2


@requires_opening
class TestOpeningAgentDispatch:
    """A single, unbound ``OpeningPopulatorAgent`` prototype must self-dispatch
    to :class:`DoorPopulatorAgent` / :class:`WindowPopulatorAgent` once bound
    to a concrete feature, since :class:`~compas_timber.panel_features.Opening`
    is shared by both opening types."""

    def _make_opening(self, opening_type):
        panel = make_panel()
        return Opening.from_outline_panel(make_outline(1000, 0, 2200, 2200), panel, opening_type=opening_type)

    def test_binding_door_dispatches_to_door_subclass(self):
        from timber_design.populators import DoorPopulatorAgent, OpeningPopulatorAgent

        agent = OpeningPopulatorAgent()
        agent.feature = self._make_opening(OpeningType.DOOR)
        assert isinstance(agent, DoorPopulatorAgent)

    def test_binding_window_dispatches_to_window_subclass(self):
        from timber_design.populators import OpeningPopulatorAgent, WindowPopulatorAgent

        agent = OpeningPopulatorAgent()
        agent.feature = self._make_opening(OpeningType.WINDOW)
        assert isinstance(agent, WindowPopulatorAgent)

    def test_explicit_subclass_is_not_redispatched(self):
        from timber_design.populators import DoorPopulatorAgent

        agent = DoorPopulatorAgent()
        agent.feature = self._make_opening(OpeningType.WINDOW)
        assert isinstance(agent, DoorPopulatorAgent)


@requires_opening
class TestSplitBottomPlateBeam:
    """Regression tests for the ``split_bottom_plate_beam`` door option.

    The (king_stud/jack_stud, bottom_plate_beam) joint is between elements
    owned by two different agents (the bottom plate belongs to the edge
    agent), so it is resolved via ``external_rules`` — not ``internal_rules``.
    """

    def _make_door_agent(self, split_bottom_plate_beam, lintel_posts=False):
        from timber_design.populators import OpeningPopulatorAgent

        opening = self._make_opening()
        agent = OpeningPopulatorAgent(
            feature=opening,
            header_width=60.0,
            king_stud_width=60.0,
            jack_stud_width=60.0,
            lintel_posts=lintel_posts,
            split_bottom_plate_beam=split_bottom_plate_beam,
        )
        agent._apply_split_bottom_plate_rules()
        return agent

    def _make_opening(self):
        panel = make_panel()
        return Opening.from_outline_panel(make_outline(1000, 0, 2200, 2200), panel, opening_type=OpeningType.DOOR)

    def _bottom_plate_rule(self, agent, category_a):
        # Excludes the unrelated "HACK" corner rule (max_distance=1.0) also
        # registered for this category pair; the split-mode rule is unrestricted.
        matching = [
            r for r in agent.external_rules
            if r.category_a == category_a and r.category_b == "bottom_plate_beam" and r.max_distance is None
        ]
        assert len(matching) == 1
        return matching[0]

    def test_split_bottom_plate_beam_true_swaps_to_l_butt(self):
        agent = self._make_door_agent(split_bottom_plate_beam=True)
        assert self._bottom_plate_rule(agent, "king_stud").joint_type is LButtJoint

    def test_split_bottom_plate_beam_false_keeps_t_butt(self):
        agent = self._make_door_agent(split_bottom_plate_beam=False)
        assert self._bottom_plate_rule(agent, "king_stud").joint_type is TButtJoint

    def test_split_bottom_plate_beam_targets_jack_stud_with_lintel_posts(self):
        agent = self._make_door_agent(split_bottom_plate_beam=True, lintel_posts=True)
        assert self._bottom_plate_rule(agent, "jack_stud").joint_type is LButtJoint


# =============================================================================
# Robustness
# =============================================================================


class TestRobustness:
    def test_narrow_panel_no_error(self):
        panel = make_panel(width=500.0)
        _, model = run_workflow(panel, standard_beam_width=60.0, stud_spacing=625.0)
        assert "top_plate_beam" in categories(model)

    def test_wide_panel_many_studs(self):
        panel = make_panel(width=10000.0)
        _, model = run_workflow(panel, standard_beam_width=60.0, stud_spacing=625.0)
        assert len(by_category(model, "stud")) > 10

    def test_thin_panel(self):
        panel = make_panel(thickness=50.0)
        _, model = run_workflow(panel, standard_beam_width=40.0)
        assert model is not None

    def test_populate_only_does_not_raise(self):
        panel = make_panel()
        model = TimberModel()
        add_panel(model, panel)
        pop = stud_panel(panel, standard_beam_width=60.0)
        pop.populate_elements()

    def test_internal_model_has_framing_after_populate(self):
        panel = make_panel()
        model = TimberModel()
        add_panel(model, panel)
        pop = stud_panel(panel, standard_beam_width=60.0, stud_spacing=625.0)
        pop.populate_elements()
        internal_cats = {e.attributes.get("category") for e in pop.model.elements()
                         if hasattr(e, "attributes")}
        assert "stud" in internal_cats


# =============================================================================
# Joint creation
# =============================================================================


class TestJointCreation:
    def test_joints_created(self):
        from compas_timber.connections import JointCandidate

        panel = make_panel()
        model = TimberModel()
        add_panel(model, panel)
        pop = stud_panel(panel, standard_beam_width=60.0, stud_spacing=625.0)
        pop.populate_elements()
        pop.join_elements()
        real = [j for j in pop.model.joints if not isinstance(j, JointCandidate)]
        assert len(real) > 0
