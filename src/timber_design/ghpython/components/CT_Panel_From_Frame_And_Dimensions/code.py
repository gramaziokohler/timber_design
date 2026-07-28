"""Creates a Panel from a frame and dimensions."""

# flake8: noqa
import Grasshopper
import Rhino
import Rhino.Geometry as rg
import rhinoscriptsyntax as rs
import System
from compas.scene import Scene
from compas_rhino.conversions import plane_to_compas_frame
from compas_rhino.conversions import polyline_to_compas

from compas_timber.elements import Panel as CTPanel
from compas_timber.elements.panel import Opening, OpeningType
from timber_design.ghpython.ghcomponent_helpers import list_input_valid_cpython
from timber_design.ghpython.ghcomponent_helpers import item_input_valid_cpython


def _curve_to_polyline(curve):
    if isinstance(curve, rg.PolylineCurve):
        return curve.ToPolyline()
    poly_crv = curve.ToPolyline(0, 0, 0.1, 0.0, 0.0, 0.0, 0.0, 0.001, 0.001)
    return poly_crv.ToPolyline()


class PanelFromFrameAndDimensions(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(
        self,
        frame: System.Collections.Generic.List[object],
        length: float,
        width: float,
        thickness: float,
        openings: System.Collections.Generic.List[object],
        category: str,
        updateRefObj: bool,
    ):
        if not list_input_valid_cpython(ghenv, frame, "frame"):
            return
        if not item_input_valid_cpython(ghenv, length, "length"):
            return
        if not item_input_valid_cpython(ghenv, width, "width"):
            return
        if not item_input_valid_cpython(ghenv, thickness, "thickness"):
            return

        o = []
        if openings:
            for o_outline in openings:
                if o_outline:
                    o_rhino_curve = rs.coercecurve(o_outline)
                    o.append(polyline_to_compas(_curve_to_polyline(o_rhino_curve)))

        panels = []
        scene = Scene()

        for f in frame:
            compas_frame = plane_to_compas_frame(f)
            panel = CTPanel(frame=compas_frame, length=length, width=width, thickness=thickness)
            panel.debug_info = []
            panel.attributes["category"] = category
            for opening in o:
                try:
                    panel.add_feature(Opening.from_outline_panel(opening.copy(), panel, opening_type=OpeningType.WINDOW))
                except Exception as e:
                    ghenv.Component.AddRuntimeMessage(
                        Grasshopper.Kernel.GH_RuntimeMessageLevel.Warning,
                        "Could not apply opening: {}".format(str(e)),
                    )
            panels.append(panel)
            scene.add(panel.geometry)

        geo = scene.draw()

        return panels, geo
