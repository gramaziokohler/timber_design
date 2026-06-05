from timber_design.populators import PanelPopulator
from timber_design.populators import PlatePopulatorAgent
from timber_design.populators import RecessPopulatorAgent



def recess_panel(
    panel=None,
    standard_beam_width=None,
    # Recess agent
    recess_beam_width=None,
    recess_beam_height=None,
    sheeting_recess=0,
    # Edge agent
    edge_stud_width=None,
    top_plate_beam_width=None,
    bottom_plate_beam_width=None,
    standard_beam_width_increment=None,
    # Panel-level
    sheeting_outside=0,
    sheeting_inside=0,
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
        Default width for every framing beam category not given an explicit
        width below.  When ``None``, defaults to half the panel thickness at
        populate time.
    recess_beam_width : float, optional
        Width of the recess beam.  When ``None``, *standard_beam_width* is used.
    recess_beam_height : float, optional
        Height (Z extent) of the recess beam within the frame layer.  When
        ``None``, the full layer thickness is used (no recess offset).
    sheeting_recess : float, optional
        Thickness of the sheeting plate inserted into the recess.
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
    joint_rule_overrides : list[:class:`~timber_design.workflow.CategoryRule`], optional
        Joint-rule overrides routed automatically to whichever agents own the
        rule's categories (see
        :meth:`~timber_design.populators.PanelPopulatorConfig.route_rule_overrides`).
        Callers do not need to know which agent owns a pair.
    default_feature_configs : dict, optional
        Mapping from panel feature class to a ``FeatureAgentConfig`` instance.
    instance_feature_configs : list, optional
        Per-instance feature config overrides.
    """

    core_start = sheeting_inside or 0
    core_end = panel.thickness - (sheeting_outside or 0)
    panel.define_core_layer(core_start, core_end)

    agents = []
    # define_core_layer only creates the exterior/interior layer when its face
    # has sheeting (non-zero thickness); key the plate agents off existence so
    # a missing layer is simply skipped.
    if panel.exterior_layer:  # the [0, sheeting_inside] slice
        agents.append(PlatePopulatorAgent(panel.exterior_layer))
    if panel.interior_layer:  # the [thickness - sheeting_outside, thickness] slice
        agents.append(PlatePopulatorAgent(panel.interior_layer))

    agents.append(RecessPopulatorAgent(
        panel.core_layer,
        recess_width=recess_beam_width,
        edge_stud_width=edge_stud_width,
        top_plate_beam_width=top_plate_beam_width,
        bottom_plate_beam_width=bottom_plate_beam_width,
        standard_beam_width_increment=standard_beam_width_increment,
        recess_beam_height=recess_beam_height,
        sheeting_recess=sheeting_recess,
    ))

    return PanelPopulator(
        panel,
        agents,
        default_feature_agents=default_feature_configs,
        standard_beam_width=standard_beam_width,
        joint_rule_overrides=joint_rule_overrides,
    )

