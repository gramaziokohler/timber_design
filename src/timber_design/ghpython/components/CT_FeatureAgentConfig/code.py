"""Creates a FeatureAgentConfig for a specific panel-feature type.

Select the feature agent type via the right-click menu.  The component
exposes the constructor parameters of the chosen config as dynamic inputs.

The two optional list inputs ``framing_layers`` and ``trimming_layers``
accept :class:`~timber_design.populators.LayerConfig` objects — the
**same** objects wired into a ``CT_PopulatorConfig`` component.  They
control on which layers the feature agent generates beams and on which
layers it cuts sheathing plates.  When left disconnected the agent falls
back to its default layer-selection logic (``is_framing_layer`` flag and
full-panel cross-section cut respectively).
"""

# r: timber_design>=0.1.0
# venv: td_migration
# flake8: noqa
import inspect
import Grasshopper
import System

from timber_design.populators import FeatureAgentConfig
from timber_design.ghpython.ghcomponent_helpers import manage_cpython_dynamic_params
from timber_design.ghpython.ghcomponent_helpers import rename_cpython_gh_output


# Names of the permanent list inputs that are always present
_PERMANENT_PARAM_NAMES = ["framing_layers", "trimming_layers", "external_joint_overrides", "internal_joint_overrides"]
_PERMANENT_PARAM_COUNT = len(_PERMANENT_PARAM_NAMES)


class FeatureAgentConfigurator(Grasshopper.Kernel.GH_ScriptInstance):
    def __init__(self):
        super().__init__()
        self.feature_config_types = {}
        for ft in _get_leaf_feature_configs(FeatureAgentConfig):
            self.feature_config_types[ft.__name__] = ft
        self.config_type = self.feature_config_types.get(ghenv.Component.Params.Output[0].NickName, None)

    def RunScript(
        self,
        framing_layers: System.Collections.Generic.List[object],
        trimming_layers: System.Collections.Generic.List[object],
        internal_joint_overrides: System.Collections.Generic.List[object],
        external_joint_overrides: System.Collections.Generic.List[object],
        *args,
    ):
        if not self.config_type:
            return None

        ghenv.Component.Message = self.config_type.__name__

        # Map positional *args to constructor kwargs (permanent params handled above).
        kwargs = {}
        names = self._config_arg_names()
        for i, val in enumerate(args):
            if val is not None and i < len(names):
                kwargs[names[i]] = val

        kwargs["framing_layer_defs"] = list(framing_layers) if framing_layers else None
        kwargs["trimming_layer_defs"] = list(trimming_layers) if trimming_layers else None
        kwargs["external_joint_overrides"] = list(external_joint_overrides) if external_joint_overrides else None
        kwargs["internal_joint_overrides"] = list(internal_joint_overrides) if internal_joint_overrides else None

        return self.config_type(**kwargs)

    def _config_arg_names(self):
        """Return the constructor parameter names for the current config type.

        Excludes ``framing_layer_defs``, ``trimming_layer_defs``,
        ``beam_width_overrides``, and ``joint_rule_overrides`` — those are
        handled separately.
        """
        skip = _PERMANENT_PARAM_NAMES
        spec = inspect.getfullargspec(self.config_type.__init__)
        return [n for n in spec.args[1:] if n not in skip]

    def AppendAdditionalMenuItems(self, menu):
        for name in self.feature_config_types.keys():
            item = menu.Items.Add(name, None, self._on_type_click)
            if self.config_type and name == self.config_type.__name__:
                item.Checked = True

    def _on_type_click(self, sender, event_info):
        self.config_type = self.feature_config_types[str(sender)]
        rename_cpython_gh_output(self.config_type.__name__, 0, ghenv)
        dynamic_names = self._config_arg_names()
        manage_cpython_dynamic_params(
            dynamic_names,
            ghenv,
            rename_count=0,
            permanent_param_count=_PERMANENT_PARAM_COUNT,
        )
        ghenv.Component.ExpireSolution(True)


def _get_leaf_feature_configs(cls):
    """Return all concrete (non-abstract) leaf subclasses of *cls*."""
    result = []
    for sub in cls.__subclasses__():
        children = _get_leaf_feature_configs(sub)
        if not children and getattr(sub, "IS_ABSTRACT", True) is False:
            result.append(sub)
        result.extend(children)
    return result
