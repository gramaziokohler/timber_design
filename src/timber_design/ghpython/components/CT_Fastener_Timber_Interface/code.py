# flake8: noqa
import Grasshopper
import Rhino
import System
from compas_brep import Brep  # compas_timber 3 unions fastener shapes as compas_brep Breps
from compas_rhino.conversions import point_to_compas

from compas_timber.elements import FastenerTimberInterface


class FastenerTimberInterfaceComponent(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(
        self,
        outline: Rhino.Geometry.Polyline,
        thickness: float,
        drill_points: System.Collections.Generic.List[Rhino.Geometry.Point3d],
        drill_diameters: System.Collections.Generic.List[float],
        shapes: System.Collections.Generic.List[Rhino.Geometry.Brep],
        features: System.Collections.Generic.List[object],
    ):
        holes = []
        if drill_points and drill_diameters:
            if len(drill_points) == len(drill_diameters):
                for pt, dia in zip(drill_points, drill_diameters):
                    holes.append({"point": point_to_compas(pt), "diameter": dia, "vector": None, "through": True})
            elif len(drill_diameters) == 1:
                for pt in drill_points:
                    holes.append({"point": point_to_compas(pt), "diameter": drill_diameters[0], "vector": None, "through": True})
            else:
                raise Warning("Number of diameters must either match the number of points or be a single value")
        feat_list = []
        if features:
            for feature in features:
                if feature:
                    if feature.elements:
                        ghenv.Component.AddRuntimeMessage(
                            Grasshopper.Kernel.GH_RuntimeMessageLevel.Warning,
                            "Features in the Fastener Timber Interface are applied by joints. Elements in feature definitions will be ignored",
                        )
                    feat_list.append(feature)
        outline_points = [point_to_compas(pt) for pt in outline] if outline else None
        interface = FastenerTimberInterface(
            outline_points,
            thickness,
            holes,
            shapes=[Brep.from_native(brep) for brep in shapes] if shapes else [],
            features=feat_list,
        )
        return interface
