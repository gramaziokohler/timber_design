"""Creates a Panel from a frame and dimensions."""

# flake8: noqa
import Grasshopper
import System
from compas.scene import Scene
from compas_rhino.conversions import plane_to_compas_frame

from timber_design_arch.elements import Panel as CTPanel
from timber_design_gh import list_input_valid_cpython
from timber_design_gh import add_panel_feature_definitions
from timber_design_gh import item_input_valid_cpython


class PanelFromFrameAndDimensions(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(
        self,
        frame: System.Collections.Generic.List[object],
        length: float,
        width: float,
        thickness: float,
        features: System.Collections.Generic.List[object],
        category: str,
        updateRefObj: bool,
    ):
        if not list_input_valid_cpython(ghenv, frame, "frame"):
            return
        if not item_input_valid_cpython(ghenv, length, "length"):
            return
        if not item_input_valid_cpython(ghenv, width, "width"):
            return
        if not item_input_valid_cpython(ghenv, thickness, "thickness"):
            return

        panels = []
        scene = Scene()

        for f in frame:
            compas_frame = plane_to_compas_frame(f)
            panel = CTPanel(frame=compas_frame, length=length, width=width, thickness=thickness)
            panel.debug_info = []
            panel.attributes["category"] = category
            add_panel_feature_definitions(ghenv, panel, features)
            panels.append(panel)
            scene.add(panel.geometry)

        geo = scene.draw()

        return panels, geo
