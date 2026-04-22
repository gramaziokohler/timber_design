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
from timber_design.populators import Layer
from timber_design.populators import LayerDefinition
from timber_design.populators import PanelPopulatorConfig
from timber_design.populators import PlatePopulatorAgent
from timber_design.populators import PlatePopulatorAgentConfig
from timber_design.populators import StudPopulatorAgent
from timber_design.populators import StudPopulatorAgentConfig
from timber_design.populators.beam2d import Beam2D
from timber_design.populators.populator_configs.recess_panel_config import recess_panel
from timber_design.populators.populator_configs.stud_panel_config import stud_panel


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


def build_layers(panel, si=0.0, so=0.0):
    """Build a layer list matching the old ``get_layers`` helper.

    Mirrors the cross-section used by the previous test suite:
    optional interior plate, a framing layer (fill-remaining), optional
    exterior plate.  Returns the resolved list of :class:`Layer` instances
    in populator space, as produced by
    :meth:`PanelPopulatorConfig.create_layers`.
    """
    layer_defs = []
    if si:
        layer_defs.append(LayerDefinition(si, name="interior", agent_configs=[PlatePopulatorAgentConfig()]))
    layer_defs.append(LayerDefinition(name="frame", is_framing_layer=True))
    if so:
        layer_defs.append(LayerDefinition(so, name="exterior", agent_configs=[PlatePopulatorAgentConfig()]))
    config = PanelPopulatorConfig(panel=panel, layer_defs=layer_defs)
    populator_panel = config.get_populator_panel()
    return config.create_layers(populator_panel)


def frame_panel_of(layers):
    """Return the framing layer's panel (populator-space)."""
    return next(fl for fl in layers if fl.is_framing_layer).panel


# =============================================================================
# EdgePopulatorAgent
# =============================================================================


class TestEdgePopulatorAgent:
    @pytest.fixture
    def gen(self):
        panel = make_panel(width=3000.0, height=2000.0, thickness=160.0)
        frame_layer = next(fl for fl in build_layers(panel) if fl.is_framing_layer)
        params = EdgePopulatorAgentConfig(edge_beam_min_width=60.0)
        g = EdgePopulatorAgent(frame_layer, params)
        g.resolve_beam_dimensions(60.0, frame_layer.thickness)
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
        frame_layer = next(fl for fl in build_layers(panel) if fl.is_framing_layer)
        params = EdgePopulatorAgentConfig(edge_beam_min_width=0.0, standard_beam_width_increment=20.0)
        g = EdgePopulatorAgent(frame_layer, params)
        g.resolve_beam_dimensions(60.0, frame_layer.thickness)
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
        frame_layer = next(fl for fl in build_layers(panel) if fl.is_framing_layer)
        params = StudPopulatorAgentConfig(stud_spacing=625.0)
        g = StudPopulatorAgent(frame_layer, params)
        g.resolve_beam_dimensions(60.0, frame_layer.thickness)
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
        frame_layer = next(fl for fl in build_layers(panel) if fl.is_framing_layer)

        g_narrow = StudPopulatorAgent(frame_layer, StudPopulatorAgentConfig(stud_spacing=300.0))
        g_narrow.resolve_beam_dimensions(60.0, frame_layer.thickness)
        g_narrow.generate_elements()

        g_wide = StudPopulatorAgent(frame_layer, StudPopulatorAgentConfig(stud_spacing=900.0))
        g_wide.resolve_beam_dimensions(60.0, frame_layer.thickness)
        g_wide.generate_elements()

        assert len(g_narrow.elements) > len(g_wide.elements)


# =============================================================================
# PlatePopulatorAgent
# =============================================================================


