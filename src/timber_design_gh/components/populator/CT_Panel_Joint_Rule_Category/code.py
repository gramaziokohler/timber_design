# flake8: noqa
import Grasshopper
from System.Windows.Forms import ToolStripSeparator

from timber_design_rules import CategoryRule
from timber_design_gh import item_input_valid_cpython
from timber_design_gh import kwargs_by_input_name
from timber_design_gh import manage_cpython_dynamic_params
from timber_design_gh import panel_joint_classes
from timber_design_gh import panel_joint_flag_names
from timber_design_gh import rename_cpython_gh_output
from timber_design_gh import warning

_FIRST_NAMES = ["panel_a_category", "panel_b_category"]


class CategoryPanelJointRule(Grasshopper.Kernel.GH_ScriptInstance):
    def __init__(self):
        super(CategoryPanelJointRule, self).__init__()
        self.classes = panel_joint_classes()
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
        a, b = args[:2]
        if not item_input_valid_cpython(ghenv, a, _FIRST_NAMES[0]) or not item_input_valid_cpython(ghenv, b, _FIRST_NAMES[1]):
            return
        kwargs = kwargs_by_input_name(ghenv, args, self.arg_names()[2:])
        return CategoryRule(self.joint_type, a, b, **kwargs)

    def arg_names(self):
        # the joint's flags (e.g. backing_studs on the generic joints) become inputs
        return _FIRST_NAMES + ["max_distance"] + panel_joint_flag_names(self.joint_type)

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
