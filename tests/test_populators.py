"""Unit tests for the individual populator agents and factory helpers.

Tests here work one level below the full PanelPopulator workflow: they
instantiate agents directly (via the factory or by hand) and assert
that ``generate_elements`` produces the right element types, categories,
and counts for a known panel geometry.

All panels are created with ``Panel.from_outline_thickness`` in mm units.
"""

import pytest

from compas.geometry import Point
from compas.geometry import Polyline
from compas_timber.elements import Panel
from compas_timber.elements import Plate

from timber_design.populators import EdgePopulatorAgent
from timber_design.populators import EdgePopulatorAgentConfig
from timber_design.populators import PlatePopulatorAgent
from timber_design.populators import PlatePopulatorAgentConfig
from timber_design.populators import RecessPanelPopulatorConfig
from timber_design.populators import StudPopulatorAgent
from timber_design.populators import StudPopulatorAgentConfig
from timber_design.populators import StudPanelPopulatorConfig
from timber_design.populators.beam2d import Beam2D
from timber_design.populators import get_frame_panel


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


def make_panel(width=4000.0, height=2700.0, thickness=160.0):
    return Panel.from_outline_thickness(make_outline(0, 0, width, height), thickness)


class _SheetingParams:
    """Minimal stand-in for factory params used only by get_frame_panel."""

    def __init__(self, si=0.0, so=0.0, thickness=160.0):
        self.sheeting_inside = si
        self.sheeting_outside = so
        self.thickness = thickness


# =============================================================================
# EdgePopulatorAgent
# =============================================================================


class TestEdgePopulatorAgent:
    @pytest.fixture
    def gen(self):
        panel = make_panel(width=3000.0, height=2000.0, thickness=160.0)
        frame_panel = get_frame_panel(panel, _SheetingParams())
        params = EdgePopulatorAgentConfig(edge_beam_min_width=60.0)
        g = EdgePopulatorAgent(frame_panel, params)
        g.resolve_beam_dimensions(frame_panel.thickness, standard_beam_width=60.0)
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
        """Edge agent sets its outline (used for trimming by other agents)."""
        assert gen.outline is not None

    def test_aabb_covers_all_elements(self, gen):
        from timber_design.populators.beam2d import AABB2D

        assert gen.aabb is not None
        assert isinstance(gen.aabb, AABB2D)

    def test_width_respects_standard(self, gen):
        """All edge beams must be at least the min width."""
        for e in gen.elements:
            assert e.width >= 60.0

    def test_standard_width_increment_rounds_up(self):
        """With an increment, edge-beam widths snap to the next multiple."""
        panel = make_panel()
        frame_panel = get_frame_panel(panel, _SheetingParams())
        params = EdgePopulatorAgentConfig(edge_beam_min_width=0.0, standard_beam_width_increment=20.0)
        g = EdgePopulatorAgent(frame_panel, params)
        g.resolve_beam_dimensions(frame_panel.thickness, standard_beam_width=60.0)
        g.generate_elements()
        for e in g.elements:
            # width must be a multiple of 20 (or ≥ the increment)
            assert e.width % 20.0 < 1.0 or e.width >= 60.0


# =============================================================================
# StudPopulatorAgent
# =============================================================================


