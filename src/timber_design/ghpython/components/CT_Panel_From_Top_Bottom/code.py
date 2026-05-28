# r: timber_design>=0.1.0
"""Creates a Panel from a Top and Bottom Outline."""

# flake8: noqa
import Grasshopper
import rhinoscriptsyntax as rs
import System
from compas.scene import Scene
from compas_rhino.conversions import polyline_to_compas

from compas_timber.elements import Panel as CTPanel
from timber_design.ghpython.ghcomponent_helpers import item_input_valid_cpython
from timber_design.ghpython.ghcomponent_helpers import get_guid_and_geometry


class PanelFromTopBottom(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(self, top, bottom, openings: System.Collections.Generic.List[object], category: str, updateRefObj: bool):
        # minimum inputs required

        if not item_input_valid_cpython(ghenv, top, "top") or not item_input_valid_cpython(ghenv, bottom, "bottom"):
            return

        scene = Scene()

        t_guid, t_geometry = get_guid_and_geometry(top)
        b_guid, b_geometry = get_guid_and_geometry(bottom)
        t_rhino_polyline = rs.coercecurve(t_geometry)
        b_rhino_polyline = rs.coercecurve(b_geometry)
        top_line = polyline_to_compas(t_rhino_polyline.ToPolyline())
        bottom_line = polyline_to_compas(b_rhino_polyline.ToPolyline())

        o = []
        if openings:
            for o_outline in openings:
                if o_outline:
                    o_guid, o_geometry = get_guid_and_geometry(o_outline)
                    o_rhino_polyline = rs.coercecurve(o_geometry)
                    o.append(polyline_to_compas(o_rhino_polyline.ToPolyline()))

        panel = CTPanel.from_outlines(top_line, bottom_line, openings=o)
        panel.attributes["rhino_guid_a"] = str(t_guid) if t_guid else None
        panel.attributes["rhino_guid_b"] = str(b_guid) if b_guid else None
        panel.attributes["category"] = category

        scene.add(panel.geometry)

        geo = scene.draw()

        return panel, geo
