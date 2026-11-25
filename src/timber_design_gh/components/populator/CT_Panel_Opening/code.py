# r: timber_design>=0.3.1
"""Defines Opening features (windows and doors) for the panel components' 'features' input."""

# flake8: noqa
import Grasshopper
import System
from compas_rhino.conversions import polyline_to_rhino_curve
from compas_arch.panel_features import OpeningType

from timber_design_gh import curve_to_compas_polyline
from timber_design_gh import error
from timber_design_gh import warning
from timber_design_gh.panel_feature_helpers import OpeningDefinition


class PanelOpening(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(
        self,
        outlines: System.Collections.Generic.List[object],
        opening_type: str,
        project_horizontal: bool,
        detail_set: object,
    ):
        try:
            # look up by member name: on Python 3.9 compas_timber's StrEnum values are not the lowercase names
            opening_type = OpeningType[opening_type.strip().upper()] if opening_type else OpeningType.WINDOW
        except KeyError:
            error(ghenv.Component, "opening_type must be one of: {}".format(", ".join(t.name.lower() for t in OpeningType)))
            return
        ghenv.Component.Message = opening_type.name.lower()

        definitions = []
        for outline in outlines or []:
            if outline is None:
                continue
            try:
                definitions.append(OpeningDefinition(curve_to_compas_polyline(outline), opening_type, project_horizontal, detail_set))
            except Exception as e:
                warning(ghenv.Component, "Could not define opening: {}".format(e))

        geometry = [polyline_to_rhino_curve(pl) for d in definitions for pl in d.polylines]
        return definitions, geometry
