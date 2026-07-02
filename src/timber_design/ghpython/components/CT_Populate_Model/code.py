# r: timber_design>=0.1.0
"""Populates an existing Model with panel framing elements."""

import Grasshopper
import System
from compas.data import json_dumps, json_loads

from timber_design.workflow import DebugInfomation


class PopulateModel(Grasshopper.Kernel.GH_ScriptInstance):
    @property
    def component(self):
        return ghenv.Component  # type: ignore

    def RunScript(self, Model, Populators: System.Collections.Generic.List[object]):
        if not Populators or Model is None:
            return Model, None
        debug_info = DebugInfomation()
        model = json_loads(json_dumps(Model)) #copy model
        model.process_joinery()
        for panel in model.panels:
            panel.apply_edge_extensions()

        for pop in Populators:
            if pop is None:
                continue

            pop.update_panel_from_model(model)

            pop.populate_elements()
            pop.join_elements()
            pop.merge_with_model(model)
        model.process_joinery()
        return model, debug_info