class TestPlatePopulatorAgent:
    def test_interior_plate_produced(self):
        panel = make_panel(thickness=160.0)
        layers = build_layers(panel, si=15.0)
        interior = next(il for il in layers if il.name == "interior")
        frame = frame_panel_of(layers)
        g = PlatePopulatorAgent(interior, PlatePopulatorAgentConfig())
        g.resolve_beam_dimensions(60.0, frame.thickness)
        g.generate_elements()
        assert any(isinstance(e, Plate) for e in g.elements)

    def test_exterior_plate_produced(self):
        panel = make_panel(thickness=160.0)
        layers = build_layers(panel, so=22.0)
        exterior = next(el for el in layers if el.name == "exterior")
        frame = frame_panel_of(layers)
        g = PlatePopulatorAgent(exterior, PlatePopulatorAgentConfig())
        g.resolve_beam_dimensions(60.0, frame.thickness)
        g.generate_elements()
        assert any(isinstance(e, Plate) for e in g.elements)

    def test_both_plates_produced(self):
        panel = make_panel(thickness=160.0)
        layers = build_layers(panel, si=15.0, so=22.0)
        interior = next(il for il in layers if il.name == "interior")
        exterior = next(el for el in layers if el.name == "exterior")
        frame = frame_panel_of(layers)
        g_interior = PlatePopulatorAgent(interior, PlatePopulatorAgentConfig())
        g_interior.resolve_beam_dimensions(60.0, frame.thickness)
        g_interior.generate_elements()
        g_exterior = PlatePopulatorAgent(exterior, PlatePopulatorAgentConfig())
        g_exterior.resolve_beam_dimensions(60.0, frame.thickness)
        g_exterior.generate_elements()
        plates = [e for e in g_interior.elements + g_exterior.elements if isinstance(e, Plate)]
        assert len(plates) == 2

    def test_no_plates_without_sheeting(self):
        panel = make_panel(thickness=160.0)
        layers = build_layers(panel)
        assert not any(il.name == "interior" for il in layers)
        assert not any(el.name == "exterior" for el in layers)

    def test_interior_plate_category(self):
        """Plate element carries the layer-derived category name."""
        panel = make_panel(thickness=160.0)
        layers = build_layers(panel, si=15.0)
        interior = next(il for il in layers if il.name == "interior")
        frame = frame_panel_of(layers)
        g = PlatePopulatorAgent(interior, PlatePopulatorAgentConfig())
        g.resolve_beam_dimensions(60.0, frame.thickness)
        g.generate_elements()
        plates = [e for e in g.elements if isinstance(e, Plate)]
        assert all(e.attributes.get("category") == "interior_plate" for e in plates)

    def test_exterior_plate_category(self):
        panel = make_panel(thickness=160.0)
        layers = build_layers(panel, so=22.0)
        exterior = next(el for el in layers if el.name == "exterior")
        frame = frame_panel_of(layers)
        g = PlatePopulatorAgent(exterior, PlatePopulatorAgentConfig())
        g.resolve_beam_dimensions(60.0, frame.thickness)
        g.generate_elements()
        plates = [e for e in g.elements if isinstance(e, Plate)]
        assert all(e.attributes.get("category") == "exterior_plate" for e in plates)


# =============================================================================
# build_layers (LayerDefinition flow through PanelPopulatorConfig)
# =============================================================================


class TestBuildLayers:
    def test_always_has_frame(self):
        panel = make_panel(thickness=160.0)
        layers = build_layers(panel)
        assert any(fl.is_framing_layer for fl in layers)

    def test_no_sheeting_no_interior_exterior(self):
        panel = make_panel(thickness=160.0)
        layers = build_layers(panel)
        assert not any(il.name == "interior" for il in layers)
        assert not any(el.name == "exterior" for el in layers)

    def test_sheeting_inside_creates_interior_layer(self):
        panel = make_panel(thickness=160.0)
        layers = build_layers(panel, si=15.0)
        assert any(il.name == "interior" for il in layers)
        assert not any(el.name == "exterior" for el in layers)

    def test_sheeting_outside_creates_exterior_layer(self):
        panel = make_panel(thickness=160.0)
        layers = build_layers(panel, so=22.0)
        assert any(el.name == "exterior" for el in layers)
        assert not any(il.name == "interior" for il in layers)

    def test_both_sheeting_creates_both_layers(self):
        panel = make_panel(thickness=160.0)
        layers = build_layers(panel, si=15.0, so=22.0)
        assert any(il.name == "interior" for il in layers)
        assert any(el.name == "exterior" for el in layers)

    def test_layers_are_layer_instances(self):
        panel = make_panel(thickness=160.0)
        layers = build_layers(panel, si=15.0, so=22.0)
        for layer in layers:
            assert isinstance(layer, Layer)

    def test_interior_layer_thickness(self):
        panel = make_panel(thickness=160.0)
        layers = build_layers(panel, si=15.0)
        interior = next(il for il in layers if il.name == "interior")
        assert abs(interior.thickness - 15.0) < 1.0

    def test_exterior_layer_thickness(self):
        panel = make_panel(thickness=160.0)
        layers = build_layers(panel, so=22.0)
        exterior = next(el for el in layers if el.name == "exterior")
        assert abs(exterior.thickness - 22.0) < 1.0

    def test_frame_thickness_reduced_by_sheeting(self):
        panel = make_panel(thickness=160.0)
        layers = build_layers(panel, si=15.0, so=22.0)
        frame = next(fl for fl in layers if fl.is_framing_layer)
        assert abs(frame.thickness - (160.0 - 15.0 - 22.0)) < 1.0

    def test_layer_names(self):
        panel = make_panel(thickness=160.0)
        layers = build_layers(panel, si=15.0, so=22.0)
        names = [la.name for la in layers]
        assert "frame" in names
        assert "interior" in names
        assert "exterior" in names


