# env: C:\Users\Admin\OneDrive\Documents\01_ETH\04_Repositories\timber_design\src
# flake8: noqa
import inspect

import Grasshopper
import compas_timber.connections as _ct_connections
from compas_timber.connections import PanelJoint
from System.Windows.Forms import ToolStripSeparator

from timber_design.ghpython import item_input_valid_cpython
from timber_design.ghpython import manage_cpython_dynamic_params
from timber_design.ghpython import rename_cpython_gh_output
from timber_design.ghpython import warning
from timber_design.workflow import DirectRule


class DirectPanelJointRule(Grasshopper.Kernel.GH_ScriptInstance):
    def __init__(self):
        super(DirectPanelJointRule, self).__init__()
        self.classes = {}
        for name in dir(_ct_connections):
            cls = getattr(_ct_connections, name)
            if (
                isinstance(cls, type)
                and issubclass(cls, PanelJoint)
                and cls is not PanelJoint
                and getattr(cls, 'SUPPORTED_TOPOLOGY', 0) != 0
                and getattr(cls, 'MAX_ELEMENT_COUNT', 0) == 2
            ):
                self.classes[cls.__name__] = cls

        self.joint_type = self.classes.get(self.component.Params.Output[0].NickName, None)

    @property
    def component(self):
        return ghenv.Component  # type: ignore

    def RunScript(self, *args):
        if not self.joint_type:
            self.component.Message = "Select joint type from context menu (right click)"
            warning(self.component, "Select joint type from context menu (right click)")
            return None

        self.component.Message = self.joint_type.__name__
        panel_a = args[0]
        panel_b = args[1]

        if not item_input_valid_cpython(ghenv, panel_a, self.arg_names()[0]) or not item_input_valid_cpython(ghenv, panel_b, self.arg_names()[1]):
            return

        kwargs = {}
        for i, val in enumerate(args[2:]):
            if val is not None:
                kwargs[self.arg_names()[i + 2]] = val

        return DirectRule(self.joint_type, [panel_a, panel_b], **kwargs)

    def arg_names(self):
        return inspect.getfullargspec(self.joint_type.__init__)[0][1:3] + ["max_distance"]

    def AppendAdditionalMenuItems(self, menu):
        for name in self.classes.keys():
            item = menu.Items.Add(name, None, self.on_item_click)
            if self.joint_type and name == self.joint_type.__name__:
                item.Checked = True
        menu.Items.Add(ToolStripSeparator())

    def on_item_click(self, sender, event_info):
        self.joint_type = self.classes[str(sender)]
        rename_cpython_gh_output(self.joint_type.__name__, 0, ghenv)
        manage_cpython_dynamic_params(self.arg_names(), ghenv, rename_count=2, permanent_param_count=0)
        self.component.ExpireSolution(True)
