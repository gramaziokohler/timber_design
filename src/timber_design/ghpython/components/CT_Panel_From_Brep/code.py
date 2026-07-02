"""Creates a Panel from a Brep."""

# flake8: noqa
import Grasshopper
import rhinoscriptsyntax as rs
from compas.scene import Scene
from compas_rhino.conversions import brep_to_compas

from compas_timber.elements import Panel as CTPanel
from timber_design.ghpython.ghcomponent_helpers import item_input_valid_cpython
from timber_design.ghpython.ghcomponent_helpers import get_guid_and_geometry


class PanelFromBrep(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(self, brep, category: str, updateRefObj: bool):
        if not item_input_valid_cpython(ghenv, brep, "brep"):
            return

        guid, geometry = get_guid_and_geometry(brep)
        rhino_brep = rs.coercebrep(geometry)
        compas_brep = brep_to_compas(rhino_brep)

        panel = CTPanel.from_brep(compas_brep)
        panel.debug_info = []
        panel.attributes["rhino_guid"] = str(guid) if guid else None
        panel.attributes["category"] = category

        scene = Scene()
        scene.add(panel.geometry)
        geo = scene.draw()

        return panel, geo
