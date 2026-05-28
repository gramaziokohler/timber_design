import Grasshopper
import System

from timber_design.populators.populator_configs.recess_panel_config import recess_panel


class RecessPanelConfigurator(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(
        self,
        panel,
        standard_beam_width: float,
        recess_beam_width: float,
        recess_beam_height: float,
        sheeting_recess: float,
        edge_stud_width: float,
        top_plate_beam_width: float,
        bottom_plate_beam_width: float,
        standard_beam_width_increment: float,
        sheeting_outside: float,
        sheeting_inside: float,
        joint_rule_overrides: System.Collections.Generic.List[object],
        default_feature_configs: System.Collections.Generic.List[object],
        instance_feature_configs: System.Collections.Generic.List[object],
    ):
        return recess_panel(
            panel=panel,
            standard_beam_width=standard_beam_width,
            recess_beam_width=recess_beam_width,
            recess_beam_height=recess_beam_height,
            sheeting_recess=sheeting_recess,
            edge_stud_width=edge_stud_width,
            top_plate_beam_width=top_plate_beam_width,
            bottom_plate_beam_width=bottom_plate_beam_width,
            standard_beam_width_increment=standard_beam_width_increment,
            sheeting_outside=sheeting_outside,
            sheeting_inside=sheeting_inside,
            joint_rule_overrides=list(joint_rule_overrides) if joint_rule_overrides else None,
            default_feature_configs={d.FEATURE_TYPE: d for d in default_feature_configs} if default_feature_configs else None,
            instance_feature_configs=list(instance_feature_configs) if instance_feature_configs else None,
        )
