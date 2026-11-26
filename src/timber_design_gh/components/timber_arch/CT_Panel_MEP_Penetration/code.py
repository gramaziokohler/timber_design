# r: timber_design>=0.3.1
"""Defines MEP penetration features, with a separate outline per layer, for the panel components' 'features' input."""

# flake8: noqa
import Grasshopper
import System
from compas_rhino.conversions import polyline_to_rhino_curve

from timber_design_gh import curve_to_compas_polyline
from timber_design_gh import list_input_valid_cpython
from timber_design_gh import warning
from timber_design_gh.panel_feature_helpers import MEPPenetrationDefinition


class PanelMEPPenetration(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(
        self,
        outline_core: System.Collections.Generic.List[object],
        outline_interior: System.Collections.Generic.List[object],
        outline_exterior: System.Collections.Generic.List[object],
        detail_set: object,
    ):
        if not list_input_valid_cpython(ghenv, outline_core, "outline_core"):
            return
        outline_interior = list(outline_interior or [])
        outline_exterior = list(outline_exterior or [])

        definitions = []
        for i, core in enumerate(outline_core):
            if core is None:
                continue
            interior = outline_interior[i] if i < len(outline_interior) else None
            exterior = outline_exterior[i] if i < len(outline_exterior) else None
            try:
                definitions.append(
                    MEPPenetrationDefinition(
                        curve_to_compas_polyline(core),
                        curve_to_compas_polyline(interior) if interior is not None else None,
                        curve_to_compas_polyline(exterior) if exterior is not None else None,
                        detail_set,
                    )
                )
            except Exception as e:
                warning(ghenv.Component, "Could not define MEP penetration {}: {}".format(i, e))

        geometry = [polyline_to_rhino_curve(pl) for d in definitions for pl in d.polylines]
        return definitions, geometry