class TestGetPopulatorPanel:
    """``PanelPopulatorConfig.get_populator_panel`` produces the localized panel."""

    def test_returns_panel_instance(self):
        panel = make_panel()
        config = PanelPopulatorConfig(panel=panel, layer_defs=[LayerDefinition(name="frame", is_framing_layer=True)])
        populator_panel = config.get_populator_panel()
        assert isinstance(populator_panel, Panel)

    def test_preserves_thickness(self):
        panel = make_panel(thickness=160.0)
        config = PanelPopulatorConfig(panel=panel, layer_defs=[LayerDefinition(name="frame", is_framing_layer=True)])
        populator_panel = config.get_populator_panel()
        assert abs(populator_panel.thickness - 160.0) < 1.0


# =============================================================================
# stud_panel config: layer.agents composition
# =============================================================================


def _all_layer_agents(layers):
    """Flat, deduplicated list of every agent on every layer."""
    seen = []
    for layer in layers:
        for agent in layer.agents:
            if agent not in seen:
                seen.append(agent)
    return seen


def _resolve_agent_dims(layers, standard_beam_width):
    """Simulate ``PanelPopulatorConfig.resolve_beam_dimensions`` for raw tests."""
    for layer in layers:
        for agent in layer.agents:
            agent.resolve_beam_dimensions(standard_beam_width, layer.thickness)


class TestStudPanelPopulatorConfig:
    """``stud_panel`` creates the expected agent types for standard params."""

    def _layers(self, **kwargs):
        panel = kwargs.pop("panel", None) or make_panel()
        config = stud_panel(standard_beam_width=60.0, stud_spacing=625.0, **kwargs)
        config.panel = panel
        populator_panel = config.get_populator_panel()
        return config, config.create_layers(populator_panel)

    def test_returns_non_empty_list(self):
        _, layers = self._layers()
        agents = _all_layer_agents(layers)
        assert isinstance(agents, list)
        assert len(agents) >= 2  # at minimum: edge + stud

    def test_edge_agent_present(self):
        _, layers = self._layers()
        agents = _all_layer_agents(layers)
        assert any(isinstance(g, EdgePopulatorAgent) for g in agents)

    def test_stud_agent_present_when_spacing_set(self):
        _, layers = self._layers()
        agents = _all_layer_agents(layers)
        assert any(isinstance(g, StudPopulatorAgent) for g in agents)

    def test_no_stud_agent_when_spacing_none(self):
        panel = make_panel()
        config = stud_panel(standard_beam_width=60.0, stud_spacing=None)
        config.panel = panel
        populator_panel = config.get_populator_panel()
        layers = config.create_layers(populator_panel)
        agents = _all_layer_agents(layers)
        assert not any(isinstance(g, StudPopulatorAgent) for g in agents)

    def test_plate_agent_present_when_sheeting_set(self):
        _, layers = self._layers(sheeting_inside=15.0)
        agents = _all_layer_agents(layers)
        assert any(isinstance(g, PlatePopulatorAgent) for g in agents)

    def test_no_plate_agent_without_sheeting(self):
        _, layers = self._layers()
        agents = _all_layer_agents(layers)
        assert not any(isinstance(g, PlatePopulatorAgent) for g in agents)

    def test_beam_dimensions_resolved_on_agents(self):
        """Dimensions resolve per-layer for every agent attached to a layer."""
        config, layers = self._layers()
        _resolve_agent_dims(layers, config.standard_beam_width)
        for g in _all_layer_agents(layers):
            assert g.beam_dimensions, f"{type(g).__name__}.beam_dimensions is empty after resolve"

    def test_create_layers_returns_interior_layer_when_sheeting_set(self):
        _, layers = self._layers(sheeting_inside=15.0)
        assert any(il.name == "interior" for il in layers)
        assert not any(el.name == "exterior" for el in layers)

    def test_create_layers_returns_both_layers_when_both_sheeting_set(self):
        _, layers = self._layers(sheeting_inside=15.0, sheeting_outside=22.0)
        assert any(il.name == "interior" for il in layers)
        assert any(el.name == "exterior" for el in layers)


# =============================================================================
# PanelPopulatorConfig.recess_panel / layer.agents composition
# =============================================================================


class TestRecessPanelPopulatorConfig:
    def _layers(self):
        panel = make_panel()
        config = recess_panel(
            standard_beam_width=60.0,
            recess_beam_width=40.0,
            recess_beam_height=80.0,
            edge_beam_min_width=60.0,
        )
        config.panel = panel
        populator_panel = config.get_populator_panel()
        return config, config.create_layers(populator_panel)

    def test_returns_non_empty_list(self):
        _, layers = self._layers()
        agents = _all_layer_agents(layers)
        assert isinstance(agents, list)
        assert len(agents) >= 1

    def test_beam_dimensions_resolved(self):
        """Simulate ``PanelPopulatorConfig.resolve_beam_dimensions``."""
        config, layers = self._layers()
        _resolve_agent_dims(layers, config.standard_beam_width)
        for g in _all_layer_agents(layers):
            assert g.beam_dimensions
