from timber_design.populators import LayerDefinition
from timber_design.populators import PanelPopulatorConfig
from timber_design.populators.populator_agents.plate_populator_agent import PlatePopulatorAgentConfig
from timber_design.populators.populator_agents.recess_populator_agent import RecessPopulatorAgentConfig


def recess_panel(
    panel=None,
    standard_beam_width=None,
    recess_beam_width=None,
    recess_beam_height=None,
    edge_beam_min_width=None,
    standard_beam_width_increment=None,
    sheeting_outside=0,
    sheeting_inside=0,
    sheeting_recess=0,
    beam_width_overrides=None,
    joint_rule_overrides=None,
    default_feature_configs=None,
    instance_feature_configs=None,
):
    """Create a config for a recess panel populator.

    Parameters
    ----------
    panel : :class:`compas_timber.elements.Panel`, optional
        The panel to populate.
    standard_beam_width : float, optional
        Default beam width.
    recess_beam_width : float, optional
        Width of the recess beam.
    recess_beam_height : float, optional
        Height of the recess beam.
    edge_beam_min_width : float, optional
        Minimum width for edge beams.
    standard_beam_width_increment : float, optional
        Rounding increment for edge-beam widths.
    sheeting_outside : float, optional
        Thickness of external sheathing plate.
    sheeting_inside : float, optional
        Thickness of internal sheathing plate.
    sheeting_recess : float, optional
        Thickness of the sheeting plate in the recess.
    beam_width_overrides : dict, optional
        Per-category width overrides passed to every agent config.
    joint_rule_overrides : list, optional
        Rules that replace matching entries in any agent's ``INTERNAL_RULES`` list.
    default_feature_configs : dict, optional
        Mapping from panel feature class to a ``LayerAgentConfig`` instance.
    """

    beam_width_overrides = beam_width_overrides or {}
    beam_width_overrides["recess"] = recess_beam_width or standard_beam_width

    recess_agent_config = RecessPopulatorAgentConfig(
        standard_beam_width_increment=standard_beam_width_increment,
        edge_beam_min_width=edge_beam_min_width or standard_beam_width,
        recess_beam_width=recess_beam_width or standard_beam_width,
        recess_beam_height=recess_beam_height or standard_beam_width,
        sheeting_recess=sheeting_recess,
        beam_width_overrides=beam_width_overrides,
        joint_rule_overrides=joint_rule_overrides,
    )
    layer_defs = []
    if sheeting_inside:
        layer_defs.append(LayerDefinition(sheeting_inside, name="interior", agent_configs=[PlatePopulatorAgentConfig()]))
    layer_defs.append(LayerDefinition(None, name="frame", is_framing_layer=True, agent_configs=[recess_agent_config]))
    if sheeting_outside:
        layer_defs.append(LayerDefinition(sheeting_outside, name="exterior", agent_configs=[PlatePopulatorAgentConfig()]))

    config = PanelPopulatorConfig(panel=panel, layer_defs=layer_defs, default_feature_configs=default_feature_configs, instance_feature_configs=instance_feature_configs)
    return config
