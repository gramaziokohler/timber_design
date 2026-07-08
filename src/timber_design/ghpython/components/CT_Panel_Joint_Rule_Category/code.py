# flake8: noqa
from collections import OrderedDict

import Grasshopper
from System.Windows.Forms import ToolStripSeparator

import compas_timber.connections as _ct_connections
from compas_timber.connections import PanelJoint
from timber_design.workflow import CategoryRule
from timber_design.ghpython import item_input_valid_cpython
from timber_design.ghpython import manage_cpython_dynamic_params
from timber_design.ghpython import rename_cpython_gh_output
from timber_design.ghpython import warning
from timber_design.ghpython import message
from timber_design.ghpython.joint_arg_mapping import get_gh_arg_names


class CategoryPanelJointRule(Grasshopper.Kernel.GH_ScriptInstance):
    def __init__(self):
        super(CategoryPanelJointRule, self).__init__()

        self.classes = {}
        for name in dir(_ct_connections):
            cls = getattr(_ct_connections, name)
            if isinstance(cls, type) and issubclass(cls, PanelJoint) and cls is not PanelJoint and getattr(cls, "SUPPORTED_TOPOLOGY", 0) != 0:
                self.classes[cls.__name__] = cls

        self.joint_type = self.classes.get(self.component.Params.Output[0].NickName, None)

    @property
    def component(self):
        return ghenv.Component  # type: ignore

    def RunScript(self, *args):
        if not self.joint_type:
            warning(self.component, "Select joint type from context menu (right click)")
            return None
        else:
            message(self.component, self.joint_type.__name__)
            cat_a, cat_b = args[:2]
            if not item_input_valid_cpython(ghenv, cat_a, self.arg_names()[0]) or not item_input_valid_cpython(ghenv, cat_b, self.arg_names()[1]):
                return

            return CategoryRule(self.joint_type, cat_a, cat_b)

    def arg_names(self):
        return get_gh_arg_names(self.joint_type, CategoryRule, expose_extra_kwargs=False)

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
        ghenv.Component.ExpireSolution(True)
