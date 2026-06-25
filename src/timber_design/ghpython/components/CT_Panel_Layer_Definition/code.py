# r: timber_design>=0.1.0
"""Creates panel-free Layer definitions for exterior, core, and interior layers."""

# flake8: noqa
import Grasshopper

from compas_timber.elements import Layer


class PanelLayerDefinition(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(self, core_start: float, core_end: float, exterior_name: str, core_name: str, interior_name: str):
        if core_start is None or core_end is None:
            return None

        layer_defs = []

        if core_start > 0:
            layer_defs.append(Layer(
                start_level=0.0,
                end_level=core_start,
                name=exterior_name or "Exterior Layer",
                layer_path=(0,),
            ))

        layer_defs.append(Layer(
            start_level=core_start,
            end_level=core_end,
            name=core_name or "Core Layer",
            layer_path=(1,),
        ))

        layer_defs.append(Layer(
            start_level=core_end,
            end_level=None,  # sentinel: Panel.define_layers fills from panel.thickness
            name=interior_name or "Interior Layer",
            layer_path=(2,),
        ))

        return layer_defs
