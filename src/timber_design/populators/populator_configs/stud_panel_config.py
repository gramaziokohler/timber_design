from compas_timber.panel_features import Opening

from timber_design.populators import LayerConfig
from timber_design.populators import PanelPopulatorConfig
from timber_design.populators.populator_agents.edge_populator_agent import EdgePopulatorAgentConfig
from timber_design.populators.populator_agents.opening_populator_agent import OpeningPopulatorAgentConfig
from timber_design.populators.populator_agents.plate_populator_agent import PlatePopulatorAgentConfig
from timber_design.populators.populator_agents.stud_populator_agent import StudPopulatorAgentConfig


def stud_panel(
    panel=None,
    standard_beam_width=None,
    stud_spacing=None,
    stud_width=None,
    standard_beam_width_increment=None,
    edge_stud_width=None,
    top_plate_beam_width=None,
    bottom_plate_beam_width=None,
    orientation=None,
    sheeting_outside=0,
    sheeting_inside=0,
    lintel_posts=False,
    split_bottom_plate_beam=False,
    internal_joint_overrides=None,
    external_joint_overrides=None,
    default_feature_configs=None,
    instance_feature_configs=None,
):
    """Create a config for a standard stud-framed wall panel.

    Parameters
    ----------
    panel : :class:`compas_timber.elements.Panel`, optional
        The panel to populate.
    standard_beam_width : float, optional
        Default width for all framing beams.  When ``None``, defaults to
        half the panel thickness at populate time.
    stud_spacing : float, optional
        On-centre spacing between studs.  When ``None``, defaults to
        ``stud_width * 8`` at populate time.  Pass ``0`` to suppress studs
        entirely (edge-only panel).
    stud_width : float, optional
        Explicit width for stud beams.  When ``None``, *standard_beam_width*
        is used.
    standard_beam_width_increment : float, optional
        Rounding increment for edge-beam widths.
    edge_stud_width : float, optional
        Explicit width for vertical edge studs.  When ``None``,
        *standard_beam_width* is used.
    top_plate_beam_width : float, optional
        Explicit width for top plate beams.  When ``None``,
        *standard_beam_width* is used.
    bottom_plate_beam_width : float, optional
        Explicit width for bottom plate beams.  When ``None``,
        *standard_beam_width* is used.
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
    internal_joint_overrides : list, optional
        :class:`~timber_design.workflow.CategoryRule` instances that replace
        matching entries in the frame (edge) agent's ``INTERNAL_JOINT_RULES``.
    external_joint_overrides : list, optional
        :class:`~timber_design.workflow.CategoryRule` instances that replace
        matching entries in the frame (edge) agent's ``EXTERNAL_JOINT_RULES``.
    default_feature_configs : dict, optional
        Mapping from panel feature class to a ``FeatureAgentConfig`` instance.
    instance_feature_configs : list, optional
        Per-instance feature config overrides.
    """
    frame_agent_configs = [
        EdgePopulatorAgentConfig(
            standard_beam_width_increment=standard_beam_width_increment,
            edge_stud_width=edge_stud_width,
            top_plate_beam_width=top_plate_beam_width,
            bottom_plate_beam_width=bottom_plate_beam_width,
            internal_joint_overrides=internal_joint_overrides,
            external_joint_overrides=external_joint_overrides,
        ),
    ]
    if stud_spacing is None or stud_spacing:
        frame_agent_configs.append(
            StudPopulatorAgentConfig(
                stud_spacing=stud_spacing,
                stud_width=stud_width,
            )
        )

    layer_defs = []
    if sheeting_inside:
        layer_defs.append(LayerConfig(sheeting_inside, name="interior", agent_configs=[PlatePopulatorAgentConfig()]))
    framing_layer = LayerConfig(name="frame", agent_configs=frame_agent_configs)
    layer_defs.append(framing_layer)
    if sheeting_outside:
        layer_defs.append(LayerConfig(sheeting_outside, name="exterior", agent_configs=[PlatePopulatorAgentConfig()]))

    if not default_feature_configs:
        default_feature_configs = {}
    if Opening not in default_feature_configs:
        default_feature_configs[Opening] = OpeningPopulatorAgentConfig(
            lintel_posts=lintel_posts,
            split_bottom_plate_beam=split_bottom_plate_beam,
            framing_layer_defs=[framing_layer],
            trimming_layer_defs=layer_defs,
        )
    else:
        # User supplied their own Opening config — inject layer references when
        # missing so they don't need to know about internal LayerConfig objects.
        cfg = default_feature_configs[Opening]
        if cfg.framing_layer_defs is None:
            cfg.framing_layer_defs = [framing_layer]
        if cfg.trimming_layer_defs is None:
            cfg.trimming_layer_defs = layer_defs

    return PanelPopulatorConfig(
        panel=panel,
        orientation=orientation,
        standard_beam_width=standard_beam_width,
        layer_defs=layer_defs,
        default_feature_configs=default_feature_configs,
        instance_feature_configs=instance_feature_configs,
    )
