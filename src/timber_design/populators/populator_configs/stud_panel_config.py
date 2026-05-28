import copy

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
    default_feature_configs=None,
    instance_feature_configs=None,
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
    frame_agent_configs = [
        EdgePopulatorAgentConfig(
            standard_beam_width_increment=standard_beam_width_increment,
            edge_stud_width=edge_stud_width,
            top_plate_beam_width=top_plate_beam_width,
            bottom_plate_beam_width=bottom_plate_beam_width,
        ),
    ]
    if stud_spacing is None or stud_spacing:
        # spacing=0 → no studs; spacing=None → default (stud_width * 8) at populate time.
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

    # Build a fresh dict so we don't mutate the caller's mapping when GH (or
    # any caller) reuses the same dict across multiple panels.
    default_feature_configs = dict(default_feature_configs) if default_feature_configs else {}
    if Opening not in default_feature_configs:
        default_feature_configs[Opening] = OpeningPopulatorAgentConfig(
            framing_layer_defs=[framing_layer],
            trimming_layer_defs=layer_defs,
        )
    else:
        # The user-supplied Opening config may be a single instance shared
        # across multiple stud_panel() calls (e.g. one CT_FeatureAgentConfig
        # output wired into a CT_StudPanel component that processes a list of
        # panels).  Mutating its framing_layer_defs / trimming_layer_defs
        # in-place would let the last call's LayerConfig references "win",
        # leaving every other panel's opening agent pointing at a layer whose
        # resulting_layer is set by a different model.  Shallow-copy the
        # config so each stud_panel call has its own slot to write into.
        cfg = copy.copy(default_feature_configs[Opening])
        cfg.framing_layer_defs = [framing_layer]
        cfg.trimming_layer_defs = layer_defs
        default_feature_configs[Opening] = cfg

    config = PanelPopulatorConfig(
        panel=panel,
        orientation=orientation,
        standard_beam_width=standard_beam_width,
        layer_defs=layer_defs,
        default_feature_configs=default_feature_configs,
        instance_feature_configs=instance_feature_configs,
    )
    config.route_rule_overrides(joint_rule_overrides)
    return config
