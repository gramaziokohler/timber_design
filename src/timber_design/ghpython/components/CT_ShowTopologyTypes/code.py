"""Shows the names of the connection topology types."""

# flake8: noqa
import Grasshopper
import System
from compas_timber.connections import get_clusters_from_joint_candidates
from timber_design.ghpython.ghcomponent_helpers import item_input_valid_cpython


class ShowTopologyTypes(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(self, model):
        self.pt = []
        self.txt = []

        if not item_input_valid_cpython(ghenv, model, "model"):
            return

        # TODO: can we cache the clusters in the model?
        clusters = get_clusters_from_joint_candidates(model.joint_candidates)

        for cluster in clusters:
            self.pt.append(cluster.joints[0].location)
            self.txt.append(cluster.joints[0].topology)

    def DrawViewportWires(self, arg):
        if ghenv.Component.Locked:
            return
        col = System.Drawing.Color.FromArgb(0, 0, 255, 0)
        # https://developer.rhino3d.com/api/RhinoCommon/html/M_Rhino_Display_DisplayPipeline_Draw2dText_5.htm
        for p, t in zip(self.pt, self.txt):
            arg.Display.Draw2dText(t, col, p, True, 12, "Verdana")
