"""Detail sets: how a panel feature is built, one module per set.

A detail set is one way to build a feature, not the only one: the sets here are examples and
the defaults :func:`~timber_design_populator.stud_panel` uses.  There are three ways to extend
the populator:

- a new **detail agent**, for a new base behaviour;
- a new **detail set**, for a new combination of agents (or a new way to derive their inputs);
- a new **panel joint / panel joint detail set** pair, for a new connection detail.

Every set is exported here: compas serializes a set as ``timber_design_populator.detail_sets/<ClassName>``
and looks the class up in this package when decoding.  A new set is a new module plus one
export below.
"""

from .detail_agent_set import DetailAgentSet
from .framed_opening_detail_set import FramedOpeningDetailSet
from .framed_penetration_detail_set import FramedPenetrationDetailSet
from .framed_niche_detail_set import FramedNicheDetailSet
from .linear_service_detail_set import LinearServiceDetailSet
from .panel_joint_detail_set import PanelJointDetailSet
from .l_generic_panel_joint_detail_set import LGenericPanelJointDetailSet
from .t_generic_panel_joint_detail_set import TGenericPanelJointDetailSet

__all__ = [
    "DetailAgentSet",
    "FramedOpeningDetailSet",
    "FramedPenetrationDetailSet",
    "FramedNicheDetailSet",
    "LinearServiceDetailSet",
    "PanelJointDetailSet",
    "LGenericPanelJointDetailSet",
    "TGenericPanelJointDetailSet",
]
