# env: C:\Users\Admin\OneDrive\Documents\01_ETH\04_Repositories\timber_design\src
# flake8: noqa
from System.Windows.Forms import ToolStripSeparator

import Grasshopper
import compas_timber.connections as _ct_connections

from compas_timber.connections import PanelJoint
from compas_timber.connections import JointTopology
from compas_timber.connections import PanelMiterJoint
from timber_design.workflow import TopologyRule
from timber_design.ghpython.ghcomponent_helpers import manage_cpython_dynamic_params
from timber_design.ghpython.ghcomponent_helpers import rename_cpython_gh_output


def _get_panel_joint_classes(topology):
    """Return PanelJoint subclasses with given topology."""
    result = {}
    for name in dir(_ct_connections):
        cls = getattr(_ct_connections, name)
        if (
            isinstance(cls, type)
            and issubclass(cls, PanelJoint)
            and cls is not PanelJoint
            and getattr(cls, 'SUPPORTED_TOPOLOGY', None) == topology
        ):
            result[cls.__name__] = cls
    return result


class EdgeEdgeTopologyPanelJointRule(Grasshopper.Kernel.GH_ScriptInstance):
    def __init__(self):
        super(EdgeEdgeTopologyPanelJointRule, self).__init__()
        self.classes = _get_panel_joint_classes(JointTopology.TOPO_EDGE_EDGE)
        self.joint_type = self.classes.get(ghenv.Component.Params.Output[0].NickName, None)

    def RunScript(self, *args):
        if not self.joint_type:
            ghenv.Component.Message = "Default: PanelMiterJoint"
            ghenv.Component.AddRuntimeMessage(Grasshopper.Kernel.GH_RuntimeMessageLevel.Warning, "PanelMiterJoint is default, change in context menu (right click)")
            return TopologyRule(JointTopology.TOPO_EDGE_EDGE, PanelMiterJoint)
        else:
            ghenv.Component.Message = self.joint_type.__name__
            kwargs = {}
            for i, val in enumerate(args):
                if val is not None:
                    kwargs[self.arg_names()[i]] = val
            return TopologyRule(JointTopology.TOPO_EDGE_EDGE, self.joint_type, **kwargs)

    def AppendAdditionalMenuItems(self, menu):
        for name in self.classes.keys():
            item = menu.Items.Add(name, None, self.on_item_click)
            if self.joint_type and name == self.joint_type.__name__:
                item.Checked = True
        menu.Items.Add(ToolStripSeparator())

    def arg_names(self):
        return ["max_distance"]

    def on_item_click(self, sender, event_info):
        self.joint_type = self.classes[str(sender)]
        rename_cpython_gh_output(self.joint_type.__name__, 0, ghenv)
        manage_cpython_dynamic_params(self.arg_names(), ghenv, rename_count=0, permanent_param_count=0)
        ghenv.Component.ExpireSolution(True)
