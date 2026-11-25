# r: timber_design>=0.3.1
import Grasshopper
import System

from timber_design_populator import stud_panel
from timber_design_gh import feature_defaults_by_type


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
        joint_rule_overrides: System.Collections.Generic.List[object],
        default_detail_sets: System.Collections.Generic.List[object],
        max_distance: float,
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
            joint_rule_overrides=list(joint_rule_overrides) if joint_rule_overrides else None,
            default_detail_sets=feature_defaults_by_type(default_detail_sets),
            max_distance=max_distance,
        )
