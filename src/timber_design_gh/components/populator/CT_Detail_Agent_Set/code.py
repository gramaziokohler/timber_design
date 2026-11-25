# r: timber_design>=0.3.1
# flake8: noqa
import inspect
import Grasshopper

from timber_design_populator.detail_sets import DetailAgentSet
from timber_design_populator.detail_sets import PanelJointDetailSet
from timber_design_gh import manage_cpython_dynamic_params
from timber_design_gh import rename_cpython_gh_output


# Sets saved in older documents under their previous names.
_RENAMED = {
    "OpeningDetailSet": "FramedOpeningDetailSet",
    "MEPPenetrationDetailSet": "FramedPenetrationDetailSet",
    "NicheDetailSet": "FramedNicheDetailSet",
}


class DetailAgentSetComponent(Grasshopper.Kernel.GH_ScriptInstance):
    def __init__(self):
        super(DetailAgentSetComponent, self).__init__()
        self.set_types = {st.__name__: st for st in get_detail_set_types()}
        name = ghenv.Component.Params.Output[0].NickName
        self.set_type = self.set_types.get(_RENAMED.get(name, name), None)
        if self.set_type is not None and name != self.set_type.__name__:
            rename_cpython_gh_output(self.set_type.__name__, 0, ghenv)

    def RunScript(self, *args):
        if not self.set_type:
            ghenv.Component.AddRuntimeMessage(Grasshopper.Kernel.GH_RuntimeMessageLevel.Warning, "Select a detail set from the context menu (right click)")
            return
        ghenv.Component.Message = self.set_type.__name__
        # map by input name, not position: the inputs may be in any order (e.g. after switching sets)
        accepted = set(self.arg_names())
        kwargs = {}
        for param, val in zip(ghenv.Component.Params.Input, args):
            if val is not None and param.Name in accepted:
                kwargs[param.Name] = val
        return self.set_type(**kwargs)

    def arg_names(self):
        return inspect.getfullargspec(self.set_type.__init__).args[1:]

    def AppendAdditionalMenuItems(self, menu):
        for name in self.set_types.keys():
            item = menu.Items.Add(name, None, self.on_item_click)
            if self.set_type and name == self.set_type.__name__:
                item.Checked = True

    def on_item_click(self, sender, event_info):
        self.set_type = self.set_types[str(sender)]
        rename_cpython_gh_output(self.set_type.__name__, 0, ghenv)
        manage_cpython_dynamic_params(self.arg_names(), ghenv, rename_count=0, permanent_param_count=0)
        ghenv.Component.ExpireSolution(True)


def get_detail_set_types():
    """Every concrete detail set a feature can use: the subclasses of DetailAgentSet (recursively).

    Panel joint detail sets are left out: panel joints create them.
    """
    types = []

    def walk(cls):
        for subclass in cls.__subclasses__():
            if issubclass(subclass, PanelJointDetailSet):
                continue
            if not inspect.isabstract(subclass):
                types.append(subclass)
            walk(subclass)

    walk(DetailAgentSet)
    return types
