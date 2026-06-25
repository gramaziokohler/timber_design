# r: timber_design>=0.1.0
"""Creates a Panel from a Brep."""

# flake8: noqa
import Grasshopper
import rhinoscriptsyntax as rs
import System
from compas.scene import Scene
from compas_rhino.conversions import brep_to_compas

from compas_timber.elements import Panel as CTPanel
from compas_timber.elements.layer import build_layers_from_defs
from timber_design.ghpython.ghcomponent_helpers import item_input_valid_cpython
from timber_design.ghpython.ghcomponent_helpers import get_guid_and_geometry


class PanelFromBrep(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(self, brep, layers: System.Collections.Generic.List[object], identify_doors: bool, category: str, updateRefObj: bool):
        if not item_input_valid_cpython(ghenv, brep, "Brep"):
            return
        scene = Scene()
        guid, geometry = get_guid_and_geometry(brep)
        rhino_brep = rs.coercebrep(geometry)
        brep = brep_to_compas(rhino_brep)

        panel = CTPanel.from_brep(brep, recognize_doors=bool(identify_doors))
        panel.attributes["rhino_guid"] = str(guid) if guid else None
        panel.attributes["category"] = category

        if layers:
            panel.layers = build_layers_from_defs(panel, list(layers), panel.thickness)

        if panel.layers:
            for l in panel.get_leaf_layers():
                l = l.copy()
                g = l.geometry.transformed(panel.transformation)
                scene.add(g)
        else:
            scene.add(panel.geometry)

        geo = scene.draw()
        return panel, geo
