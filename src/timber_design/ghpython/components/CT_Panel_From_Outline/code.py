# env: C:\Users\Admin\OneDrive\Documents\01_ETH\04_Repositories\timber_design\src
"""Creates a Panel from a polyline outline and thickness."""

# flake8: noqa
import Grasshopper
import Rhino
import Rhino.Geometry as rg
import rhinoscriptsyntax as rs
import System
from compas.scene import Scene
from compas_rhino.conversions import polyline_to_compas
from compas_rhino.conversions import vector_to_compas

from compas_timber.elements import Panel as CTPanel
from timber_design.ghpython.ghcomponent_helpers import item_input_valid_cpython
from timber_design.ghpython.ghcomponent_helpers import get_guid_and_geometry


def _curve_to_polyline(curve):
    if isinstance(curve, rg.PolylineCurve):
        return curve.ToPolyline()
    poly_crv = curve.ToPolyline(0, 0, 0.1, 0.0, 0.0, 0.0, 0.0, 0.001, 0.001)
    return poly_crv.ToPolyline()


class PanelFromOutline(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(self, outline, thickness: float, vector, openings: System.Collections.Generic.List[object], category: str, updateRefObj: bool):
        if not item_input_valid_cpython(ghenv, outline, "outline"):
            return
        if not item_input_valid_cpython(ghenv, thickness, "thickness"):
            return

        o_guid, o_geometry = get_guid_and_geometry(outline)
        compas_outline = polyline_to_compas(_curve_to_polyline(rs.coercecurve(o_geometry)))

        compas_vector = vector_to_compas(vector) if vector else None

        o = []
        if openings:
            for o_outline in openings:
                if o_outline:
                    o_rhino_curve = rs.coercecurve(o_outline)
                    o.append(polyline_to_compas(_curve_to_polyline(o_rhino_curve)))

        panel = CTPanel.from_outline_thickness(compas_outline, thickness, vector=compas_vector, openings=o if o else None)
        panel.debug_info = []
        panel.attributes["rhino_guid"] = str(o_guid) if o_guid else None
        panel.attributes["category"] = category

        scene = Scene()
        scene.add(panel.geometry)
        geo = scene.draw()

        return panel, geo
