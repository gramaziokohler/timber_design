from __future__ import annotations

from compas_timber.panel_features import Opening

from compas_timber_populator.populator import PanelPopulator
from compas_timber_populator.populator_agents.edge_populator_agent import EdgePopulatorAgent
from compas_timber_populator.populator_agents.opening_populator_agent import OpeningPopulatorAgent
from compas_timber_populator.populator_agents.plate_populator_agent import PlatePopulatorAgent
from compas_timber_populator.populator_agents.stud_populator_agent import StudPopulatorAgent


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
    max_distance=None,
):
    """Create a config for a standard stud-framed wall panel.

    Uses the panel's layers named ``"exterior"``, ``"core"`` and ``"interior"``
    (see :class:`~compas_timber.elements.LayerStructure`): the exterior and
    interior layers, when present, each receive a
    :class:`~compas_timber_populator.PlatePopulatorAgent` and the core layer
    receives the framing agents.  A panel without a ``layer_structure`` has a
    single full-thickness ``"core"`` layer, so only framing is generated.

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
        Panel-level joint rules held by the populator.  They are tried on a
        cluster only after the owning agents' own rules have failed, so they
        act as a panel-wide fallback rather than overriding an agent.
    default_feature_configs : dict, optional
        Mapping from panel feature class to a ``FeatureAgent`` prototype.
    instance_feature_configs : list, optional
        Per-instance feature agents, already bound to specific features.
    max_distance : float, optional
        Maximum gap distance applied to all joint finding and creation.
        ``None`` (the default) resolves to ``PanelPopulator``'s own default.
    """

    agents = []
    if panel.exterior_layer:
        agents.append(PlatePopulatorAgent(panel.exterior_layer))
    if panel.interior_layer:
        agents.append(PlatePopulatorAgent(panel.interior_layer))

    agents.append(
        EdgePopulatorAgent(
            panel.core_layer,
            standard_beam_width_increment=standard_beam_width_increment,
            edge_stud_width=edge_stud_width,
            top_plate_beam_width=top_plate_beam_width,
            bottom_plate_beam_width=bottom_plate_beam_width,
        )
    )

    if stud_spacing is None or stud_spacing:
        agents.append(
            StudPopulatorAgent(
                panel.core_layer,
                stud_width=stud_width,
                stud_spacing=stud_spacing,
            )
        )

    all_layers = [la for la in [panel.exterior_layer, panel.core_layer, panel.interior_layer] if la]

    # Build a fresh dict so we don't mutate the caller's mapping when GH (or
    # any caller) reuses the same dict across multiple panels.
    default_feature_configs = dict(default_feature_configs) if default_feature_configs else {}
    if Opening not in default_feature_configs:
        default_feature_configs[Opening] = OpeningPopulatorAgent(
            element_layers=[panel.core_layer] if panel.core_layer else [],
            trimming_layers=all_layers,
        )
    else:
        # The user-supplied prototype may be a single instance shared across
        # multiple stud_panel() calls (e.g. one CT: Feature Agent output
        # wired into a CT_StudPanel component that processes a list of panels).
        # Clone it so each call binds its own layer references.
        prototype = default_feature_configs[Opening].clone()
        prototype.element_layer_paths = [panel.core_layer.layer_path] if panel.core_layer else []
        prototype.trimming_layer_paths = [la.layer_path for la in all_layers]
        default_feature_configs[Opening] = prototype

    for instance_agent in instance_feature_configs or []:
        # Clone so the caller's agent (possibly shared across panels) is not mutated.
        agent = instance_agent.clone()
        agent.element_layer_paths = [panel.core_layer.layer_path] if panel.core_layer else []
        agent.trimming_layer_paths = [la.layer_path for la in all_layers]
        agents.append(agent)

    return PanelPopulator(
        panel=panel,
        standard_beam_width=standard_beam_width,
        agents=agents,
        default_feature_agents=default_feature_configs,
        joint_rule_overrides=joint_rule_overrides,
        max_distance=max_distance,
    )
