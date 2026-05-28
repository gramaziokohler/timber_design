import Grasshopper
import System

from timber_design.populators import LayerConfig


class MyComponent(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(self, thickness, name, agent_configs: System.Collections.Generic.List[object], sublayers: System.Collections.Generic.List[object]):
        return LayerConfig(
            thickness=thickness,
            name=name,
            agent_configs=list(agent_configs) if agent_configs else None,
            sublayers=list(sublayers) if sublayers else None,
        )
