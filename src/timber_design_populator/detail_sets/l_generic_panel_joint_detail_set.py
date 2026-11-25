from __future__ import annotations

from .panel_joint_detail_set import PanelJointDetailSet


class LGenericPanelJointDetailSet(PanelJointDetailSet):
    """One panel's half of an :class:`~timber_design_populator.panel_joints.LGenericPanelJoint` corner.

    Created by the joint, not by you: the layer stagger at this panel's edge and, on the cross
    panel, the backing studs under the inside corner.  See :class:`PanelJointDetailSet`.
    """
