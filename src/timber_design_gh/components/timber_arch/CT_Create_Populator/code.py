# r: timber_design>=0.3.1
"""Makes the PanelPopulator that builds a panel as a panel type."""

import Grasshopper

from timber_design_gh import error
from timber_design_gh import resolve_panel_type


class CreatePopulatorComponent(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(self, panel, panel_type):
        if panel is None:
            return None
        panel_type = resolve_panel_type(ghenv, panel_type)
        if panel_type is None:
            return None
        try:
            return panel_type.populator(panel)
        except ValueError as e:
            error(ghenv.Component, str(e))
            return None
