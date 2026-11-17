# flake8: noqa
import Grasshopper
import System

from timber_design.ghpython import warning


class FindBeamByRhinoGuid(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(self, beams: System.Collections.Generic.List[object], guid: System.Collections.Generic.List[System.Guid]):
        if not (beams and guid):
            return

        guids = [str(g) for g in guid]  # guid is a .NET List, never a python list
        FoundBeam = []
        for beam in beams:
            if beam.attributes.get("rhino_guid", None) in guids:
                FoundBeam.append(beam)

        if not FoundBeam:
            warning(ghenv.Component, "No beams found!")

        return FoundBeam
