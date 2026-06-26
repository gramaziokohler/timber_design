"""Create a PanelPopulatorConfig from inputs."""
import Grasshopper
import Rhino
import System
from compas_rhino.conversions import vector_to_compas

from timber_design.populators import PanelPopulator


class PanelPopulatorComponent(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(self,
            panel,
            agents: System.Collections.Generic.List[object],
            standard_beam_width: float,
            default_feature_configs: System.Collections.Generic.List[object],
            joint_rule_overrides: System.Collections.Generic.List[object]):

        populators = []
        these_agents = [agent for agent in list(agents) if agent.is_on_panel(panel)]
        populators.append(PanelPopulator(
            panel=panel,
            standard_beam_width=standard_beam_width,
            agents=these_agents if these_agents else None,
            default_feature_agents={d.FEATURE_TYPE: d for d in default_feature_configs} if default_feature_configs else None,
            joint_rule_overrides=[o for o in joint_rule_overrides]
        ))

        return populators
