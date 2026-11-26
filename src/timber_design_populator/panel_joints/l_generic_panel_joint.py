from __future__ import annotations

from typing import Optional

from timber_design_arch.connections import PanelLButtJoint

from timber_design_populator.detail_sets.l_generic_panel_joint_detail_set import LGenericPanelJointDetailSet
from timber_design_populator.panel_joints.panel_joint_geometry import backing_stud_lines
from timber_design_populator.panel_joints.panel_joint_geometry import layer_stagger


class LGenericPanelJoint(PanelLButtJoint):
    """An L-butt corner between two panels, with a generic connection detail.

    Shapes the panel envelopes like :class:`~timber_design_arch.connections.PanelLButtJoint`, then
    works out each panel's half of the detail with both panels in view and gives each panel's
    interface an :class:`~timber_design_populator.detail_sets.LGenericPanelJointDetailSet`.

    Parameters
    ----------
    panel_a, panel_b, topology, a_segment_index, b_segment_index : optional
        See :class:`~timber_design_arch.connections.PanelLButtJoint`; panel_a is the main panel.
    stagger_layers : bool, optional
        Stagger the exterior, core and interior layers at the corner: the main panel's core butts
        against the cross panel's core, while the cladding layers wrap the corner.  Both panels
        need all three role layers.  Default ``True``.
    backing_studs : bool, optional
        Add a backing stud to the cross panel under the inside corner.  Default ``False``.
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
        stagger_layers: bool = True,
        backing_studs: bool = False,
        backing_stud_width: Optional[float] = None,
        backing_stud_inset: float = 0.0,
        **kwargs,
    ):
        super().__init__(panel_a, panel_b, topology, a_segment_index, b_segment_index, **kwargs)
        self.stagger_layers = stagger_layers
        self.backing_studs = backing_studs
        self.backing_stud_width = backing_stud_width
        self.backing_stud_inset = backing_stud_inset

    @property
    def __data__(self):
        data = super().__data__
        data["stagger_layers"] = self.stagger_layers
        data["backing_studs"] = self.backing_studs
        data["backing_stud_width"] = self.backing_stud_width
        data["backing_stud_inset"] = self.backing_stud_inset
        return data

    def add_features(self) -> None:
        super().add_features()
        for interface, panel, partner, main in ((self.interface_a, self.main_panel, self.cross_panel, True), (self.interface_b, self.cross_panel, self.main_panel, False)):
            extensions, messages = layer_stagger(panel, partner, interface.edge_index, main) if self.stagger_layers else ([], [])
            positions, direction = [], None
            if self.backing_studs and not main:
                lines = backing_stud_lines(panel, partner, self.backing_stud_inset)
                if lines is not None:
                    positions, direction = lines
            interface.detail_set = LGenericPanelJointDetailSet(
                edge_index=interface.edge_index,
                extensions=extensions,
                backing_positions=positions,
                backing_direction=direction,
                backing_stud_width=self.backing_stud_width,
                messages=messages,
            )
