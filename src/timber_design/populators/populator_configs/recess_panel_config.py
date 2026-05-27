from timber_design.populators import LayerConfig
from timber_design.populators import PanelPopulatorConfig
from timber_design.populators.populator_agents.plate_populator_agent import PlatePopulatorAgentConfig
from timber_design.populators.populator_agents.recess_populator_agent import RecessPopulatorAgentConfig


def recess_panel(
    panel=None,
    standard_beam_width=None,
    recess_beam_width=None,
    recess_beam_height=None,
    standard_beam_width_increment=None,
    edge_stud_width=None,
    top_plate_beam_width=None,
    bottom_plate_beam_width=None,
    sheeting_outside=0,
    sheeting_inside=0,
    sheeting_recess=0,
    internal_joint_overrides=None,
    external_joint_overrides=None,
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
    edge_stud_width : float, optional
        Explicit width for vertical edge studs.  When ``None``,
        *standard_beam_width* is used.
    top_plate_beam_width : float, optional
        Explicit width for top plate beams.  When ``None``,
        *standard_beam_width* is used.
    bottom_plate_beam_width : float, optional
        Explicit width for bottom plate beams.  When ``None``,
        *standard_beam_width* is used.
    standard_beam_width_increment : float, optional
        Rounding increment for edge-beam widths.
    sheeting_outside : float, optional
        Thickness of external sheathing plate.
    sheeting_inside : float, optional
        Thickness of internal sheathing plate.
    sheeting_recess : float, optional
        Thickness of the sheeting plate inserted into the recess.
    internal_joint_overrides : list, optional
        :class:`~timber_design.workflow.CategoryRule` instances that replace
        matching entries in the recess agent's ``INTERNAL_JOINT_RULES``.
    external_joint_overrides : list, optional
        :class:`~timber_design.workflow.CategoryRule` instances that replace
        matching entries in the recess agent's ``EXTERNAL_JOINT_RULES``.
    default_feature_configs : dict, optional
        Mapping from panel feature class to a ``FeatureAgentConfig`` instance.
    instance_feature_configs : list, optional
        Per-instance feature config overrides.
    """

    layer_defs = []
    if sheeting_inside:
        layer_defs.append(LayerConfig(sheeting_inside, name="interior", agent_configs=[PlatePopulatorAgentConfig()]))
    if sheeting_outside:
        layer_defs.append(LayerConfig(sheeting_outside, name="exterior", agent_configs=[PlatePopulatorAgentConfig()]))

    recess_agent_config = RecessPopulatorAgentConfig(
        standard_beam_width_increment=standard_beam_width_increment,
        edge_stud_width=edge_stud_width,
        top_plate_beam_width=top_plate_beam_width,
        bottom_plate_beam_width=bottom_plate_beam_width,
        recess_beam_width=recess_beam_width,
        recess_beam_height=recess_beam_height,
        sheeting_recess=sheeting_recess,
        internal_joint_overrides=internal_joint_overrides,
        external_joint_overrides=external_joint_overrides,
    )
    layer_defs.insert(1, LayerConfig(name="frame", agent_configs=[recess_agent_config]))

    return PanelPopulatorConfig(
        panel=panel,
        standard_beam_width=standard_beam_width,
        layer_defs=layer_defs,
        default_feature_configs=default_feature_configs,
        instance_feature_configs=instance_feature_configs,
    )
