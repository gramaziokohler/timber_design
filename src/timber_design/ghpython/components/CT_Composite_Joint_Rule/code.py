# r: timber_design>=0.1.0
"""Generates a composite joint rule for clusters of 3 or more elements."""

import Grasshopper  # type: ignore
import System  # type: ignore
from compas_timber.connections import JointTopology

from timber_design.ghpython import rename_cpython_gh_output
from timber_design.ghpython import warning
from timber_design.workflow import ClusterRule

topo_dict = {
    "TOPO_Y": JointTopology.TOPO_Y,
    "TOPO_K": JointTopology.TOPO_K,
}


class ClusterRuleComponent(Grasshopper.Kernel.GH_ScriptInstance):
    def __init__(self):
        super(ClusterRuleComponent, self).__init__()
        self.topo_type = topo_dict.get(self.component.Params.Output[0].NickName, None)

    @property
    def component(self):
        return ghenv.Component  # type: ignore  # noqa: F821

    def RunScript(
        self,
        rules: System.Collections.Generic.List[object],
        min_count,
        max_count,
        name,
    ):
        if not self.topo_type:
            self.component.Message = "Select topology type from context menu (right click)"
            warning(self.component, "Select topology type from context menu (right click)")
            return None

        self.component.Message = JointTopology.get_name(self.topo_type)
        return ClusterRule(
            rules=[r for r in rules if r is not None],
            topo=self.topo_type,
            min_element_count=int(min_count) if min_count is not None else None,
            max_element_count=int(max_count) if max_count is not None else None,
            name=name
        )

    def AppendAdditionalMenuItems(self, menu):
        for name in topo_dict.keys():
            item = menu.Items.Add(name, None, self.on_item_click)
            if topo_dict[name] == self.topo_type:
                item.Checked = True

    def on_item_click(self, sender, event_info):
        self.topo_type = topo_dict[str(sender)]
        rename_cpython_gh_output(str(sender), 0, ghenv)  # type: ignore  # noqa: F821
        self.component.ExpireSolution(True)
