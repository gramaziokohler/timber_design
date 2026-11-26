# r: timber_design>=0.3.1
"""Defines Niche features (one-sided blind recesses) for the panel components' 'features' input."""

# flake8: noqa
import Grasshopper
import System
from compas_rhino.conversions import polyline_to_rhino_curve
from timber_design_arch.elements import LayerRole
from timber_design_arch.panel_features import Niche

from timber_design_gh import curve_to_compas_polyline
from timber_design_gh import error
from timber_design_gh import warning
from timber_design_gh.panel_feature_helpers import NicheDefinition


class PanelNiche(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(
        self,
        outlines: System.Collections.Generic.List[object],
        side: str,
        depth: float,
        detail_set: object,
    ):
        try:
            # LayerRole has explicit values, so lookup by value works on every Python version
            side = LayerRole(side.strip().lower()) if side else LayerRole.EXTERIOR
            if side not in Niche.SIDES:
                raise ValueError(side)
        except ValueError:
            error(ghenv.Component, "side must be one of: {}".format(", ".join(s.value for s in Niche.SIDES)))
            return
        ghenv.Component.Message = "{}, {}".format(side.value, "through framing" if depth is None else "depth {}".format(depth))

        definitions = []
        for outline in outlines or []:
            if outline is None:
                continue
            try:
                definitions.append(NicheDefinition(curve_to_compas_polyline(outline), side, depth, detail_set))
            except Exception as e:
                warning(ghenv.Component, "Could not define niche: {}".format(e))

        geometry = [polyline_to_rhino_curve(pl) for d in definitions for pl in d.polylines]
        return definitions, geometry
