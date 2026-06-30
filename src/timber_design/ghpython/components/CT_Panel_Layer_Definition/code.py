# r: timber_design>=0.1.0
"""Creates a LayerStructure definition for a panel cross-section."""

# flake8: noqa
import Grasshopper
from Grasshopper.Kernel import GH_RuntimeMessageLevel as RML

from compas_timber.elements.layer import LayerDef
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
        ext = float(exterior_thickness) if exterior_thickness is not None else None
        core = float(core_thickness) if core_thickness is not None else None
        inter = float(interior_thickness) if interior_thickness is not None else None

        # If neither face layer is provided → single-layer core panel
        if ext is None and inter is None:
            return LayerStructure(layer_defs=[LayerDef(name=core_name or "core", thickness=core)])

        # All three layers are included; exactly one may be None to absorb remaining thickness.
        nones = sum(1 for t in [ext, core, inter] if t is None)
        if nones > 1:
            ghenv.Component.AddRuntimeMessage(
                RML.Warning,
                "At most one thickness may be omitted. Specify at least 2 of the 3 layer thicknesses.",
            )
            return None

        layer_defs = [
            LayerDef(name=exterior_name or "exterior", thickness=ext),
            LayerDef(name=core_name or "core", thickness=core),
            LayerDef(name=interior_name or "interior", thickness=inter),
        ]
        return LayerStructure(layer_defs=layer_defs)
