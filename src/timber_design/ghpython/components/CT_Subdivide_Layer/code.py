# r: timber_design>=0.1.0
"""Subdivides a LayerStructure into child layers by thickness."""

# flake8: noqa
import Grasshopper
import System

from compas_timber.elements.layer import LayerStructure


class SubdivideLayer(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(self, layer_structure, thicknesses: System.Collections.Generic.List[object], names: System.Collections.Generic.List[object]):
        if layer_structure is None or not thicknesses:
            return None

        thicknesses = [float(t) if t is not None else None for t in thicknesses]
        names = list(names) if names else []

        sublayers = []
        for i, t in enumerate(thicknesses):
            name = names[i] if i < len(names) else None
            sublayers.append(LayerStructure(name=name, thickness=t))

        return LayerStructure(name=layer_structure.name, thickness=layer_structure.thickness, sublayers=sublayers)
