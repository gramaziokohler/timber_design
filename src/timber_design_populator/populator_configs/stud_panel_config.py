from __future__ import annotations

from compas_arch.panel_features import LinearService
from compas_arch.panel_features import MEPPenetration
from compas_arch.panel_features import Niche
from compas_arch.panel_features import Opening

from timber_design_populator.detail_sets import LinearServiceDetailSet
from timber_design_populator.detail_sets import FramedNicheDetailSet
from timber_design_populator.detail_sets import FramedOpeningDetailSet
from timber_design_populator.detail_sets import FramedPenetrationDetailSet
from timber_design_populator.populator import PanelPopulator
from timber_design_populator.populator_agents.edge_agent import EdgeAgent
from timber_design_populator.populator_agents.plate_agent import PlateAgent
from timber_design_populator.populator_agents.stud_agent import StudAgent


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
    default_detail_sets=None,
    max_distance=None,
):
    """Create a config for a standard stud-framed wall panel.

    Uses the panel's exterior, core and interior role layers
    (see :class:`~compas_arch.elements.LayerStructure`): the exterior and
    interior layers, when present, each receive a
    :class:`~timber_design_populator.PlateAgent` and the core layer
    receives the framing agents.  A panel without a ``layer_structure`` has a
    single full-thickness core layer, so only framing is generated.

    Default feature agents are provided for openings, MEP penetrations,
    niches, and manually routed linear services (the ``Framed*`` detail sets
    and :class:`~timber_design_populator.LinearServiceDetailSet`).  A feature with
    its own ``detail_set`` (including the connection details panel joints put on
    their interfaces) is built by that instead.

    Parameters
    ----------
    panel : :class:`compas_arch.elements.Panel`
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
    default_detail_sets : dict, optional
        Mapping from panel feature class to a detail set (or agent prototype), replacing the
        built-in default for that class.
    max_distance : float, optional
        Maximum gap distance applied to all joint finding and creation.
        ``None`` (the default) resolves to ``PanelPopulator``'s own default.
    """

    agents = []
    if panel.exterior_layer:
        agents.append(PlateAgent(panel.exterior_layer))
    if panel.interior_layer:
        agents.append(PlateAgent(panel.interior_layer))

    agents.append(
        EdgeAgent(
            panel.core_layer,
            standard_beam_width_increment=standard_beam_width_increment,
            edge_stud_width=edge_stud_width,
            top_plate_beam_width=top_plate_beam_width,
            bottom_plate_beam_width=bottom_plate_beam_width,
        )
    )

    if stud_spacing is None or stud_spacing:
        agents.append(
            StudAgent(
                panel.core_layer,
                stud_width=stud_width,
                stud_spacing=stud_spacing,
            )
        )

    # Build a fresh dict so we don't mutate the caller's mapping when GH (or
    # any caller) reuses the same dict across multiple panels.
    default_detail_sets = dict(default_detail_sets) if default_detail_sets else {}
    for feature_type, default_set in (
        (Opening, FramedOpeningDetailSet()),
        (MEPPenetration, FramedPenetrationDetailSet()),
        (Niche, FramedNicheDetailSet()),
        (LinearService, LinearServiceDetailSet()),
    ):
        default_detail_sets.setdefault(feature_type, default_set)

    return PanelPopulator(
        panel=panel,
        standard_beam_width=standard_beam_width,
        agents=agents,
        default_detail_sets=default_detail_sets,
        joint_rule_overrides=joint_rule_overrides,
        max_distance=max_distance,
    )
