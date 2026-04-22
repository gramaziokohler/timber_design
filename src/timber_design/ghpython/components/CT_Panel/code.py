# r: timber_design>=0.1.0
"""Creates a Panel from a Outline."""

# flake8: noqa
import Grasshopper
import Rhino
import rhinoscriptsyntax as rs
import System
from compas.scene import Scene
from compas_rhino.conversions import polyline_to_compas
from compas_rhino.conversions import vector_to_compas

from compas_timber.elements import Panel as CTPanel
from timber_design.ghpython.ghcomponent_helpers import item_input_valid_cpython
from timber_design.ghpython.ghcomponent_helpers import get_guid_and_geometry


class Panel(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(self, outline, thickness: float, vector: Rhino.Geometry.Vector3d, openings: System.Collections.Generic.List[object], category: str, updateRefObj: bool):
        # minimum inputs required

        if not item_input_valid_cpython(ghenv, outline, "Outline") or not item_input_valid_cpython(ghenv, thickness, "Thickness"):
            return
        scene = Scene()
        guid, geometry = get_guid_and_geometry(outline)
        rhino_polyline = rs.coercecurve(geometry)
        line = polyline_to_compas(rhino_polyline.ToPolyline())
        v = vector_to_compas(vector) if vector else None
        o = []
        if openings:
            for o_outline in openings:
                o_guid, o_geometry = get_guid_and_geometry(o_outline)
                o_rhino_polyline = rs.coercecurve(o_geometry)
                o.append(polyline_to_compas(o_rhino_polyline.ToPolyline()))
        panel = CTPanel.from_outline_thickness(line, thickness, vector=v, openings=o)
        panel.attributes["rhino_guid"] = str(guid) if guid else None
        panel.attributes["category"] = category

        scene.add(panel.geometry)
        geo = scene.draw()
        return panel, geo