class TestStudPopulatorAgent:
    @pytest.fixture
    def gen(self):
        panel = make_panel(width=4000.0, height=2700.0, thickness=160.0)
        frame_panel = get_frame_panel(panel, _SheetingParams())
        params = StudPopulatorAgentConfig(stud_spacing=625.0)
        g = StudPopulatorAgent(frame_panel, params)
        g.resolve_beam_dimensions(frame_panel.thickness, standard_beam_width=60.0)
        g.generate_elements()
        return g

    def test_produces_studs(self, gen):
        assert len(gen.elements) > 0

    def test_all_elements_are_beam2d(self, gen):
        assert all(isinstance(e, Beam2D) for e in gen.elements)

    def test_all_are_stud_category(self, gen):
        assert all(e.attributes.get("category") == "stud" for e in gen.elements)

    def test_stud_height_equals_panel_thickness(self, gen):
        for e in gen.elements:
            assert abs(e.height - 160.0) < 1.0

    def test_stud_width_equals_standard(self, gen):
        for e in gen.elements:
            assert abs(e.width - 60.0) < 1.0

    def test_stud_count_matches_spacing(self, gen):
        """4000 mm ÷ 625 mm spacing → between 4 and 7 intermediate studs."""
        assert 4 <= len(gen.elements) <= 7

    def test_no_element_has_zero_length(self, gen):
        for e in gen.elements:
            assert e.length > 0

    def test_fewer_studs_with_wider_spacing(self):
        panel = make_panel(width=4000.0, height=2700.0)
        frame_panel = get_frame_panel(panel, _SheetingParams())

        g_narrow = StudPopulatorAgent(frame_panel, StudPopulatorAgentConfig(stud_spacing=300.0))
        g_narrow.resolve_beam_dimensions(160.0, 60.0)
        g_narrow.generate_elements()

        g_wide = StudPopulatorAgent(frame_panel, StudPopulatorAgentConfig(stud_spacing=900.0))
        g_wide.resolve_beam_dimensions(160.0, 60.0)
        g_wide.generate_elements()

        assert len(g_narrow.elements) > len(g_wide.elements)


# =============================================================================
# PlatePopulatorAgent
# =============================================================================


class TestPlatePopulatorAgent:
    def test_inside_plate_produced(self):
        panel = make_panel(thickness=160.0)
        frame_panel = get_frame_panel(panel, _SheetingParams(si=15.0))
        params = PlatePopulatorAgentConfig(sheeting_inside=15.0)
        g = PlatePopulatorAgent(panel, frame_panel, params)
        g.resolve_beam_dimensions(frame_panel.thickness, standard_beam_width=60.0)
        g.generate_elements()
        assert any(isinstance(e, Plate) for e in g.elements)

    def test_outside_plate_produced(self):
        panel = make_panel(thickness=160.0)
        frame_panel = get_frame_panel(panel, _SheetingParams(so=22.0))
        params = PlatePopulatorAgentConfig(sheeting_outside=22.0)
        g = PlatePopulatorAgent(panel, frame_panel, params)
        g.resolve_beam_dimensions(frame_panel.thickness, standard_beam_width=60.0)
        g.generate_elements()
        assert any(isinstance(e, Plate) for e in g.elements)

    def test_both_plates_produced(self):
        panel = make_panel(thickness=160.0)
        frame_panel = get_frame_panel(panel, _SheetingParams(si=15.0, so=22.0))
        params = PlatePopulatorAgentConfig(sheeting_inside=15.0, sheeting_outside=22.0)
        g = PlatePopulatorAgent(panel, frame_panel, params)
        g.resolve_beam_dimensions(frame_panel.thickness, standard_beam_width=60.0)
        g.generate_elements()
        plates = [e for e in g.elements if isinstance(e, Plate)]
        assert len(plates) >= 2

    def test_no_plates_without_sheeting(self):
        panel = make_panel(thickness=160.0)
        frame_panel = get_frame_panel(panel, _SheetingParams())
        params = PlatePopulatorAgentConfig()
        g = PlatePopulatorAgent(panel, frame_panel, params)
        g.resolve_beam_dimensions(frame_panel.thickness, standard_beam_width=60.0)
        g.generate_elements()
        plates = [e for e in g.elements if isinstance(e, Plate)]
        assert len(plates) == 0


# =============================================================================
# get_frame_panel helper
# =============================================================================


class TestGetFramePanel:
    def test_no_sheeting_returns_same_size(self):
        panel = make_panel(thickness=160.0)
        frame_panel = get_frame_panel(panel, _SheetingParams())
        assert abs(frame_panel.thickness - 160.0) < 1.0

    def test_sheeting_reduces_frame_thickness(self):
        panel = make_panel(thickness=160.0)
        frame_panel = get_frame_panel(panel, _SheetingParams(si=15.0, so=22.0))
        assert abs(frame_panel.thickness - (160.0 - 15.0 - 22.0)) < 1.0

    def test_returns_panel_instance(self):
        panel = make_panel()
        frame_panel = get_frame_panel(panel, _SheetingParams())
        assert isinstance(frame_panel, Panel)


