import copy

from compas_timber.panel_features import Opening

from timber_design.populators import PanelPopulator
from timber_design.populators.populator_agents.edge_populator_agent import EdgePopulatorAgent
from timber_design.populators.populator_agents.opening_populator_agent import OpeningPopulatorAgent
from timber_design.populators.populator_agents.plate_populator_agent import PlatePopulatorAgent
from timber_design.populators.populator_agents.stud_populator_agent import StudPopulatorAgent


def stud_panel(
    panel=None,
    standard_beam_width=None,
    # Stud agent
    stud_spacing=None,
    stud_width=None,
    # Edge agent
    edge_stud_width=None,
    top_plate_beam_width=None,
    bottom_plate_beam_width=None,
    standard_beam_width_increment=None,
    # Panel-level
    joint_rule_overrides=None,
    default_feature_configs=None,
    instance_feature_configs=None,
):
    """Create a config for a standard stud-framed wall panel.

    If the panel already owns layers (set via ``CT_Panel_Layer_Definition``),
    those layers are used directly: the exterior and interior sheeting layers
    receive :class:`~timber_design.populators.PlatePopulatorAgent`s and the
    core layer receives the framing agents.  If the panel has no layers, a
    single core layer spanning the full panel thickness is created and no
    sheeting plates are generated.

    Parameters
    ----------
    panel : :class:`compas_timber.elements.Panel`
        The panel to populate.
    standard_beam_width : float, optional
        Default width for every framing beam category not given an explicit
        width below.
    stud_spacing : float, optional
        On-centre spacing between studs.  ``None`` → ``stud_width * 8``.
        ``0`` → no studs.
    stud_width : float, optional
        Explicit width for intermediate stud beams.
    edge_stud_width : float, optional
        Explicit width for vertical edge studs.
    top_plate_beam_width : float, optional
        Explicit width for top plate beams.
    bottom_plate_beam_width : float, optional
        Explicit width for bottom plate beams.
    standard_beam_width_increment : float, optional
        Rounding increment for edge-beam widths.
    joint_rule_overrides : list, optional
        Joint-rule overrides routed to the agents that own each rule's categories.
    default_feature_configs : dict, optional
        Mapping from panel feature class to a ``FeatureAgent`` prototype.
    instance_feature_configs : list, optional
        Per-instance feature agents, already bound to specific features.
    """

    if not panel.layers:
        panel.define_core_layer(0, panel.thickness)

    agents = []
    if panel.exterior_layer:
        agents.append(PlatePopulatorAgent(panel.exterior_layer))
    if panel.interior_layer:
        agents.append(PlatePopulatorAgent(panel.interior_layer))

    agents.append(EdgePopulatorAgent(
        panel.core_layer,
        standard_beam_width_increment=standard_beam_width_increment,
        edge_stud_width=edge_stud_width,
        top_plate_beam_width=top_plate_beam_width,
        bottom_plate_beam_width=bottom_plate_beam_width,
    ))

    if stud_spacing is None or stud_spacing:
        agents.append(StudPopulatorAgent(
            panel.core_layer,
            stud_width=stud_width,
            stud_spacing=stud_spacing,
        ))

    trimming_layers = [la for la in (panel.exterior_layer, panel.core_layer, panel.interior_layer) if la]

    # Build a fresh dict so we don't mutate the caller's mapping when GH (or
    # any caller) reuses the same dict across multiple panels.
    default_feature_configs = dict(default_feature_configs) if default_feature_configs else {}
    if Opening not in default_feature_configs:
        default_feature_configs[Opening] = OpeningPopulatorAgent(
            element_layer_paths=[panel.core_layer],
            trimming_layer_paths=trimming_layers,
        )
    else:
        # The user-supplied prototype may be a single instance shared across
        # multiple stud_panel() calls (e.g. one CT_FeatureAgentConfig output
        # wired into a CT_StudPanel component that processes a list of panels).
        # Shallow-copy it so each call binds its own layer references.
        prototype = copy.copy(default_feature_configs[Opening])
        prototype.element_layer_paths = [(1,)]
        prototype.trimming_layer_paths = [(0,),(1,),(2,)]
        default_feature_configs[Opening] = prototype

    # Instance feature agents are already feature-bound; add them directly.
    # Always update element_layers and trimming_layers: define_core_layer creates
    # new Layer objects each call, so any previously-stored refs would be stale.
    if instance_feature_configs:
        for agent in instance_feature_configs:
            agent.element_layer_paths = [(1,)]
            agent.trimming_layer_paths = [(0,),(1,),(2,)]
        agents.extend(instance_feature_configs)

    return PanelPopulator(
        panel=panel,
        standard_beam_width=standard_beam_width,
        agents=agents,
        default_feature_agents=default_feature_configs,
        joint_rule_overrides=joint_rule_overrides,
    )
