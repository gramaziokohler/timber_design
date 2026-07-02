# r: timber_design>=0.1.0
# flake8: noqa
import inspect
import Grasshopper
import System

from timber_design.populators import FeatureAgent
from timber_design.ghpython.ghcomponent_helpers import manage_cpython_dynamic_params
from timber_design.ghpython.ghcomponent_helpers import rename_cpython_gh_output

# Number of permanent (non-dynamic) input parameters that always appear first.
_PERMANENT_PARAM_NAMES = ["feature", "element_layers","trimming_layers","external_joint_overrides", "internal_joint_overrides"]
_PERMANENT_PARAM_COUNT = len(_PERMANENT_PARAM_NAMES)


class FeaturePopulatorAgent(Grasshopper.Kernel.GH_ScriptInstance):
    def __init__(self):
        super(FeaturePopulatorAgent,self).__init__()
        self.agent_types = {}
        for at in get_nonabstract_subclasses(FeatureAgent):
            self.agent_types[at.__name__] = at
        self.agent_type = self.agent_types.get(ghenv.Component.Params.Output[0].NickName, None)

    def RunScript(
        self,
        feature,
        element_layers: System.Collections.Generic.List[object],
        trimming_layers: System.Collections.Generic.List[object],
        internal_joint_overrides: System.Collections.Generic.List[object],
        external_joint_overrides: System.Collections.Generic.List[object],
        *args,
    ):
        if not self.agent_type:
            return
        ghenv.Component.Message = self.agent_type.__name__
        kwargs = {"feature": feature}
        if element_layers:
            kwargs["element_layers"] = list(element_layers) if element_layers else None
        if trimming_layers:
            kwargs["trimming_layers"] = list(trimming_layers) if trimming_layers else None
        if internal_joint_overrides:
            kwargs["internal_joint_overrides"] = list(internal_joint_overrides) if internal_joint_overrides else None
        if external_joint_overrides:
            kwargs["external_joint_overrides"] = list(external_joint_overrides) if external_joint_overrides else None
        names = self.arg_names()
        for i, val in enumerate(args):
            if val is not None and i < len(names):
                kwargs[names[i]] = val
        return self.agent_type(**kwargs)

    def arg_names(self):
        # Exclude fields handled as permanent inputs or incompatible with item-access dynamic params.
        skip = _PERMANENT_PARAM_NAMES
        names = inspect.getfullargspec(self.agent_type.__init__).args[1:]
        return [n for n in names if n not in skip]

    def AppendAdditionalMenuItems(self, menu):
        for name in self.agent_types.keys():
            item = menu.Items.Add(name, None, self.on_item_click)
            if self.agent_type and name == self.agent_type.__name__:
                item.Checked = True

    def on_item_click(self, sender, event_info):
        self.agent_type = self.agent_types[str(sender)]
        rename_cpython_gh_output(self.agent_type.__name__, 0, ghenv)
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
