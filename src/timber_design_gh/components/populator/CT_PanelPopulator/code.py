# r: timber_design>=0.3.1
"""Creates a PanelPopulator from a panel and a list of agents."""

import Grasshopper
import System

from timber_design_populator import PanelPopulator
from timber_design_gh import feature_defaults_by_type


class PanelPopulatorComponent(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(
        self,
        panel,
        agents: System.Collections.Generic.List[object],
        standard_beam_width: float,
        default_detail_sets: System.Collections.Generic.List[object],
        joint_rule_overrides: System.Collections.Generic.List[object],
        max_distance: float,
    ):

        return PanelPopulator(
            panel=panel,
            standard_beam_width=standard_beam_width,
            agents=[a for a in agents or [] if a is not None],
            default_detail_sets=feature_defaults_by_type(default_detail_sets),
            joint_rule_overrides=list(joint_rule_overrides) if joint_rule_overrides else None,
            max_distance=max_distance,
        )
