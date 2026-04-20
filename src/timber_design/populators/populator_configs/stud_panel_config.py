from compas_timber.panel_features import Opening



from timber_design.populators import LayerDefinition
from timber_design.populators import PanelPopulatorConfig

from timber_design.populators.populator_agents.edge_populator_agent import EdgePopulatorAgentConfig
from timber_design.populators.populator_agents.plate_populator_agent import PlatePopulatorAgentConfig
from timber_design.populators.populator_agents.stud_populator_agent import StudPopulatorAgentConfig
from timber_design.populators.populator_agents.opening_populator_agent import OpeningPopulatorAgentConfig

def stud_panel(
    panel=None,
    standard_beam_width=None,
    stud_spacing=None,
    standard_beam_width_increment=None,
    edge_beam_min_width=None,
    orientation=None,
    sheeting_outside=0,
    sheeting_inside=0,
    lintel_posts=False,
    split_bottom_plate_beam=False,
    beam_width_overrides=None,
    joint_rule_overrides=None,
    default_feature_configs=None,
):
    """Create a config for a standard stud-framed wall panel.

    Parameters
    ----------
    standard_beam_width : float, optional
        Default width for all framing beams.
    stud_spacing : float, optional
        On-centre spacing between studs.  When ``None`` (or ``0``), no stud
        agent is created (edge-only panel).
    standard_beam_width_increment : float, optional
        Rounding increment for edge-beam widths.
    edge_beam_min_width : float, optional
        Minimum width for edge beams.
    orientation : :class:`compas.geometry.Vector`, optional
        Desired stud orientation in world space.
    sheeting_outside : float, optional
        Thickness of the external sheathing plate.
    sheeting_inside : float, optional
        Thickness of the internal sheathing plate.
    lintel_posts : bool, optional
        When ``True``, jack studs are added inside the king studs at openings.
    split_bottom_plate_beam : bool, optional
        When ``True``, the bottom plate beam is split at the door opening.
    beam_width_overrides : dict, optional
        Per-category width overrides.
    joint_rule_overrides : list, optional
        Rules that replace matching entries in any agent's ``INTERNAL_RULES`` list.
    default_feature_configs : dict, optional
        Mapping from panel feature class to a ``PopulatorAgentConfig`` instance.
    """


    standard_beam_width = standard_beam_width or (panel.thickness / 2 if panel else None)
    stud_spacing = stud_spacing or (panel.thickness * 2 if panel else None)

    frame_agent_configs = [
        EdgePopulatorAgentConfig(
            standard_beam_width_increment=standard_beam_width_increment,
            edge_beam_min_width=edge_beam_min_width or standard_beam_width,
            beam_width_overrides=beam_width_overrides,
            joint_rule_overrides=joint_rule_overrides,
        ),
    ]
    if stud_spacing:
        frame_agent_configs.append(
            StudPopulatorAgentConfig(
                stud_spacing=stud_spacing,
                beam_width_overrides=beam_width_overrides,
                joint_rule_overrides=joint_rule_overrides,
            )
        )

    layer_defs = []
    if sheeting_inside:
        layer_defs.append(LayerDefinition(sheeting_inside, name="interior", agent_configs=[PlatePopulatorAgentConfig()]))
    layer_defs.append(LayerDefinition(None, name="frame", is_framing_layer=True, agent_configs=frame_agent_configs))
    if sheeting_outside:
        layer_defs.append(LayerDefinition(sheeting_outside, name="exterior", agent_configs=[PlatePopulatorAgentConfig()]))
    if not default_feature_configs:
        default_feature_configs = {}
    if Opening not in default_feature_configs:
        default_feature_configs[Opening] = OpeningPopulatorAgentConfig(lintel_posts = lintel_posts, split_bottom_plate_beam = split_bottom_plate_beam)


    config = PanelPopulatorConfig(panel=panel, layer_defs=layer_defs, default_feature_configs=default_feature_configs, orientation=orientation)
    config.standard_beam_width = standard_beam_width
    config.beam_width_overrides = beam_width_overrides
    config.joint_rule_overrides = joint_rule_overrides

    return config
