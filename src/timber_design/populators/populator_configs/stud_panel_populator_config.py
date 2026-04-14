from __future__ import annotations

from typing import TYPE_CHECKING
from typing import List
from typing import Optional

from compas.geometry import Vector
from compas_timber.elements import Panel
from compas_timber.panel_features import Opening

from timber_design.workflow import CategoryRule

from .panel_populator_config import PanelPopulatorConfig

if TYPE_CHECKING:
    from timber_design.populators import PopulatorAgent


class StudPanelPopulatorConfig(PanelPopulatorConfig):
    """Config for a standard stud-framed wall panel.

    Combines the configuration data (previously ``StudPanelPopulatorFactoryParams``)
    and factory behaviour (previously ``StudPanelPopulatorFactory``) into a single class.

    Parameters
    ----------
    standard_beam_width : float
        Default width (in model units) for all framing beams that do not have
        an explicit override.
    stud_spacing : float, optional
        On-centre spacing between studs.  When ``None`` (or ``0``), no stud
        agent is created (edge-only panel).
    standard_beam_width_increment : float, optional
        Rounding increment for the edge-beam width.
    edge_beam_min_width : float, optional
        Minimum width for edge beams.  Defaults to ``standard_beam_width`` when ``None``.
    stud_direction : :class:`compas.geometry.Vector`, optional
        Desired stud direction in world space.
    sheeting_outside : float, optional
        Thickness of the external sheathing plate.
    sheeting_inside : float, optional
        Thickness of the internal sheathing plate.
    lintel_posts : bool, optional
        When ``True``, jack studs (lintel posts) are added inside the king studs
        at openings.  Defaults to ``False``.
    split_bottom_plate_beam : bool, optional
        When ``True``, the bottom plate beam is split at the door opening.
        Defaults to ``False``.
    beam_width_overrides : dict, optional
        Per-category width overrides.
    joint_rule_overrides : list[:class:`~timber_design.workflow.CategoryRule`], optional
        Rules that replace matching entries in any agent's ``RULES`` list.
    default_feature_configs : dict or list, optional
        Mapping from panel feature class to a :class:`~timber_design.populators.PopulatorAgentConfig`
        instance (without ``feature`` set), or a list of config instances with ``FEATURE_TYPE`` set.
    """

    def __init__(
        self,
        panel: Optional[Panel] = None,
        standard_beam_width: Optional[float] = None,
        stud_spacing: Optional[float] = None,
        standard_beam_width_increment: Optional[float] = None,
        edge_beam_min_width: Optional[float] = None,
        stud_direction: Optional[Vector] = None,
        sheeting_outside: float = 0,
        sheeting_inside: float = 0,
        lintel_posts: bool = False,
        split_bottom_plate_beam: bool = False,
        beam_width_overrides: Optional[dict] = None,
        joint_rule_overrides: Optional[List[CategoryRule]] = None,
        default_feature_configs=None,
    ):
        super(StudPanelPopulatorConfig, self).__init__(
            panel=panel,
            sheeting_inside=sheeting_inside,
            sheeting_outside=sheeting_outside,
            default_feature_configs=default_feature_configs,
        )
        self.standard_beam_width = standard_beam_width or (panel.thickness/2 if panel else None)
        self.stud_spacing = stud_spacing or (panel.thickness * 2 if panel else None)
        self.standard_beam_width_increment = standard_beam_width_increment
        self.edge_beam_min_width = edge_beam_min_width
        self.stud_direction = stud_direction
        self.lintel_posts = lintel_posts
        self.split_bottom_plate_beam = split_bottom_plate_beam
        self.beam_width_overrides = beam_width_overrides
        self.joint_rule_overrides = joint_rule_overrides

    def create_populator_agents(self, layers) -> list:
        """Create stud panel populator agents.

        Parameters
        ----------
        layers : dict[str, :class:`~timber_design.populators.Layer`]
            All layers for the panel.  Always contains ``"local"`` and
            ``"frame"``; ``"interior"`` and ``"exterior"`` are present only
            when the corresponding sheeting thickness is non-zero.

        Returns
        -------
        list[:class:`~timber_design.populators.PopulatorAgent`]
            Agents ready for ``resolve_beam_dimensions``, which is called by
            :meth:`~PanelPopulatorConfig.create_populator_from_panel` after all
            agents are assembled.
        """
        # local imports to avoid circular imports at module import time
        from timber_design.populators import EdgePopulatorAgent
        from timber_design.populators.populator_agents.edge_populator_agent import EdgePopulatorAgentConfig

        frame_layer = layers["frame"]
        frame_panel = frame_layer.panel
        agents: List["PopulatorAgent"] = []

        agents.append(
            EdgePopulatorAgent(
                frame_panel,
                EdgePopulatorAgentConfig(
                    standard_beam_width_increment=self.standard_beam_width_increment,
                    edge_beam_min_width=self.edge_beam_min_width or self.standard_beam_width,
                    beam_width_overrides=self.beam_width_overrides,
                    joint_rule_overrides=self.joint_rule_overrides,
                    layer=frame_layer,
                ),
            )
        )

        if self.stud_spacing:
            from timber_design.populators import StudPopulatorAgent
            from timber_design.populators.populator_agents.stud_populator_agent import StudPopulatorAgentConfig

            agents.append(
                StudPopulatorAgent(
                    frame_panel,
                    StudPopulatorAgentConfig(
                        stud_spacing=self.stud_spacing,
                        beam_width_overrides=self.beam_width_overrides,
                        joint_rule_overrides=self.joint_rule_overrides,
                        layer=frame_layer,
                    ),
                )
            )

        if "interior" in layers or "exterior" in layers:
            from timber_design.populators import PlatePopulatorAgent
            from timber_design.populators.populator_agents.plate_populator_agent import PlatePopulatorAgentConfig

            if "interior" in layers:
                agents.append(
                    PlatePopulatorAgent(
                        layers["interior"],
                        PlatePopulatorAgentConfig(thickness=self.sheeting_inside),
                    )
                )
            if "exterior" in layers:
                agents.append(
                    PlatePopulatorAgent(
                        layers["exterior"],
                        PlatePopulatorAgentConfig(thickness=self.sheeting_outside),
                    )
                )

        return agents
