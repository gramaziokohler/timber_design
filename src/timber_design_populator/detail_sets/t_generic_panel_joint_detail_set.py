from __future__ import annotations

from .panel_joint_detail_set import PanelJointDetailSet


class TGenericPanelJointDetailSet(PanelJointDetailSet):
    """One panel's half of a :class:`~timber_design_populator.panel_joints.TGenericPanelJoint` junction.

    Created by the joint, not by you: on the cross panel (the one the other panel's edge lands
    on), the backing studs under the inside corners.  See :class:`PanelJointDetailSet`.
    """
