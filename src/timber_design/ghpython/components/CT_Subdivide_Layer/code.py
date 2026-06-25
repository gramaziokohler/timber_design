# r: timber_design>=0.1.0
"""Subdivides a layer definition into child layers by thickness."""

# flake8: noqa
import Grasshopper
import System

from compas_timber.elements import Layer


class SubdivideLayer(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(self, layer, thicknesses: System.Collections.Generic.List[object], names: System.Collections.Generic.List[object]):
        if layer is None or not thicknesses:
            return None

        thicknesses = [float(t) for t in thicknesses]
        names = list(names) if names else []
        parent_path = layer.layer_path

        sublayers = []
        cursor = layer.start_level
        for i, thickness in enumerate(thicknesses):
            start = cursor
            cursor += thickness
            is_last = i == len(thicknesses) - 1
            end = layer.end_level if is_last else cursor
            name = names[i] if i < len(names) else "{}_{}".format(layer.name or "Layer", i)
            sublayers.append(Layer(
                start_level=start,
                end_level=end,
                name=name,
                layer_path=parent_path + (i,),
            ))

        return sublayers
