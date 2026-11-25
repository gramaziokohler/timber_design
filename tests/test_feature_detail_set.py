"""Tests for PanelFeature.detail_set: every feature is built by exactly one set, its own or the populator's default for its type."""

import pytest

from compas.data import json_dumps
from compas.data import json_loads
from compas.geometry import Frame
from compas.geometry import Point
from compas.geometry import Polyline
from compas_timber.elements import Beam

from compas_arch.elements import LayerDefinition
from compas_arch.elements import LayerStructure
from compas_arch.elements import Panel
from compas_arch.model import ArchModel
from compas_arch.panel_features import LinearService
from compas_arch.panel_features import Opening
from compas_arch.panel_features import OpeningType

from timber_design_populator import EdgeAgent
from timber_design_populator import LayerCutDetailAgent
from timber_design_populator import LinearServiceDetailSet
from timber_design_populator import PanelPopulator
from timber_design_populator import PlateAgent
from timber_design_populator import ServiceDrillingDetailAgent
from timber_design_populator import ServiceNotchDetailAgent
from timber_design_populator import VoidFramingDetailAgent
from timber_design_populator import stud_panel
from timber_design_populator.detail_sets import FramedNicheDetailSet
from timber_design_populator.detail_sets import FramedOpeningDetailSet

STANDARD = 60.0
# what a FramedOpeningDetailSet expands into on a wall with exterior, core and interior: framing + a cut per layer
OPENING_AGENTS = [VoidFramingDetailAgent, LayerCutDetailAgent, LayerCutDetailAgent, LayerCutDetailAgent]


def _outline(xmin, ymin, xmax, ymax, z=0.0):
    return Polyline([Point(xmin, ymin, z), Point(xmax, ymin, z), Point(xmax, ymax, z), Point(xmin, ymax, z), Point(xmin, ymin, z)])


def _panel():
    panel = Panel.from_outline_thickness(_outline(0, 0, 4000, 2700), 200.0)
    panel.layer_structure = LayerStructure([LayerDefinition("exterior", 20.0), LayerDefinition("core"), LayerDefinition("interior", 20.0)])
    return panel


def _window(panel, detail_set=None):
    return Opening.from_outline_panel(_outline(1000, 900, 2200, 2100), panel, opening_type=OpeningType.WINDOW, detail_set=detail_set)


def _model(panel):
    model = ArchModel()
    model.add_element(panel)
    panel.merge_layer_structure(model)
    return model


def _populate(pop, model):
    pop.populate_elements()
    pop.join_elements()
    pop.process_joinery()
    pop.merge_with_model(model)
    return model


def _beams(model, category):
    return [e for e in model.elements() if isinstance(e, Beam) and e.attributes.get("category") == category]


def _agents_for(pop, feature):
    return [a for a in pop.agents if getattr(a, "feature", None) is feature]


# =============================================================================
# carried agents vs the populator's defaults
# =============================================================================


def test_a_feature_without_a_detail_set_gets_the_default_for_its_type():
    panel = _panel()
    window = _window(panel)
    panel.add_feature(window)
    model = _model(panel)
    pop = stud_panel(panel, standard_beam_width=STANDARD, stud_spacing=625.0)
    _populate(pop, model)

    assert [type(a) for a in _agents_for(pop, window)] == OPENING_AGENTS
    headers = _beams(model, "header")
    assert headers and all(beam.width == STANDARD for beam in headers)


def test_a_features_detail_set_replaces_the_default():
    panel = _panel()
    window = _window(panel, detail_set=FramedOpeningDetailSet(header_width=200.0))
    panel.add_feature(window)
    model = _model(panel)
    pop = stud_panel(panel, standard_beam_width=STANDARD, stud_spacing=625.0)
    _populate(pop, model)

    agents = _agents_for(pop, window)
    assert [type(a) for a in agents] == OPENING_AGENTS
    headers = _beams(model, "header")
    assert headers and all(beam.width == 200.0 for beam in headers)


def test_a_features_detail_set_works_without_any_populator_defaults():
    panel = _panel()
    window = _window(panel, detail_set=FramedOpeningDetailSet())
    panel.add_feature(window)
    model = _model(panel)
    pop = PanelPopulator(panel, agents=[EdgeAgent(panel.core_layer)], standard_beam_width=STANDARD)
    _populate(pop, model)
    assert _beams(model, "header")


