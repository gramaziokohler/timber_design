# env: C:\Users\Admin\OneDrive\Documents\01_ETH\04_Repositories\timber_design\src
"""Creates a Panel from two polyline outlines."""

# flake8: noqa
import Grasshopper
import Rhino.Geometry as rg
import rhinoscriptsyntax as rs
import System
from compas.scene import Scene
from compas_rhino.conversions import polyline_to_compas

from compas_timber.elements import Panel as CTPanel
from timber_design.ghpython.ghcomponent_helpers import item_input_valid_cpython
from timber_design.ghpython.ghcomponent_helpers import get_guid_and_geometry


def _curve_to_polyline(curve):
    if isinstance(curve, rg.PolylineCurve):
        return curve.ToPolyline()
    poly_crv = curve.ToPolyline(0, 0, 0.1, 0.0, 0.0, 0.0, 0.0, 0.001, 0.001)
    return poly_crv.ToPolyline()


class PanelFromTopBottom(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(self, top, bottom, openings: System.Collections.Generic.List[object], category: str, updateRefObj: bool):
        if not item_input_valid_cpython(ghenv, top, "top") or not item_input_valid_cpython(ghenv, bottom, "bottom"):
            return

        t_guid, t_geometry = get_guid_and_geometry(top)
        b_guid, b_geometry = get_guid_and_geometry(bottom)
        top_line = polyline_to_compas(_curve_to_polyline(rs.coercecurve(t_geometry)))
        bottom_line = polyline_to_compas(_curve_to_polyline(rs.coercecurve(b_geometry)))

        o = []
        if openings:
            for o_outline in openings:
                if o_outline:
                    o_rhino_curve = rs.coercecurve(o_outline)
                    o.append(polyline_to_compas(_curve_to_polyline(o_rhino_curve)))

        panel = CTPanel.from_outlines(
            top_line,
            bottom_line,
            openings=o if o else None,
        )
        panel.debug_info = []
        panel.attributes["rhino_guid_a"] = str(t_guid) if t_guid else None
        panel.attributes["rhino_guid_b"] = str(b_guid) if b_guid else None
        panel.attributes["category"] = category

        scene = Scene()
        scene.add(panel.geometry)
        geo = scene.draw()

        return panel, geo
