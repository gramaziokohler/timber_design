# flake8: noqa
import Grasshopper
import Rhino

from compas_timber.fabrication import BTLxWriter
from timber_design.ghpython.ghcomponent_helpers import item_input_valid_cpython


class WriteBTLx(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(self, model, path, write: bool, nesting: bool):
        if not item_input_valid_cpython(ghenv, model, "Model"):
            return

        btlx = BTLxWriter(file_name=str(Rhino.RhinoDoc.ActiveDoc.Name))

        if write:
            if not item_input_valid_cpython(ghenv, path, "Path"):
                return
            XML = btlx.write(model, path, nesting)
        else:
            XML = btlx.model_to_xml(model)

        return XML
