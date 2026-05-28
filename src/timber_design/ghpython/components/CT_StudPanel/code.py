import Grasshopper
import Rhino
import System
from compas_rhino.conversions import vector_to_compas

from timber_design.populators.populator_configs.stud_panel_config import stud_panel


class StudPanelConfigurator(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(
        self,
        panel,
        standard_beam_width: float,
        stud_spacing: float,
        stud_width: float,
        edge_stud_width: float,
        top_plate_beam_width: float,
        bottom_plate_beam_width: float,
        standard_beam_width_increment: float,
        orientation: Rhino.Geometry.Vector3d,
        sheeting_outside: float,
        sheeting_inside: float,
        joint_rule_overrides: System.Collections.Generic.List[object],
        default_feature_configs: System.Collections.Generic.List[object],
        instance_feature_configs: System.Collections.Generic.List[object],
    ):
        return stud_panel(
            panel=panel,
            standard_beam_width=standard_beam_width,
            stud_spacing=stud_spacing,
            stud_width=stud_width,
            edge_stud_width=edge_stud_width,
            top_plate_beam_width=top_plate_beam_width,
            bottom_plate_beam_width=bottom_plate_beam_width,
            standard_beam_width_increment=standard_beam_width_increment,
            orientation=vector_to_compas(orientation) if orientation else None,
            sheeting_outside=sheeting_outside,
            sheeting_inside=sheeting_inside,
            joint_rule_overrides=list(joint_rule_overrides) if joint_rule_overrides else None,
            default_feature_configs={d.FEATURE_TYPE: d for d in default_feature_configs} if default_feature_configs else None,
            instance_feature_configs=list(instance_feature_configs) if instance_feature_configs else None,
        )
