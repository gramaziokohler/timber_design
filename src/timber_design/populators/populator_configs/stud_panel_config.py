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
    orientation=None,
    sheeting_outside=0,
    sheeting_inside=0,
    joint_rule_overrides=None,
    default_feature_agents=None,
    instance_feature_agents=None,
):
    """Create a config for a standard stud-framed wall panel.

    All cross-section beam widths produced by the frame agents
    (:class:`~timber_design.populators.EdgePopulatorAgent`,
    :class:`~timber_design.populators.StudPopulatorAgent`) are exposed as
    explicit keyword arguments.  Opening-specific options (lintel posts,
    split bottom plate, header / sill / king-stud / jack-stud widths, etc.)
    are configured on an :class:`~timber_design.populators.OpeningPopulatorAgentConfig`
    that you pass via ``default_feature_configs`` or
    ``instance_feature_configs``.

    Parameters
    ----------
    panel : :class:`compas_timber.elements.Panel`, optional
        The panel to populate.
    standard_beam_width : float, optional
        Default width for every framing beam category not given an explicit
        width below.  When ``None``, defaults to half the panel thickness at
        populate time.
    stud_spacing : float, optional
        On-centre spacing between studs.  When ``None``, defaults to
        ``stud_width * 8`` at populate time.  Pass ``0`` to suppress studs
        entirely (edge-only panel).
    stud_width : float, optional
        Explicit width for intermediate stud beams.  When ``None``,
        *standard_beam_width* is used.
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
        Rounding increment for edge-beam widths (each edge beam's width is
        rounded *up* to the next multiple of this value).
    orientation : :class:`compas.geometry.Vector`, optional
        Desired stud orientation in world space.
    sheeting_outside : float, optional
        Thickness of the external sheathing plate.  ``0`` disables it.
    sheeting_inside : float, optional
        Thickness of the internal sheathing plate.  ``0`` disables it.
    joint_rule_overrides : list[:class:`~timber_design.workflow.CategoryRule`], optional
        Joint-rule overrides routed automatically to whichever agents own the
        rule's categories (see
        :meth:`~timber_design.populators.PanelPopulatorConfig.route_rule_overrides`):
        a rule whose pair lies entirely inside one agent's
        ``BEAM_CATEGORY_NAMES`` is appended to that agent's
        ``internal_joint_overrides``; a rule that straddles two agents is
        appended to each agent's ``external_joint_overrides``.  Callers do not
        need to know which agent owns a pair.
    default_feature_configs : dict, optional
        Mapping from panel feature class to a ``FeatureAgentConfig`` instance.
        If the user does not register a config for :class:`~compas_timber.panel_features.Opening`,
        a default :class:`~timber_design.populators.OpeningPopulatorAgentConfig`
        is wired up automatically (with no lintel posts and no split bottom
        plate).  Pass your own
        :class:`~timber_design.populators.OpeningPopulatorAgentConfig`
        (``lintel_posts=True``, ``split_bottom_plate_beam=True``,
        ``header_width=...``, etc.) under the ``Opening`` key to customise.
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

    agents.append(EdgePopulatorAgent(panel.core_layer, 
            standard_beam_width_increment=standard_beam_width_increment,
            edge_stud_width=edge_stud_width,
            top_plate_beam_width=top_plate_beam_width,
            bottom_plate_beam_width=bottom_plate_beam_width,
        ))
    
    if stud_spacing is None or stud_spacing:
        # spacing=0 → no studs; spacing=None → default (stud_width * 8) at populate time.
        agents.append(
            StudPopulatorAgent(panel.core_layer,
                stud_width=stud_width,
                stud_spacing=stud_spacing,
            )
        )



    # Build a fresh dict so we don't mutate the caller's mapping when GH (or
    # any caller) reuses the same dict across multiple panels.
    trimming_layers = [la for la in (panel.interior_layer, panel.core_layer, panel.exterior_layer) if la]
    default_feature_agents = dict(default_feature_agents) if default_feature_agents else {}
    if Opening not in default_feature_agents:
        default_feature_agents[Opening] = OpeningPopulatorAgent(
            element_layers=[panel.core_layer],
            trimming_layers=trimming_layers,
        )
    else:
        # The user-supplied prototype may be a single instance shared across
        # multiple stud_panel() calls (e.g. one CT_FeatureAgentConfig output
        # wired into a CT_StudPanel component that processes a list of panels).
        # Shallow-copy it so each call binds its own layer references.
        prototype = copy.copy(default_feature_agents[Opening])
        prototype.element_layers = [panel.core_layer]
        prototype.trimming_layers = trimming_layers
        default_feature_agents[Opening] = prototype

    # Instance feature agents are already feature-bound; add them directly.
    if instance_feature_agents:
        agents.extend(instance_feature_agents)

    # NOTE: ``orientation`` is no longer consumed by PanelPopulator — the stud
    # direction is baked into the panel's local frame at construction time
    # (``Panel.from_outlines(..., orientation=...)``).  Build the panel with the
    # desired orientation upstream of this factory.
    return PanelPopulator(
        panel=panel,
        standard_beam_width=standard_beam_width,
        agents=agents,
        default_feature_agents=default_feature_agents,
        joint_rule_overrides=joint_rule_overrides,
    )
