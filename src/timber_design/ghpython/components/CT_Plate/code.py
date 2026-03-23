# r: timber_design>=0.1.0
# venv: td_migration
"""Creates a Beam from a LineCurve."""

# flake8: noqa
import Grasshopper
import Rhino
import rhinoscriptsyntax as rs
import System
from compas.scene import Scene
from compas_rhino.conversions import polyline_to_compas
from compas_rhino.conversions import vector_to_compas

from compas_timber.elements import Plate as CTPlate
from timber_design.ghpython.ghcomponent_helpers import item_input_valid_cpython, get_guid_and_geometry


class Plate(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(self, outline, thickness: float, vector: Rhino.Geometry.Vector3d, openings: System.Collections.Generic.List[object], category: str, updateRefObj: bool):
        # minimum inputs required
        if not item_input_valid_cpython(ghenv, outline, "Outline"):
            return
        scene = Scene()
        guid, geometry = get_guid_and_geometry(outline)

        plate = None
        v = vector_to_compas(vector) if vector else None
        o = []
        if openings:
            for o_outline in openings:
                o_guid, o_geometry = get_guid_and_geometry(o_outline)
                o_rhino_polyline = rs.coercecurve(o_geometry)
                o.append(polyline_to_compas(o_rhino_polyline.ToPolyline()))

        # Determine geometry type and construct CTPlate accordingly
        # Polyline/Curve
        if hasattr(geometry, 'ToPolyline'):
            rhino_polyline = rs.coercecurve(geometry)
            line = polyline_to_compas(rhino_polyline.ToPolyline())
            if not item_input_valid_cpython(ghenv, thickness, "Thickness"):
                return
            plate = CTPlate.from_outline_thickness(line, thickness, vector=v, openings=o)
        # Surface Face
        elif isinstance(geometry, Rhino.Geometry.Surface):
            if not item_input_valid_cpython(ghenv, thickness, "Thickness"):
                return
            plate = CTPlate.from_face_thickness(geometry, thickness, vector=v, openings=o)
        # Brep
        elif isinstance(geometry, Rhino.Geometry.Brep):
            plate = CTPlate.from_brep(geometry, vector=v, openings=o)
        else:
            # Unsupported geometry type
            return

        plate.attributes["rhino_guid"] = str(guid) if guid else None
        plate.attributes["category"] = category

        scene.add(plate.shape)
        geo = scene.draw()
        return plate, geo
