# r: compas_timber_gh>=0.3.1, compas_timber_populator>=0.3.1
"""Creates a PanelPopulator from a panel and a list of agents."""

import Grasshopper
import System

from compas_timber_populator import PanelPopulator
from compas_timber_populator import FeatureAgent


class PanelPopulatorComponent(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(
        self,
        panel,
        agents: System.Collections.Generic.List[object],
        standard_beam_width: float,
        default_feature_configs: System.Collections.Generic.List[object],
        joint_rule_overrides: System.Collections.Generic.List[object],
        max_distance: float,
    ):

        these_agents = []
        for a in agents or []:
            if not isinstance(a, FeatureAgent):
                these_agents.append(a)
            elif getattr(a, "feature", None) in panel.features:
                these_agents.append(a)
        return PanelPopulator(
            panel=panel,
            standard_beam_width=standard_beam_width,
            agents=these_agents if these_agents else None,
            default_feature_agents={d.FEATURE_TYPE: d for d in default_feature_configs} if default_feature_configs else None,
            joint_rule_overrides=list(joint_rule_overrides) if joint_rule_overrides else None,
            max_distance=max_distance,
        )
