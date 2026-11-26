# r: timber_design>=0.3.1
"""Creates a panel-wide PopulatorAgent of the type selected in the context menu."""

# flake8: noqa
import inspect
import Grasshopper
import Rhino
import System
from compas_rhino.conversions import vector_to_compas

from timber_design_populator import PopulatorAgent
from timber_design_gh import kwargs_by_input_name
from timber_design_gh import manage_cpython_dynamic_params
from timber_design_gh import rename_cpython_gh_output

# Number of permanent (non-dynamic) input parameters that always appear first.
_PERMANENT_PARAM_NAMES = ["layer", "external_joint_overrides", "internal_joint_overrides"]
_PERMANENT_PARAM_COUNT = len(_PERMANENT_PARAM_NAMES)
# Constructor arguments not offered as dynamic inputs: the layer shorthand covers the layer lists,
# and detail sets bind features.
_HIDDEN_PARAM_NAMES = ["element_layers", "trimming_layers", "feature", "composite_joint_overrides"]
# Agents saved in older documents under their previous names.
_RENAMED = {
    "EdgePopulatorAgent": "EdgeAgent",
    "StudPopulatorAgent": "StudAgent",
    "PlatePopulatorAgent": "PlateAgent",
    "PanelBoundaryPopulatorAgent": "LayerBoundaryAgent",
}


class LayerAgentComponent(Grasshopper.Kernel.GH_ScriptInstance):
    def __init__(self):
        super().__init__()
        self.panel_types = {}
        for pt in get_nonabstract_subclasses(PopulatorAgent):
            if not pt.IS_DETAIL:  # detail agents are created by detail sets
                self.panel_types[pt.__name__] = pt
        name = ghenv.Component.Params.Output[0].NickName
        self.panel_type = self.panel_types.get(_RENAMED.get(name, name), None)
        if self.panel_type is not None and name != self.panel_type.__name__:
            rename_cpython_gh_output(self.panel_type.__name__, 0, ghenv)

    def RunScript(
        self,
        layer,
        internal_joint_overrides: System.Collections.Generic.List[object],
        external_joint_overrides: System.Collections.Generic.List[object],
        *args,
    ):
        if not self.panel_type:
            return
        ghenv.Component.Message = self.panel_type.__name__
        kwargs = {"layer": layer}
        if internal_joint_overrides:
            kwargs["internal_joint_overrides"] = list(internal_joint_overrides)
        if external_joint_overrides:
            kwargs["external_joint_overrides"] = list(external_joint_overrides)
        # map by input name, not position: the inputs may be in any order (e.g. after switching agents)
        kwargs.update(kwargs_by_input_name(ghenv, (layer, internal_joint_overrides, external_joint_overrides) + tuple(args), self.arg_names()))
        for name, value in kwargs.items():  # e.g. a BoardAgent's direction
            if isinstance(value, Rhino.Geometry.Vector3d):
                kwargs[name] = vector_to_compas(value)
        return self.panel_type(**kwargs)

    def arg_names(self):
        # Exclude fields handled as permanent inputs or incompatible with item-access dynamic params.
        skip = _PERMANENT_PARAM_NAMES + _HIDDEN_PARAM_NAMES
        names = [n for n in inspect.getfullargspec(self.panel_type.__init__).args[1:] if n not in skip]
        if "priority" not in names:  # every agent takes it, through PopulatorAgent
            names.append("priority")
        return names

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
