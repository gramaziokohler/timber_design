# r: timber_design>=0.1.0
"""Creates a LayerStructure definition for a panel cross-section."""

# flake8: noqa
import Grasshopper
import System

from compas_timber.elements.layer import LayerStructure


class PanelLayerDefinition(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(
        self,
        exterior_thickness: float,
        core_thickness: float,
        interior_thickness: float,
        exterior_name: str,
        core_name: str,
        interior_name: str,
    ):
        sublayers = []

        if exterior_thickness:
            sublayers.append(LayerStructure(name=exterior_name or "exterior", thickness=float(exterior_thickness)))

        sublayers.append(LayerStructure(name=core_name or "core", thickness=float(core_thickness) if core_thickness else None))

        if interior_thickness:
            sublayers.append(LayerStructure(name=interior_name or "interior", thickness=float(interior_thickness)))

        return LayerStructure(sublayers=sublayers)
