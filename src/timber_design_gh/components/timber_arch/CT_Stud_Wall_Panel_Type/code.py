# r: timber_design>=0.3.1
"""A stud wall PanelType: exterior and interior sheeting of the given thicknesses, framing in the core."""

import Grasshopper
import System

from timber_design_populator import save_panel_type
from timber_design_populator import stud_wall_type
from timber_design_gh import describe_panel_type
from timber_design_gh import error
from timber_design_gh import feature_defaults_by_type
from timber_design_gh import remark


class StudWallPanelTypeComponent(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(
        self,
        name: str,
        exterior_sheeting_thickness: float,
        interior_sheeting_thickness: float,
        standard_beam_width: float,
        stud_spacing: float,
        stud_width: float,
        edge_stud_width: float,
        top_plate_beam_width: float,
        bottom_plate_beam_width: float,
        detail_sets: System.Collections.Generic.List[object],
        filepath: str,
        save: bool,
    ):
        try:
            panel_type = stud_wall_type(
                name=name or "stud_wall",
                exterior_sheeting_thickness=exterior_sheeting_thickness,
                interior_sheeting_thickness=interior_sheeting_thickness,
                standard_beam_width=standard_beam_width if standard_beam_width is not None else 60.0,
                stud_spacing=stud_spacing,
                stud_width=stud_width,
                edge_stud_width=edge_stud_width,
                top_plate_beam_width=top_plate_beam_width,
                bottom_plate_beam_width=bottom_plate_beam_width,
                default_detail_sets=feature_defaults_by_type(detail_sets),
            )
            if filepath and save:
                save_panel_type(panel_type, filepath)
                remark(ghenv.Component, "Saved to {}.".format(filepath))
        except (ValueError, TypeError, IOError, OSError) as e:
            error(ghenv.Component, str(e))
            return None, None
        return panel_type, describe_panel_type(panel_type)
