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
        standard_beam_width_increment: float,
        edge_beam_min_width: float,
        orientation: Rhino.Geometry.Vector3d,
        sheeting_outside: float,
        sheeting_inside: float,
        lintel_posts: bool,
        split_bottom_plate_beam: bool,
        beam_width_overrides: System.Collections.Generic.List[object],
        joint_rule_overrides: System.Collections.Generic.List[object],
        default_feature_configs: System.Collections.Generic.List[object],
        instance_feature_configs: System.Collections.Generic.List[object],
    ):

        return stud_panel(
            panel=panel,
            standard_beam_width=standard_beam_width,
            stud_spacing=stud_spacing,
            standard_beam_width_increment=standard_beam_width_increment,
            edge_beam_min_width=edge_beam_min_width,
            orientation=vector_to_compas(orientation) if orientation else None,
            sheeting_outside=sheeting_outside,
            sheeting_inside=sheeting_inside,
            lintel_posts=lintel_posts,
            split_bottom_plate_beam=split_bottom_plate_beam,
            beam_width_overrides=beam_width_overrides,
            joint_rule_overrides=joint_rule_overrides,
            default_feature_configs=default_feature_configs,
            instance_feature_configs=instance_feature_configs,
        )
