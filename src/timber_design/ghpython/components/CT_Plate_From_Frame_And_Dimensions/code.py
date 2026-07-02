"""Creates a Plate from a frame and dimensions."""

# flake8: noqa
import Grasshopper
import Rhino
import Rhino.Geometry as rg
import rhinoscriptsyntax as rs
import System
from compas.scene import Scene
from compas_rhino.conversions import plane_to_compas_frame
from compas_rhino.conversions import polyline_to_compas

from compas_timber.elements import Plate as CTPlate
from compas_timber.fabrication import FreeContour
from timber_design.ghpython.ghcomponent_helpers import list_input_valid_cpython
from timber_design.ghpython.ghcomponent_helpers import item_input_valid_cpython


def _curve_to_polyline(curve):
    if isinstance(curve, rg.PolylineCurve):
        return curve.ToPolyline()
    poly_crv = curve.ToPolyline(0, 0, 0.1, 0.0, 0.0, 0.0, 0.0, 0.001, 0.001)
    return poly_crv.ToPolyline()


class PlateFromFrameAndDimensions(Grasshopper.Kernel.GH_ScriptInstance):
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

        plates = []
        scene = Scene()

        for f in frame:
            compas_frame = plane_to_compas_frame(f)
            plate = CTPlate(frame=compas_frame, length=length, width=width, thickness=thickness)
            plate.attributes["category"] = category
            for opening in o:
                plate.add_feature(FreeContour.from_polyline_and_element(opening, plate, interior=True))
            plates.append(plate)
            try:
                scene.add(plate.geometry)
            except IndexError:
                plate.features = []
                plate._geometry = None
                scene.add(plate.geometry)
                ghenv.Component.AddRuntimeMessage(
                    Grasshopper.Kernel.GH_RuntimeMessageLevel.Warning,
                    "One or more openings do not intersect the plate geometry and were skipped.",
                )

        geo = scene.draw()

        return plates, geo
