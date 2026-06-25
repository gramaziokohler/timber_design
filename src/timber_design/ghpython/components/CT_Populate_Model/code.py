# r: timber_design>=0.1.0
"""Populates an existing Model with panel framing elements."""

import Grasshopper
import System

from timber_design.workflow import DebugInfomation


class PopulateModel(Grasshopper.Kernel.GH_ScriptInstance):
    @property
    def component(self):
        return ghenv.Component  # type: ignore

    def RunScript(
        self,
        Model,
        Populators: System.Collections.Generic.List[object],
    ):
        if not Populators or Model is None:
            return Model, None

        debug_info = DebugInfomation()

        # Build rhino_guid → panel lookup for relinking
        panel_by_guid = {}
        for panel in Model.panels:
            rhino_guid = panel.attributes.get("rhino_guid")
            if rhino_guid:
                panel_by_guid[rhino_guid] = panel

        for pop in Populators:
            if pop is None:
                continue
            # Relink to the model's panel instance by rhino_guid
            rhino_guid = pop.original_panel.attributes.get("rhino_guid")
            if rhino_guid and rhino_guid in panel_by_guid:
                model_panel = panel_by_guid[rhino_guid]
                if pop.original_panel is not model_panel:
                    pop.original_panel = model_panel
                    pop.layers = list(model_panel.layers)
                    pop.layer_tree = {k: v for k, v in model_panel.layer_tree.items()}
            pop.populate_elements()
            pop.join_elements()
            pop.merge_with_model(Model)

        return Model, debug_info