def test_a_detail_set_for_another_feature_type_is_reported_and_skipped():
    panel = _panel()
    window = _window(panel, detail_set=FramedNicheDetailSet())
    panel.add_feature(window)
    model = _model(panel)
    pop = stud_panel(panel, standard_beam_width=STANDARD, stud_spacing=625.0)
    _populate(pop, model)

    assert _agents_for(pop, window) == []  # the feature's own set replaces the default, even when it is skipped
    messages = [e.message for e in pop.debug_info.feature_errors]
    assert any("builds Niche features, not Opening" in m for m in messages)


def test_a_detail_agent_is_not_accepted_as_a_panel_wide_agent():
    panel = _panel()
    window = _window(panel)
    panel.add_feature(window)
    model = _model(panel)
    bound = VoidFramingDetailAgent(feature=window)
    pop = PanelPopulator(panel, agents=[EdgeAgent(panel.core_layer), bound], standard_beam_width=STANDARD)
    _populate(pop, model)

    assert not any(isinstance(a, VoidFramingDetailAgent) for a in pop.agents)
    assert any("is a detail agent" in e.message for e in pop.debug_info.feature_errors)


def test_a_features_detail_set_survives_the_model_copy():
    """CT: Populate Model populates a JSON copy of the model; the copy's features carry their own sets."""
    panel = _panel()
    panel.add_feature(_window(panel, detail_set=FramedOpeningDetailSet(header_width=200.0)))
    model = _model(panel)
    pop = stud_panel(panel, standard_beam_width=STANDARD, stud_spacing=625.0)

    copy = json_loads(json_dumps(model))
    pop.update_panel_from_model(copy)
    _populate(pop, copy)
    copied_window = [f for f in pop.panel.features if isinstance(f, Opening)][0]
    assert copied_window is not panel.features[0]
    assert [type(a) for a in _agents_for(pop, copied_window)] == OPENING_AGENTS
    assert all(beam.width == 200.0 for beam in _beams(copy, "header"))


# =============================================================================
# linear services: the set chooses the agent and its inputs
# =============================================================================


def _service_agents(mode=None):
    panel = _panel()
    service = LinearService(Frame.worldXY(), Polyline([Point(100, 100, 100), Point(500, 200, 100)]), 20)
    service.detail_set = LinearServiceDetailSet() if mode is None else LinearServiceDetailSet(mode=mode)
    panel.add_feature(service)
    model = _model(panel)
    pop = PanelPopulator(panel, agents=[], standard_beam_width=STANDARD)
    _populate(pop, model)
    return panel, _agents_for(pop, pop.panel.features[0])


def test_linear_services_are_drilled_by_default_and_only_machine_the_core():
    panel, (agent,) = _service_agents()
    assert type(agent) is ServiceDrillingDetailAgent
    assert agent.element_layer_paths == [] and agent.trimming_layer_paths == [panel.layer_structure.get_path_for_role("core")]
    assert agent.diameter == 20


def test_notching_mode_notches_from_the_interior():
    panel, (agent,) = _service_agents("notching")
    assert type(agent) is ServiceNotchDetailAgent
    assert agent.trimming_layer_paths == [panel.layer_structure.get_path_for_role("core")]
    assert agent.side is not None


def test_an_unknown_service_mode_is_refused():
    with pytest.raises(ValueError):
        LinearServiceDetailSet(mode="sawing")


# =============================================================================
# agents: layer shorthand and priority
# =============================================================================


def test_layer_is_shorthand_for_element_and_trimming_layers():
    path = (1,)
    short, long = PlateAgent(layer=path), PlateAgent(element_layers=[path], trimming_layers=[path])
    assert short.element_layer_paths == long.element_layer_paths == [path]
    assert short.trimming_layer_paths == long.trimming_layer_paths == [path]


def test_priority_defaults_to_the_class_and_can_be_overridden():
    assert EdgeAgent((1,)).priority == EdgeAgent.PRIORITY
    assert PlateAgent((1,), priority=7).priority == 7
    assert PlateAgent((1,), priority=7).clone().priority == 7


# =============================================================================
# serialization
# =============================================================================


def test_a_features_detail_set_serializes():
    panel = _panel()
    window = _window(panel, detail_set=FramedOpeningDetailSet(header_width=200.0, cut_offsets={"exterior": 20.0}))
    copied = json_loads(json_dumps(window))
    assert type(copied.detail_set) is FramedOpeningDetailSet
    assert copied.detail_set.header_width == 200.0
    assert copied.detail_set.cut_offsets == {"exterior": 20.0}
