# r: timber_design>=0.3.1
"""Populates an existing Model with panel framing elements."""

import Grasshopper
import System
from compas.data import json_dumps
from compas.data import json_loads
from timber_design_arch.connections import PanelJoint

from timber_design_rules import DebugInfomation


class PopulateModel(Grasshopper.Kernel.GH_ScriptInstance):
    @property
    def component(self):
        return ghenv.Component  # type: ignore

    def RunScript(self, Model, Populators: System.Collections.Generic.List[object]):
        if not Populators or Model is None:
            return Model, None
        debug_info = DebugInfomation()
        model = json_loads(json_dumps(Model))  # copy model
        Populators = [pop for pop in Populators if pop is not None]
        # Bind each populator to the copy's panel; it gives the panel its panel type's layers
        # there (panels enter the model without layers). This comes first: layer-aware panel
        # joints read the layers.
        for pop in Populators:
            pop.update_panel_from_model(model)
        # Extension planes and connection interfaces are not serialized, so the copy's panels
        # and layers come back unextended and without interfaces. Re-run the panel joints on
        # the copy to restore them before population; interfaces read the extended outlines.
        panel_joints = [joint for joint in model.joints if isinstance(joint, PanelJoint)]
        for joint in panel_joints:
            joint.add_extensions()
        for panel in model.panels:
            panel.apply_edge_extensions()
        for joint in panel_joints:
            joint.add_features()

        for pop in Populators:
            pop.populate_elements()
            pop.join_elements()
            pop.process_joinery()
            pop.merge_with_model(model)
            debug_info.joint_errors.extend(pop.debug_info.joint_errors)
            debug_info.feature_errors.extend(pop.debug_info.feature_errors)

        return model, debug_info
