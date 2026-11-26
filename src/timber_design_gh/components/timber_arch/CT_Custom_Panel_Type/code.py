# r: timber_design>=0.3.1
"""Assembles a PanelType from a layer structure, the agents that build its layers and detail sets."""

import Grasshopper
import System

from timber_design_populator import PanelType
from timber_design_populator import save_panel_type
from timber_design_gh import describe_panel_type
from timber_design_gh import error
from timber_design_gh import feature_defaults_by_type
from timber_design_gh import remark


class CustomPanelTypeComponent(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(
        self,
        name: str,
        layer_structure,
        agents: System.Collections.Generic.List[object],
        detail_sets: System.Collections.Generic.List[object],
        standard_beam_width: float,
        filepath: str,
        save: bool,
    ):
        if layer_structure is None:
            remark(ghenv.Component, "Give a layer structure (CT: Panel Layer Definition, CT: Subdivide Layer).")
            return None, None
        try:
            panel_type = PanelType(
                name or "custom_panel_type",
                getattr(layer_structure, "Value", layer_structure),
                agents=[getattr(a, "Value", a) for a in agents or [] if a is not None],
                default_detail_sets=feature_defaults_by_type(detail_sets),
                standard_beam_width=standard_beam_width,
            )
            if filepath and save:
                save_panel_type(panel_type, filepath)
                remark(ghenv.Component, "Saved to {}.".format(filepath))
        except (ValueError, TypeError, IOError, OSError) as e:
            error(ghenv.Component, str(e))
            return None, None
        return panel_type, describe_panel_type(panel_type)
