# r: timber_design>=0.3.1
"""Reads a PanelType from a JSON file, or a library type by name."""

import Grasshopper

from timber_design_populator import list_panel_type_files
from timber_design_populator import load_panel_type
from timber_design_gh import describe_panel_type
from timber_design_gh import error
from timber_design_gh import remark


class PanelTypeFromJSONComponent(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(self, filepath: str):
        available = list(list_panel_type_files())
        if not filepath:
            remark(ghenv.Component, "Give a JSON file, or a library type: {}.".format(", ".join(available)))
            return None, None, available
        try:
            panel_type = load_panel_type(filepath.strip())
        except (ValueError, TypeError, KeyError, IOError, OSError) as e:
            error(ghenv.Component, "{} (library types: {})".format(e, ", ".join(available)))
            return None, None, available
        return panel_type, describe_panel_type(panel_type), available
