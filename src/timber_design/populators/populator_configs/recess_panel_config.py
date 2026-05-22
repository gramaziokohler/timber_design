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
        Default width for all framing beams.  When ``None``, defaults to
        half the panel thickness at populate time.
    recess_beam_width : float, optional
        Width of the recess beam.  When ``None``, *standard_beam_width* is used.
    recess_beam_height : float, optional
        Height (Z extent) of the recess beam within the frame layer.  When
        ``None``, the full layer thickness is used (no recess offset).
    edge_beam_min_width : float, optional
        Minimum width for edge beams.
    standard_beam_width_increment : float, optional
        Rounding increment for edge-beam widths.
    sheeting_outside : float, optional
        Thickness of external sheathing plate.
    sheeting_inside : float, optional
        Thickness of internal sheathing plate.
    sheeting_recess : float, optional
        Thickness of the sheeting plate inserted into the recess.
    joint_rule_overrides : list, optional
        Rules that replace matching entries in any agent's ``INTERNAL_RULES``.
    default_feature_configs : dict, optional
        Mapping from panel feature class to a ``FeatureAgentConfig`` instance.
    instance_feature_configs : list, optional
        Per-instance feature config overrides.
    """
    recess_agent_config = RecessPopulatorAgentConfig(
        standard_beam_width_increment=standard_beam_width_increment,
        edge_beam_min_width=edge_beam_min_width,
        recess_beam_width=recess_beam_width,
        recess_beam_height=recess_beam_height,
        sheeting_recess=sheeting_recess,
        joint_rule_overrides=joint_rule_overrides,
    )

    layer_defs = []
    if sheeting_inside:
        layer_defs.append(LayerDefinition(sheeting_inside, name="interior", agent_configs=[PlatePopulatorAgentConfig()]))
    layer_defs.append(LayerDefinition(name="frame", agent_configs=[recess_agent_config]))
    if sheeting_outside:
        layer_defs.append(LayerDefinition(sheeting_outside, name="exterior", agent_configs=[PlatePopulatorAgentConfig()]))

    return PanelPopulatorConfig(
        panel=panel,
        standard_beam_width=standard_beam_width,
        layer_defs=layer_defs,
        default_feature_configs=default_feature_configs,
        instance_feature_configs=instance_feature_configs,
    )
