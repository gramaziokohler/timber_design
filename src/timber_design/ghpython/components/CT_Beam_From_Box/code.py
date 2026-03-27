# r: timber_design>=0.1.0
# venv: td_migration
"""Creates a Beam from a Box."""

# flake8: noqa
import Grasshopper
import Rhino
import rhinoscriptsyntax as rs
import System

from compas.scene import Scene
from compas.geometry import Box, Frame, Point
from compas.geometry import oriented_bounding_box_numpy
from compas_rhino.conversions import point_to_compas

from compas_timber.elements import Beam as CTBeam
from timber_design.ghpython.ghcomponent_helpers import list_input_valid_cpython
from timber_design.ghpython.ghcomponent_helpers import get_guid_and_geometry

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

            compas_corners = [point_to_compas(pt) for pt in rhino_brep.Vertices]
            obb_points = oriented_bounding_box_numpy(compas_corners)
            box = self._box_from_obb_consistent(obb_points)

            beam = CTBeam.from_box(box)
            beam.attributes["rhino_guid"] = str(guid) if guid else None
            beam.attributes["category"] = c
            beams.append(beam)
            scene.add(beam.blank)

        blanks = scene.draw()
        return beams, blanks

    def _box_from_obb_consistent(self, obb_points):
        """Build a compas Box from 8 OBB points with consistent axis orientation.

        Ensures x=longest, y=mid, z=shortest dimension so that CTBeam.from_box
        always receives length along X regardless of the input geometry orientation.
        """
        pts = [Point(*p) for p in obb_points]

        origin = pts[0]
        x_vec = pts[1] - pts[0]   # edge along local X
        y_vec = pts[3] - pts[0]   # edge along local Y
        z_vec = pts[4] - pts[0]   # edge along local Z

        xsize = x_vec.length
        ysize = y_vec.length
        zsize = z_vec.length

        axes = sorted(
            [(xsize, x_vec), (ysize, y_vec), (zsize, z_vec)],
            key=lambda item: item[0],
            reverse=True,  # largest first -> X
        )

        sizes = [a[0] for a in axes]
        vecs  = [a[1] for a in axes]

        x_axis = vecs[0].unitized()
        y_axis = vecs[1].unitized()
        z_axis = x_axis.cross(y_axis)
        z_axis.unitize()
        y_axis = z_axis.cross(x_axis)
        y_axis.unitize()

        centroid = Point(
            sum(p.x for p in pts) / 8.0,
            sum(p.y for p in pts) / 8.0,
            sum(p.z for p in pts) / 8.0,
        )
        frame = Frame(centroid, x_axis, y_axis)

        return Box(sizes[0], sizes[1], sizes[2], frame=frame)
