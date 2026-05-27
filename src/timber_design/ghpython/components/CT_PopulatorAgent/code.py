"""makes rule to apply joint type to L topology. Defualts to LMiterJoint"""

# r: timber_design>=0.1.0
# venv: td_migration
# flake8: noqa
import inspect
import ctypes
import Grasshopper
import System

from timber_design.populators import LayerAgentConfig
from timber_design.ghpython.ghcomponent_helpers import manage_cpython_dynamic_params
from timber_design.ghpython.ghcomponent_helpers import rename_cpython_gh_output

# Number of permanent (non-dynamic) input parameters that always appear first.
_PERMANENT_PARAM_NAMES = ["external_joint_overrides", "internal_joint_overrides"]
_PERMANENT_PARAM_COUNT = len(_PERMANENT_PARAM_NAMES)


class PanelPopulatorConigurator(Grasshopper.Kernel.GH_ScriptInstance):
    def __init__(self):
        super().__init__()
        self.panel_types = {}
        for pt in get_nonabstract_subclasses(LayerAgentConfig):
            self.panel_types[pt.__name__] = pt
        self.panel_type = self.panel_types.get(ghenv.Component.Params.Output[0].NickName, None)

    def RunScript(self, joint_rule_overrides: System.Collections.Generic.List[object], *args):
        if not self.panel_type:
            return
        ghenv.Component.Message = self.panel_type.__name__
        kwargs = {}
        if joint_rule_overrides:
            kwargs["joint_rule_overrides"] = list(joint_rule_overrides)
        names = self.arg_names()
        for i, val in enumerate(args):
            if val is not None and i < len(names):
                kwargs[names[i]] = val
        return self.panel_type(**kwargs)

    def arg_names(self):
        # Exclude fields handled as permanent inputs or incompatible with item-access dynamic params.
        skip = _PERMANENT_PARAM_NAMES
        names = inspect.getfullargspec(self.panel_type.__init__).args[1:]
        return [n for n in names if n not in skip]

    def AppendAdditionalMenuItems(self, menu):
        for name in self.panel_types.keys():
            item = menu.Items.Add(name, None, self.on_item_click)
            if self.panel_type and name == self.panel_type.__name__:
                item.Checked = True

    def on_item_click(self, sender, event_info):
        self.panel_type = self.panel_types[str(sender)]
        rename_cpython_gh_output(self.panel_type.__name__, 0, ghenv)
        manage_cpython_dynamic_params(self.arg_names(), ghenv, rename_count=0, permanent_param_count=_PERMANENT_PARAM_COUNT)
        ghenv.Component.ExpireSolution(True)


def get_nonabstract_subclasses(cls):
    """Return all non-abstract subclasses of ``cls`` (recursively).

    Collect concrete implementations (classes that are not abstract)
    and return them as a flat list.
    """
    subclasses = []
    for subclass in cls.__subclasses__():
        # include subclass only if it's not abstract
        if not inspect.isabstract(subclass):
            subclasses.append(subclass)
        # recurse to collect non-abstract subclasses of the subclass
        subclasses.extend(get_nonabstract_subclasses(subclass))
    return subclasses
