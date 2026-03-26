# r: timber_design>=0.1.0
# venv: td_migration
"""Creates a Beam from a Box."""

# flake8: noqa
import Grasshopper
import Rhino
import rhinoscriptsyntax as rs
import System

from compas.scene import Scene
from compas.geometry import Box
from compas_rhino.conversions import point_to_compas

from compas_timber.elements import Beam as CTBeam
from timber_design.ghpython.ghcomponent_helpers import list_input_valid_cpython
from timber_design.ghpython.ghcomponent_helpers import get_guid_and_geometry
from timber_design.ghpython.ghcomponent_helpers import compute_obb

class BeamFromBox(Grasshopper.Kernel.GH_ScriptInstance):

    def RunScript(
        self,
        box_brep: System.Collections.Generic.List[object],
        category: System.Collections.Generic.List[str],
        updateRefObj: bool,
    ):
        # minimum inputs required
        if not list_input_valid_cpython(ghenv, box_brep, "Box"):
            return

        beams = []
        scene = Scene()

        N = len(box_brep)
        if not category:
            category = [None]
        if len(category) != N:
            category = [category[0] for _ in range(N)]

        for brep_obj, c in zip(box_brep, category):
            guid, geometry = get_guid_and_geometry(brep_obj)
            rhino_brep = rs.coercebrep(geometry)
            if not rhino_brep:
                continue
            obb = compute_obb(rhino_brep)
            rhino_corners = obb.GetCorners()
            compas_corners = [point_to_compas(pt) for pt in rhino_corners]
            box = Box.from_bounding_box(compas_corners)
            beam = CTBeam.from_box(box)
            beam.attributes["rhino_guid"] = str(guid) if guid else None
            beam.attributes["category"] = c
            beams.append(beam)
            scene.add(beam.blank)

        blanks = scene.draw()
        return beams, blanks

