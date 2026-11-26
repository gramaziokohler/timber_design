# r: timber_design>=0.3.1
"""Creates a Panel from a Outline."""

# flake8: noqa
import Grasshopper
import Rhino
import rhinoscriptsyntax as rs
import System
from compas.scene import Scene
from compas_rhino.conversions import polyline_to_compas
from compas_rhino.conversions import vector_to_compas

from timber_design_arch.elements import Panel as CTPanel
from timber_design_gh import item_input_valid_cpython
from timber_design_gh import add_panel_feature_definitions
from timber_design_gh import get_guid_and_geometry


class Panel(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(
        self,
        outline,
        thickness: float,
        orientation: Rhino.Geometry.Vector3d,
        features: System.Collections.Generic.List[object],
        identify_doors: bool,
        category: str,
        updateRefObj: bool,
    ):
        if not item_input_valid_cpython(ghenv, outline, "Outline") or not item_input_valid_cpython(ghenv, thickness, "Thickness"):
            return
        scene = Scene()
        guid, geometry = get_guid_and_geometry(outline)
        rhino_polyline = rs.coercecurve(geometry)
        line = polyline_to_compas(rhino_polyline.ToPolyline())
        v = vector_to_compas(orientation) if orientation else None
        panel = CTPanel.from_outline_thickness(line, thickness, orientation=v, recognize_doors=bool(identify_doors))
        panel.attributes["rhino_guid"] = str(guid) if guid else None
        panel.attributes["category"] = category
        add_panel_feature_definitions(ghenv, panel, features)

        scene.add(panel.geometry)  # layers come later, from the panel type (CT: Populate Model)

        geo = scene.draw()
        return panel, geo
