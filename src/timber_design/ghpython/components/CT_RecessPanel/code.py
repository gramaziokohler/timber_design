import Grasshopper
import System

from timber_design.populators.populator_configs.recess_panel_config import recess_panel


class RecessPanelConfigurator(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(
        self,
        panel,
        recess_depth: float,
        standard_beam_width: float,
        recess_beam_width: float,
        edge_beam_min_width: float,
        standard_beam_width_increment: float,
        sheeting_outside: float,
        sheeting_inside: float,
        sheeting_recess: float,
        beam_width_overrides: System.Collections.Generic.List[object],
        joint_rule_overrides: System.Collections.Generic.List[object],
        default_feature_configs: System.Collections.Generic.List[object],
    ):
        recess_beam_width = recess_beam_width or standard_beam_width
        edge_beam_min_width = edge_beam_min_width or standard_beam_width
        recess_beam_height = panel.thickness - recess_depth - sheeting_inside or 0.0 - sheeting_outside or 0.0 - sheeting_recess or 0.0

        return recess_panel(
            panel=panel,
            standard_beam_width=standard_beam_width,
            recess_beam_width=recess_beam_width,
            recess_beam_height=recess_beam_height,
            edge_beam_min_width=edge_beam_min_width,
            standard_beam_width_increment=standard_beam_width_increment,
            sheeting_outside=sheeting_outside,
            sheeting_inside=sheeting_inside,
            sheeting_recess=sheeting_recess,
            beam_width_overrides=beam_width_overrides,
            joint_rule_overrides=joint_rule_overrides,
            default_feature_configs=default_feature_configs,
        )
