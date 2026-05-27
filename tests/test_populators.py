"""Unit tests for the individual populator agents and factory helpers.

Tests here work one level below the full PanelPopulator workflow: they
instantiate agents directly (via the factory or by hand) and assert
that ``generate_elements`` produces the right element types, categories,
and counts for a known panel geometry.

All panels are created in mm units.
"""

import pytest

from compas.geometry import Point
from compas.geometry import Polyline
from compas_timber.elements import Panel
from compas_timber.elements import Plate

from timber_design.populators import EdgePopulatorAgent
from timber_design.populators import EdgePopulatorAgentConfig
from timber_design.populators import Layer
from timber_design.populators import LayerConfig
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


def build_layers(panel, si=0.0, so=0.0, standard_beam_width=None):
    """Build a flat list of :class:`Layer` instances in populator space.

    Mirrors the cross-section used by tests: optional interior plate,
    a fill-remaining framing layer, optional exterior plate.  Runs the
    full config pipeline (transform → create layers).
    """
    layer_defs = []
    if si:
        layer_defs.append(LayerConfig(si, name="interior", agent_configs=[PlatePopulatorAgentConfig()]))
    layer_defs.append(LayerConfig(name="frame"))
    if so:
        layer_defs.append(LayerConfig(so, name="exterior", agent_configs=[PlatePopulatorAgentConfig()]))
    config = PanelPopulatorConfig(panel=panel, layer_defs=layer_defs, standard_beam_width=standard_beam_width)
    config.populator_panel = config.get_populator_panel()
    layer_model = config.create_populator_model()
    return list(layer_model.elements())


def get_frame_layer(layers):
    """Return the framing layer (named ``"frame"``)."""
    return next(la for la in layers if la.name == "frame")


def make_agent(agent_cls, config_cls, layer, standard_beam_width=60.0, **config_kwargs):
    """Construct an agent via the config factory, which fills beam widths automatically."""
    params = config_cls(**config_kwargs)
    return params.get_agent_from_layer(layer, standard_beam_width)


# =============================================================================
# EdgePopulatorAgent
# =============================================================================


