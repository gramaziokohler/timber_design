from __future__ import annotations

from typing import TYPE_CHECKING
from typing import List
from typing import Optional

from compas_timber.elements import Panel

from timber_design.populators.layer import LayerDefinition
from timber_design.workflow import CategoryRule

from .panel_populator_config import PanelPopulatorConfig

if TYPE_CHECKING:
    from timber_design.populators import PopulatorAgent


class RecessPanelPopulatorConfig(PanelPopulatorConfig):
    """Config for creating a recess panel populator.

    Parameters
    ----------
    standard_beam_width : float, optional
        The standard beam width for the panel elements.
    recess_beam_width : float
        Width of the recess beam.
    recess_beam_height : float
        Height of the recess beam.
    edge_beam_min_width : float
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
        A dictionary of beam width overrides for specific beam categories.
    joint_rule_overrides : list[:class:`compas_timber.design.CategoryRule`], optional
        A list of category rules to override the default ones.
    default_feature_configs : list[PopulatorAgentConfig], optional
        List of agent configs (with ``FEATURE_TYPE`` set) for default feature handling.
    """

    def __init__(
        self,
        panel: Optional[Panel] = None,
        standard_beam_width: Optional[float] = None,
        recess_beam_width: Optional[float] = None,
        recess_beam_height: Optional[float] = None,
        edge_beam_min_width: Optional[float] = None,
        standard_beam_width_increment: Optional[float] = None,
        sheeting_outside: Optional[float] = 0,
        sheeting_inside: Optional[float] = 0,
        sheeting_recess: Optional[float] = 0,
        beam_width_overrides: Optional[dict] = None,
        joint_rule_overrides: Optional[List[CategoryRule]] = None,
        default_feature_configs=None,
    ):
        # Build the ordered layer-definition stack.
        # The frame layer has no agent_configs here because create_populator_agents
        # is overridden and handles agent construction directly.
        layer_defs = []
        if sheeting_inside:
            layer_defs.append(LayerDefinition(sheeting_inside, name="interior"))
        layer_defs.append(LayerDefinition(None, name="frame", is_framing_layer=True))
        if sheeting_outside:
            layer_defs.append(LayerDefinition(sheeting_outside, name="exterior"))

        super(RecessPanelPopulatorConfig, self).__init__(
            panel=panel,
            layer_defs=layer_defs,
            default_feature_configs=default_feature_configs,
        )

        self.standard_beam_width = standard_beam_width or (panel.thickness / 2 if panel else None)
        self.recess_beam_width = recess_beam_width or standard_beam_width
        self.recess_beam_height = recess_beam_height or standard_beam_width
        self.edge_beam_min_width = edge_beam_min_width
        self.standard_beam_width_increment = standard_beam_width_increment
        self.sheeting_recess = sheeting_recess
        self.sheeting_inside = sheeting_inside
        self.sheeting_outside = sheeting_outside
        self.beam_width_overrides = beam_width_overrides or {}
        self.joint_rule_overrides = joint_rule_overrides or []

    def create_populator_agents(self, layers) -> list:
        """Create recess panel populator agents.

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
            :meth:`~PanelPopulatorConfig.create_populator` after all
            agents are assembled.
        """
        # local imports to avoid circular imports at module import time
        from timber_design.populators.populator_agents.edge_populator_agent import EdgePopulatorAgent
        from timber_design.populators.populator_agents.edge_populator_agent import EdgePopulatorAgentConfig
        from timber_design.populators.populator_agents.recess_populator_agent import RecessPopulatorAgent
        from timber_design.populators.populator_agents.recess_populator_agent import RecessPopulatorAgentConfig

        frame_layer = layers["frame"]
        frame_panel = frame_layer.panel
        edge_agent = EdgePopulatorAgent(
            frame_panel,
            EdgePopulatorAgentConfig(
                standard_beam_width_increment=self.standard_beam_width_increment,
                edge_beam_min_width=self.edge_beam_min_width or self.standard_beam_width,
                beam_width_overrides=self.beam_width_overrides,
                joint_rule_overrides=self.joint_rule_overrides,
                layer=frame_layer,
            ),
        )
        agents: List["PopulatorAgent"] = [edge_agent]
        agents.append(
            RecessPopulatorAgent(
                frame_panel,
                edge_agent,
                RecessPopulatorAgentConfig(
                    recess_beam_width=self.recess_beam_width,
                    recess_beam_height=self.recess_beam_height,
                    sheeting_recess=self.sheeting_inside,
                    beam_width_overrides=self.beam_width_overrides,
                    joint_rule_overrides=self.joint_rule_overrides,
                    layer=frame_layer,
                ),
            )
        )

        if "interior" in layers or "exterior" in layers:
            from timber_design.populators.populator_agents.plate_populator_agent import PlatePopulatorAgent
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
