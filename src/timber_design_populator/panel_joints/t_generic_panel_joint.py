from __future__ import annotations

from typing import Optional

from timber_design_arch.connections import PanelTButtJoint

from timber_design_populator.detail_sets.t_generic_panel_joint_detail_set import TGenericPanelJointDetailSet
from timber_design_populator.panel_joints.panel_joint_geometry import backing_stud_lines


class TGenericPanelJoint(PanelTButtJoint):
    """A T-butt junction (one panel's edge on another's face), with a generic connection detail.

    Shapes the panel envelopes like :class:`~timber_design_arch.connections.PanelTButtJoint`, then
    works out each panel's half of the detail with both panels in view and gives each panel's
    interface a :class:`~timber_design_populator.detail_sets.TGenericPanelJointDetailSet`.

    Parameters
    ----------
    panel_a, panel_b, topology, a_segment_index, b_segment_index : optional
        See :class:`~timber_design_arch.connections.PanelTButtJoint`; panel_a is the main panel (its
        edge lands on panel_b's face).
    backing_studs : bool, optional
        Add backing studs to the cross panel under both inside corners.  Default ``False``.
    backing_stud_width : float, optional
        Unset: the populator's ``standard_beam_width``.
    backing_stud_inset : float, optional
        How far each backing stud moves from the main panel's face into its footprint.
    """

    def __init__(
        self,
        panel_a=None,
        panel_b=None,
        topology=None,
        a_segment_index=None,
        b_segment_index=None,
        backing_studs: bool = False,
        backing_stud_width: Optional[float] = None,
        backing_stud_inset: float = 0.0,
        **kwargs,
    ):
        super().__init__(panel_a, panel_b, topology, a_segment_index, b_segment_index, **kwargs)
        self.backing_studs = backing_studs
        self.backing_stud_width = backing_stud_width
        self.backing_stud_inset = backing_stud_inset

    @property
    def __data__(self):
        data = super().__data__
        data["backing_studs"] = self.backing_studs
        data["backing_stud_width"] = self.backing_stud_width
        data["backing_stud_inset"] = self.backing_stud_inset
        return data

    def add_features(self) -> None:
        super().add_features()
        self.interface_a.detail_set = TGenericPanelJointDetailSet(edge_index=self.interface_a.edge_index)
        positions, direction = [], None
        if self.backing_studs:
            lines = backing_stud_lines(self.cross_panel, self.main_panel, self.backing_stud_inset)
            if lines is not None:
                positions, direction = lines
        self.interface_b.detail_set = TGenericPanelJointDetailSet(
            edge_index=self.interface_b.edge_index,
            backing_positions=positions,
            backing_direction=direction,
            backing_stud_width=self.backing_stud_width,
        )
