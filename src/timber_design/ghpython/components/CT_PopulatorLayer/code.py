import Grasshopper
import System

from timber_design.populators import LayerDefinition


class MyComponent(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(self, thickness, name, agent_configs: System.Collections.Generic.List[object], sublayers: System.Collections.Generic.List[object], is_framing):

        return LayerDefinition(thickness, name, agent_configs, sublayers, is_framing)
