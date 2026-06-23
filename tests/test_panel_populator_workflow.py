"""Integration tests for the PanelPopulator workflow.

Two helpers define the test patterns:

* ``run_workflow(panel, **kwargs)`` — simple first-use helper: adds panel to a
  fresh model and runs the full population pipeline once.

* ``simulate_solve(panel, **kwargs)`` — matches the exact sequence CT_Model
  performs each Grasshopper solve: ``panel.reset()``, fresh ``TimberModel``,
  ``model.add_element(panel)``, then full pipeline.  Running this several
  times on the same panel object is the standard GH re-solve pattern and is
  the main scenario under test in ``TestMultiSolve``.

All geometry uses mm units.
"""

import pytest

from compas.geometry import Point
from compas.geometry import Polyline
from compas.geometry import Translation
from compas.geometry import Vector
from compas_timber.elements import Panel
from compas_timber.elements import Plate
from compas_timber.model import TimberModel

from timber_design.populators.populator_configs.recess_panel_config import recess_panel
from timber_design.populators.populator_configs.stud_panel_config import stud_panel
from timber_design.populators.beam2d import Beam2D

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
        Point(xmin, ymax, z),
        Point(xmax, ymax, z),
        Point(xmax, ymin, z),
        Point(xmin, ymin, z),
    ])


def make_panel(width=W, height=H, thickness=T):
    return Panel.from_outline_thickness(make_outline(0, 0, width, height), thickness)


# =============================================================================
# Workflow helpers
# =============================================================================


def run_workflow(panel, **stud_kwargs):
    """Run full stud_panel pipeline once on a freshly-added panel.

    Does NOT call ``panel.reset()`` — use ``simulate_solve`` when you need
    the exact GH re-solve sequence.
    """
    model = TimberModel()
    model.add_element(panel)
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
        3. model.add_element(panel)
        4. create populator (calls define_core_layer internally)
        5. populate_elements / join_elements / process_joinery / merge_with_model

    Run this on the same panel object multiple times to reproduce the
    multi-solve / stale-layer scenario.
    """
    model = TimberModel()
    panel.reset()
    model.add_element(panel)
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

    GH caches element objects between solves.  Each solve calls define_core_layer
    again, which must reuse existing Layer objects (not create new ones) so that
    agent layer references stay valid.
    """

    KWARGS = dict(standard_beam_width=60.0, stud_spacing=625.0)

    def test_three_consecutive_solves_do_not_raise(self):
        panel = make_panel()
        for _ in range(3):
            simulate_solve(panel, **self.KWARGS)

    def test_core_layer_object_preserved_on_second_solve(self):
        """define_core_layer must reuse the same Layer object when dimensions match."""
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
        panel = make_panel()
        for _ in range(3):
            simulate_solve(panel, standard_beam_width=60.0,
                           sheeting_inside=15.0, sheeting_outside=22.0)

    def test_recess_panel_multi_solve(self):
        panel = make_panel()
        for _ in range(3):
            simulate_solve(panel, config_fn=recess_panel,
                           standard_beam_width=60.0, recess_beam_width=40.0,
                           recess_beam_height=80.0)


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
        _, model = run_workflow(make_panel(), standard_beam_width=60.0, sheeting_inside=15.0)
        assert any(isinstance(e, Plate) for e in model.elements())

    def test_outside_plate_created(self):
        _, model = run_workflow(make_panel(), standard_beam_width=60.0, sheeting_outside=22.0)
        assert any(isinstance(e, Plate) for e in model.elements())

    def test_both_plates_when_both_specified(self):
        _, model = run_workflow(make_panel(), standard_beam_width=60.0,
                                sheeting_inside=15.0, sheeting_outside=22.0)
        plates = [e for e in model.elements() if isinstance(e, Plate)]
        assert len(plates) >= 2

    def test_stud_height_equals_frame_thickness(self):
        si, so = 15.0, 22.0
        _, model = run_workflow(make_panel(), standard_beam_width=60.0,
                                sheeting_inside=si, sheeting_outside=so)
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
        model.add_element(panel)
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
        model.add_element(panel)
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
            model.add_element(p)
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
# Recess panel
# =============================================================================


class TestRecessPanel:
    @pytest.fixture(scope="class")
    def recess_result(self):
        panel = make_panel()
        model = TimberModel()
        model.add_element(panel)
        pop = recess_panel(panel, standard_beam_width=60.0,
                           recess_beam_width=40.0, recess_beam_height=80.0)
        pop.populate_elements()
        pop.join_elements()
        pop.process_joinery()
        pop.merge_with_model(model)
        return model

    def test_recess_beams_created(self, recess_result):
        assert "recess" in categories(recess_result)

    def test_no_intermediate_studs(self, recess_result):
        assert "stud" not in categories(recess_result)

    def test_recess_beams_positive_width(self, recess_result):
        for beam in by_category(recess_result, "recess"):
            assert beam.width > 0


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
        model.add_element(panel)
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
        model.add_element(panel)
        pop = stud_panel(panel, standard_beam_width=60.0)
        pop.populate_elements()

    def test_internal_model_has_framing_after_populate(self):
        panel = make_panel()
        model = TimberModel()
        model.add_element(panel)
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
        model.add_element(panel)
        pop = stud_panel(panel, standard_beam_width=60.0, stud_spacing=625.0)
        pop.populate_elements()
        pop.join_elements()
        real = [j for j in pop.model.joints if not isinstance(j, JointCandidate)]
        assert len(real) > 0
