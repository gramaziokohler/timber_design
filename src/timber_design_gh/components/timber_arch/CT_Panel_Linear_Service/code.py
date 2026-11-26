# r: timber_design>=0.3.1
"""Defines LinearService features (routed electrical or plumbing runs) for the panel components' 'features' input."""

# flake8: noqa
import Grasshopper
import System
from compas_rhino.conversions import polyline_to_rhino_curve

from timber_design_gh import curve_to_compas_polyline
from timber_design_gh import error
from timber_design_gh import item_input_valid_cpython
from timber_design_gh import warning
from timber_design_gh.panel_feature_helpers import LinearServiceDefinition


class PanelLinearService(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(
        self,
        polylines: System.Collections.Generic.List[object],
        thickness: float,
        detail_set: object,
    ):
        if not item_input_valid_cpython(ghenv, thickness, "thickness"):
            return

        definitions = []
        for polyline in polylines or []:
            if polyline is None:
                continue
            try:
                definitions.append(LinearServiceDefinition(curve_to_compas_polyline(polyline), thickness, detail_set))
            except Exception as e:
                warning(ghenv.Component, "Could not define linear service: {}".format(e))

        geometry = [polyline_to_rhino_curve(pl) for d in definitions for pl in d.polylines]
        return definitions, geometry
