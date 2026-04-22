import Grasshopper
import Rhino
import System
from compas_rhino.conversions import vector_to_compas

from timber_design.populators import PanelPopulatorConfig


class PanelPopulatorConigurator(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(
        self,
        panel,
        orientation: Rhino.Geometry.Vector3d,
        standard_beam_width,
        layer_defs: System.Collections.Generic.List[object],
        default_feature_configs: System.Collections.Generic.List[object],
        instance_feature_configs: System.Collections.Generic.List[object],
    ):

        return PanelPopulatorConfig(
            panel=panel,
            orientation=vector_to_compas(orientation) if orientation else None,
            standard_beam_width=standard_beam_width,
            layer_defs=layer_defs,
            default_feature_configs={d.FEATURE_TYPE: d for d in default_feature_configs},
            instance_feature_configs=instance_feature_configs,
        )
