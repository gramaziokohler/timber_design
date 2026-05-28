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
        joint_rule_overrides: System.Collections.Generic.List[object],
        default_feature_configs: System.Collections.Generic.List[object],
        instance_feature_configs: System.Collections.Generic.List[object],
    ):
        config = PanelPopulatorConfig(
            panel=panel,
            orientation=vector_to_compas(orientation) if orientation else None,
            standard_beam_width=standard_beam_width,
            layer_defs=list(layer_defs) if layer_defs else None,
            default_feature_configs={d.FEATURE_TYPE: d for d in default_feature_configs} if default_feature_configs else None,
            instance_feature_configs=list(instance_feature_configs) if instance_feature_configs else None,
        )
        if joint_rule_overrides:
            config.route_rule_overrides(list(joint_rule_overrides))
        return config
