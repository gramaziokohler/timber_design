# r: timber_design>=0.3.1
"""Defines LinearService features (routed electrical or plumbing runs) for the panel components' 'features' input."""

# flake8: noqa
import Grasshopper
import System
from compas_rhino.conversions import polyline_to_rhino_curve
from compas_arch.panel_features import LinearServiceMode

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
        routing_mode: str,
    ):
        try:
            # look up by member name: on Python 3.9 compas_timber's StrEnum values are not the lowercase names
            routing_mode = LinearServiceMode[routing_mode.strip().upper()] if routing_mode else LinearServiceMode.CORE_DRILLING
        except KeyError:
            error(ghenv.Component, "routing_mode must be one of: {}".format(", ".join(m.name.lower() for m in LinearServiceMode)))
            return
        ghenv.Component.Message = routing_mode.name.lower()
        if not item_input_valid_cpython(ghenv, thickness, "thickness"):
            return

        definitions = []
        for polyline in polylines or []:
            if polyline is None:
                continue
            try:
                definitions.append(LinearServiceDefinition(curve_to_compas_polyline(polyline), thickness, routing_mode))
            except Exception as e:
                warning(ghenv.Component, "Could not define linear service: {}".format(e))

        geometry = [polyline_to_rhino_curve(pl) for d in definitions for pl in d.polylines]
        return definitions, geometry