# =============================================================================
# StudPanelPopulatorConfig.create_populator_agents
# =============================================================================


class TestStudPanelPopulatorConfig:
    """Config creates the expected agent types for standard params."""

    def test_returns_non_empty_list(self):
        panel = make_panel()
        config = StudPanelPopulatorConfig(standard_beam_width=60.0, stud_spacing=625.0)
        agents, _ = config.create_populator_agents(panel)
        assert isinstance(agents, list)
        assert len(agents) >= 2  # at minimum: edge + stud

    def test_edge_agent_present(self):
        panel = make_panel()
        config = StudPanelPopulatorConfig(standard_beam_width=60.0, stud_spacing=625.0)
        agents, _ = config.create_populator_agents(panel)
        assert any(isinstance(g, EdgePopulatorAgent) for g in agents)

    def test_stud_agent_present_when_spacing_set(self):
        panel = make_panel()
        config = StudPanelPopulatorConfig(standard_beam_width=60.0, stud_spacing=625.0)
        agents, _ = config.create_populator_agents(panel)
        assert any(isinstance(g, StudPopulatorAgent) for g in agents)

    def test_no_stud_agent_when_spacing_none(self):
        panel = make_panel()
        config = StudPanelPopulatorConfig(standard_beam_width=60.0, stud_spacing=None)
        agents, _ = config.create_populator_agents(panel)
        assert not any(isinstance(g, StudPopulatorAgent) for g in agents)

    def test_plate_agent_present_when_sheeting_set(self):
        panel = make_panel()
        config = StudPanelPopulatorConfig(standard_beam_width=60.0, stud_spacing=625.0, sheeting_inside=15.0)
        agents, _ = config.create_populator_agents(panel)
        assert any(isinstance(g, PlatePopulatorAgent) for g in agents)

    def test_no_plate_agent_without_sheeting(self):
        panel = make_panel()
        config = StudPanelPopulatorConfig(standard_beam_width=60.0, stud_spacing=625.0)
        agents, _ = config.create_populator_agents(panel)
        assert not any(isinstance(g, PlatePopulatorAgent) for g in agents)

    def test_beam_dimensions_resolved_on_agents(self):
        """create_populator_agents returns a frame_panel suitable for resolving beam dimensions."""
        panel = make_panel()
        config = StudPanelPopulatorConfig(standard_beam_width=60.0, stud_spacing=625.0)
        agents, frame_panel = config.create_populator_agents(panel)
        for g in agents:
            g.resolve_beam_dimensions(frame_panel.thickness, config.standard_beam_width)
        for g in agents:
            assert g.beam_dimensions, f"{type(g).__name__}.beam_dimensions is empty after resolve"

    def test_all_agents_have_feature(self):
        panel = make_panel()
        config = StudPanelPopulatorConfig(standard_beam_width=60.0, stud_spacing=625.0)
        agents, _ = config.create_populator_agents(panel)
        for g in agents:
            assert g.feature is not None


# =============================================================================
# RecessPanelPopulatorConfig.create_populator_agents
# =============================================================================


class TestRecessPanelPopulatorConfig:
    def test_returns_non_empty_list(self):
        panel = make_panel()
        config = RecessPanelPopulatorConfig(
            standard_beam_width=60.0,
            recess_beam_width=40.0,
            recess_beam_height=80.0,
            edge_beam_min_width=60.0,
        )
        agents, _ = config.create_populator_agents(panel)
        assert isinstance(agents, list)
        assert len(agents) >= 1

    def test_beam_dimensions_resolved(self):
        """resolve_beam_dimensions is called by create_populator; simulate it here."""
        panel = make_panel()
        config = RecessPanelPopulatorConfig(
            standard_beam_width=60.0,
            recess_beam_width=40.0,
            recess_beam_height=80.0,
            edge_beam_min_width=60.0,
        )
        agents, frame_panel = config.create_populator_agents(panel)
        for g in agents:
            g.resolve_beam_dimensions(frame_panel.thickness, config.standard_beam_width)
        for g in agents:
            assert g.beam_dimensions
