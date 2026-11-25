# flake8: noqa
from System.Windows.Forms import ToolStripSeparator

import Grasshopper

from compas_timber.connections import JointTopology
from compas_arch.connections import PanelMiterJoint
from timber_design_rules import TopologyRule
from timber_design_gh import kwargs_by_input_name
from timber_design_gh import manage_cpython_dynamic_params
from timber_design_gh import panel_joint_classes
from timber_design_gh import panel_joint_flag_names
from timber_design_gh import rename_cpython_gh_output


class EdgeEdgeTopologyPanelJointRule(Grasshopper.Kernel.GH_ScriptInstance):
    def __init__(self):
        super(EdgeEdgeTopologyPanelJointRule, self).__init__()
        self.classes = panel_joint_classes(JointTopology.TOPO_EDGE_EDGE)
        self.joint_type = self.classes.get(ghenv.Component.Params.Output[0].NickName, None)

    def RunScript(self, *args):
        if not self.joint_type:
            ghenv.Component.Message = "Default: PanelMiterJoint"
            ghenv.Component.AddRuntimeMessage(Grasshopper.Kernel.GH_RuntimeMessageLevel.Warning, "PanelMiterJoint is default, change in context menu (right click)")
            return TopologyRule(JointTopology.TOPO_EDGE_EDGE, PanelMiterJoint)
        ghenv.Component.Message = self.joint_type.__name__
        return TopologyRule(JointTopology.TOPO_EDGE_EDGE, self.joint_type, **kwargs_by_input_name(ghenv, args, self.arg_names()))

    def AppendAdditionalMenuItems(self, menu):
        for name in self.classes.keys():
            item = menu.Items.Add(name, None, self.on_item_click)
            if self.joint_type and name == self.joint_type.__name__:
                item.Checked = True
        menu.Items.Add(ToolStripSeparator())

    def arg_names(self):
        # the joint's flags (e.g. backing_studs on the generic joints) become inputs
        return ["max_distance"] + panel_joint_flag_names(self.joint_type)

    def on_item_click(self, sender, event_info):
        self.joint_type = self.classes[str(sender)]
        rename_cpython_gh_output(self.joint_type.__name__, 0, ghenv)
        manage_cpython_dynamic_params(self.arg_names(), ghenv, rename_count=0, permanent_param_count=0)
        ghenv.Component.ExpireSolution(True)