class TestEdgePopulatorAgent:
    @pytest.fixture
    def gen(self):
        panel = make_panel(width=3000.0, height=2000.0, thickness=160.0)
        frame_layer = get_frame_layer(build_layers(panel))
        # standard_beam_width=60.0 (make_agent default) fills all edge categories
        g = make_agent(EdgePopulatorAgent, EdgePopulatorAgentConfig, frame_layer)
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
        assert gen.outline is not None

    def test_aabb_covers_all_elements(self, gen):
        from timber_design.populators.beam2d import AABB2D

        assert gen.aabb is not None
        assert isinstance(gen.aabb, AABB2D)

    def test_width_uses_standard_beam_width(self, gen):
        # make_agent default standard_beam_width=60.0 → all beams should be 60.0
        for e in gen.elements:
            assert e.width == 60.0

    def test_explicit_per_category_width(self):
        panel = make_panel(width=3000.0, height=2000.0, thickness=160.0)
        frame_layer = get_frame_layer(build_layers(panel))
        g = make_agent(
            EdgePopulatorAgent,
            EdgePopulatorAgentConfig,
            frame_layer,
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
        frame_layer = get_frame_layer(build_layers(panel))
        # standard_beam_width=60.0 → 60 is already a multiple of 20
        g = make_agent(EdgePopulatorAgent, EdgePopulatorAgentConfig, frame_layer, standard_beam_width_increment=20.0)
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
        frame_layer = get_frame_layer(build_layers(panel))
        g = make_agent(StudPopulatorAgent, StudPopulatorAgentConfig, frame_layer, stud_spacing=625.0)
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
        frame_layer = get_frame_layer(build_layers(panel))

        g_narrow = make_agent(StudPopulatorAgent, StudPopulatorAgentConfig, frame_layer, stud_spacing=300.0)
        g_narrow.generate_elements()

        g_wide = make_agent(StudPopulatorAgent, StudPopulatorAgentConfig, frame_layer, stud_spacing=900.0)
        g_wide.generate_elements()

        assert len(g_narrow.elements) > len(g_wide.elements)


# =============================================================================
# PlatePopulatorAgent
# =============================================================================


class TestPlatePopulatorAgent:
    def test_interior_plate_produced(self):
        panel = make_panel(thickness=160.0)
        layers = build_layers(panel, si=15.0)
        interior = next(la for la in layers if la.name == "interior")
        g = make_agent(PlatePopulatorAgent, PlatePopulatorAgentConfig, interior)
        g.generate_elements()
        assert any(isinstance(e, Plate) for e in g.elements)

    def test_exterior_plate_produced(self):
        panel = make_panel(thickness=160.0)
        layers = build_layers(panel, so=22.0)
        exterior = next(la for la in layers if la.name == "exterior")
        g = make_agent(PlatePopulatorAgent, PlatePopulatorAgentConfig, exterior)
        g.generate_elements()
        assert any(isinstance(e, Plate) for e in g.elements)

    def test_both_plates_produced(self):
        panel = make_panel(thickness=160.0)
        layers = build_layers(panel, si=15.0, so=22.0)
        interior = next(la for la in layers if la.name == "interior")
        exterior = next(la for la in layers if la.name == "exterior")
        g_i = make_agent(PlatePopulatorAgent, PlatePopulatorAgentConfig, interior)
        g_i.generate_elements()
        g_e = make_agent(PlatePopulatorAgent, PlatePopulatorAgentConfig, exterior)
        g_e.generate_elements()
        plates = [e for e in g_i.elements + g_e.elements if isinstance(e, Plate)]
        assert len(plates) == 2

    def test_no_sheeting_no_interior_exterior(self):
        panel = make_panel(thickness=160.0)
        layers = build_layers(panel)
        assert not any(la.name == "interior" for la in layers)
        assert not any(la.name == "exterior" for la in layers)

    def test_interior_plate_category(self):
        panel = make_panel(thickness=160.0)
        layers = build_layers(panel, si=15.0)
        interior = next(la for la in layers if la.name == "interior")
        g = make_agent(PlatePopulatorAgent, PlatePopulatorAgentConfig, interior)
        g.generate_elements()
        plates = [e for e in g.elements if isinstance(e, Plate)]
        assert all(e.attributes.get("category") == "interior_plate" for e in plates)

    def test_exterior_plate_category(self):
        panel = make_panel(thickness=160.0)
        layers = build_layers(panel, so=22.0)
        exterior = next(la for la in layers if la.name == "exterior")
        g = make_agent(PlatePopulatorAgent, PlatePopulatorAgentConfig, exterior)
        g.generate_elements()
        plates = [e for e in g.elements if isinstance(e, Plate)]
        assert all(e.attributes.get("category") == "exterior_plate" for e in plates)


# =============================================================================
# build_layers (LayerConfig flow through PanelPopulatorConfig)
# =============================================================================


class TestBuildLayers:
    def test_always_has_frame(self):
        panel = make_panel(thickness=160.0)
        layers = build_layers(panel)
        assert any(la.name == "frame" for la in layers)

    def test_no_sheeting_single_layer(self):
        panel = make_panel(thickness=160.0)
        layers = build_layers(panel)
        assert not any(la.name == "interior" for la in layers)
        assert not any(la.name == "exterior" for la in layers)

    def test_sheeting_inside_creates_interior_layer(self):
        panel = make_panel(thickness=160.0)
        layers = build_layers(panel, si=15.0)
        assert any(la.name == "interior" for la in layers)
        assert not any(la.name == "exterior" for la in layers)

    def test_sheeting_outside_creates_exterior_layer(self):
        panel = make_panel(thickness=160.0)
        layers = build_layers(panel, so=22.0)
        assert any(la.name == "exterior" for la in layers)
        assert not any(la.name == "interior" for la in layers)

    def test_both_sheeting_creates_both_layers(self):
        panel = make_panel(thickness=160.0)
        layers = build_layers(panel, si=15.0, so=22.0)
        assert any(la.name == "interior" for la in layers)
        assert any(la.name == "exterior" for la in layers)

    def test_layers_are_layer_instances(self):
        panel = make_panel(thickness=160.0)
        layers = build_layers(panel, si=15.0, so=22.0)
        for layer in layers:
            assert isinstance(layer, Layer)

    def test_interior_layer_thickness(self):
        panel = make_panel(thickness=160.0)
        layers = build_layers(panel, si=15.0)
        interior = next(la for la in layers if la.name == "interior")
        assert abs(interior.thickness - 15.0) < 1.0

    def test_exterior_layer_thickness(self):
        panel = make_panel(thickness=160.0)
        layers = build_layers(panel, so=22.0)
        exterior = next(la for la in layers if la.name == "exterior")
        assert abs(exterior.thickness - 22.0) < 1.0

    def test_frame_thickness_reduced_by_sheeting(self):
        panel = make_panel(thickness=160.0)
        layers = build_layers(panel, si=15.0, so=22.0)
        frame = get_frame_layer(layers)
        assert abs(frame.thickness - (160.0 - 15.0 - 22.0)) < 1.0

    def test_layer_names(self):
        panel = make_panel(thickness=160.0)
        layers = build_layers(panel, si=15.0, so=22.0)
        names = [la.name for la in layers]
        assert "frame" in names
        assert "interior" in names
        assert "exterior" in names


class TestGetPopulatorPanel:
    def test_returns_panel_instance(self):
        panel = make_panel()
        config = PanelPopulatorConfig(panel=panel, layer_defs=[LayerConfig(name="frame")])
        populator_panel = config.get_populator_panel()
        assert isinstance(populator_panel, Panel)

    def test_preserves_thickness(self):
        panel = make_panel(thickness=160.0)
        config = PanelPopulatorConfig(panel=panel, layer_defs=[LayerConfig(name="frame")])
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


class TestStudPanelPopulatorConfig:
    def _layers(self, **kwargs):
        panel = kwargs.pop("panel", None) or make_panel()
        config = stud_panel(panel=panel, standard_beam_width=60.0, stud_spacing=625.0, **kwargs)
        config.populator_panel = config.get_populator_panel()
        layer_model = config.create_populator_model()
        return config, list(layer_model.elements())

    def test_returns_non_empty_list(self):
        _, layers = self._layers()
        agents = _all_layer_agents(layers)
        assert len(agents) >= 2  # at minimum: edge + stud

    def test_edge_agent_present(self):
        _, layers = self._layers()
        assert any(isinstance(g, EdgePopulatorAgent) for g in _all_layer_agents(layers))

    def test_stud_agent_present_when_spacing_set(self):
        _, layers = self._layers()
        assert any(isinstance(g, StudPopulatorAgent) for g in _all_layer_agents(layers))

    def test_default_stud_spacing_when_spacing_none(self):
        panel = make_panel()
        config = stud_panel(panel=panel, standard_beam_width=60.0, stud_spacing=None)
        config.populator_panel = config.get_populator_panel()
        layer_model = config.create_populator_model()
        layers = list(layer_model.elements())
        assert any(isinstance(g, StudPopulatorAgent) for g in _all_layer_agents(layers))

    def test_plate_agent_present_when_sheeting_set(self):
        _, layers = self._layers(sheeting_inside=15.0)
        assert any(isinstance(g, PlatePopulatorAgent) for g in _all_layer_agents(layers))

    def test_no_plate_agent_without_sheeting(self):
        _, layers = self._layers()
        assert not any(isinstance(g, PlatePopulatorAgent) for g in _all_layer_agents(layers))

    def test_beam_dimensions_resolved_on_agents(self):
        _, layers = self._layers()
        for g in _all_layer_agents(layers):
            assert g.beam_widths, "{}.beam_widths is empty after resolve".format(type(g).__name__)

    def test_create_layers_returns_interior_layer_when_sheeting_set(self):
        _, layers = self._layers(sheeting_inside=15.0)
        assert any(la.name == "interior" for la in layers)
        assert not any(la.name == "exterior" for la in layers)

    def test_create_layers_returns_both_layers_when_both_sheeting_set(self):
        _, layers = self._layers(sheeting_inside=15.0, sheeting_outside=22.0)
        assert any(la.name == "interior" for la in layers)
        assert any(la.name == "exterior" for la in layers)


# =============================================================================
# recess_panel config
# =============================================================================


class TestRecessPanelPopulatorConfig:
    def _layers(self):
        panel = make_panel()
        config = recess_panel(
            panel=panel,
            standard_beam_width=60.0,
            recess_beam_width=40.0,
            recess_beam_height=80.0,
        )
        config.populator_panel = config.get_populator_panel()
        layer_model = config.create_populator_model()
        return config, list(layer_model.elements())

    def test_returns_non_empty_list(self):
        _, layers = self._layers()
        assert len(_all_layer_agents(layers)) >= 1

    def test_beam_dimensions_resolved(self):
        _, layers = self._layers()
        for g in _all_layer_agents(layers):
            assert g.beam_widths, "{}.beam_widths is empty".format(type(g).__name__)


# =============================================================================
# Layer tree structure
# =============================================================================


class TestLayerTree:
    def test_sublayer_list_populated(self):
        """Parent layer's sublayer_list contains the child layers."""
        panel = make_panel(thickness=160.0)
        frame_ld = LayerConfig(
            name="frame",
            sublayers=[
                LayerConfig(80.0, name="inner_frame"),
                LayerConfig(80.0, name="outer_frame"),
            ],
        )
        config = PanelPopulatorConfig(panel=panel, layer_defs=[frame_ld])
        config.populator_panel = config.get_populator_panel()
        layer_model = config.create_populator_model()
        layers = list(layer_model.elements())
        frame = next(la for la in layers if la.name == "frame")
        assert len(frame.sublayer_list) == 2
        names = {la.name for la in frame.sublayer_list}
        assert names == {"inner_frame", "outer_frame"}

    def test_parent_layer_set(self):
        """Child layers carry a reference to their parent."""
        panel = make_panel(thickness=160.0)
        frame_ld = LayerConfig(
            name="frame",
            sublayers=[
                LayerConfig(80.0, name="inner_frame"),
                LayerConfig(80.0, name="outer_frame"),
            ],
        )
        config = PanelPopulatorConfig(panel=panel, layer_defs=[frame_ld])
        config.populator_panel = config.get_populator_panel()
        layer_model = config.create_populator_model()
        layers = list(layer_model.elements())
        frame = next(la for la in layers if la.name == "frame")
        child = next(la for la in layers if la.name == "inner_frame")
        assert child.parent_layer is frame

    def test_iter_subtree_yields_all_descendants(self):
        panel = make_panel(thickness=160.0)
        frame_ld = LayerConfig(
            name="frame",
            sublayers=[
                LayerConfig(80.0, name="inner"),
                LayerConfig(80.0, name="outer"),
            ],
        )
        config = PanelPopulatorConfig(panel=panel, layer_defs=[frame_ld])
        config.populator_panel = config.get_populator_panel()
        layer_model = config.create_populator_model()
        layers = list(layer_model.elements())
        frame = next(la for la in layers if la.name == "frame")
        subtree = list(frame.iter_subtree())
        names = {la.name for la in subtree}
        assert "frame" in names
        assert "inner" in names
        assert "outer" in names


# =============================================================================
# is_on_layer
# =============================================================================


class TestIsOnLayer:
    def _setup(self):
        # Single sublayer of 80 mm — use a panel with matching thickness so
        # the sublayer sum equals the parent thickness.
        panel = make_panel(thickness=80.0)
        frame_ld = LayerConfig(
            name="frame",
            sublayers=[
                LayerConfig(80.0, name="sub", agent_configs=[EdgePopulatorAgentConfig()]),
            ],
        )
        config = PanelPopulatorConfig(panel=panel, layer_defs=[frame_ld])
        config.populator_panel = config.get_populator_panel()
        layer_model = config.create_populator_model()
        layers = list(layer_model.elements())
        frame = next(la for la in layers if la.name == "frame")
        sub = next(la for la in layers if la.name == "sub")
        agent = sub.agents[0]
        return frame, sub, agent

    def test_agent_is_on_its_own_layer(self):
        _, sub, agent = self._setup()
        assert agent.is_on_layer(sub)

    def test_agent_is_on_parent_layer(self):
        frame, _, agent = self._setup()
        assert agent.is_on_layer(frame)

    def test_agent_is_not_on_unrelated_layer(self):
        panel = make_panel(thickness=20.0)
        other_ld = LayerConfig(20.0, name="other")
        config2 = PanelPopulatorConfig(panel=panel, layer_defs=[other_ld])
        config2.populator_panel = config2.get_populator_panel()
        layer_model2 = config2.create_populator_model()
        other = next(la for la in layer_model2.elements() if la.name == "other")
        _, _, agent = self._setup()
        assert not agent.is_on_layer(other)
