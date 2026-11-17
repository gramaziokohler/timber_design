# flake8: noqa
import Grasshopper
import System
from compas_rhino.conversions import point_to_rhino

from timber_design.ghpython.ghcomponent_helpers import item_input_valid_cpython


class ShowJointTypes(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(self, model):
        self.pt = []
        self.txt = []

        if not item_input_valid_cpython(ghenv, model, "model"):
            return

        for joint in model.joints:
            self.pt.append(point_to_rhino(joint.location))  # works for plate and panel joints too, which have no centerline
            self.txt.append(joint.__class__.__name__)

    def DrawViewportWires(self, arg):
        if ghenv.Component.Locked:
            return
        col = System.Drawing.Color.FromArgb(255, 0, 0, 0)
        # https://developer.rhino3d.com/api/RhinoCommon/html/M_Rhino_Display_DisplayPipeline_Draw2dText_5.htm
        for p, t in zip(self.pt, self.txt):
            arg.Display.Draw2dText(t, col, p, True, 12, "Verdana")
