from compas_timber.connections import JointTopology
from compas_timber.connections import PlateLButtJoint
from compas_timber.connections import PlateTButtJoint

from timber_design_arch.elements import Panel
from timber_design_arch.panel_features import InterfaceRole

from .panel_joint import PanelJoint


class PanelLButtJoint(PanelJoint, PlateLButtJoint):
    """Creates a plate-to-plate butt-joint connection."""

    SUPPORTED_TOPOLOGY = JointTopology.TOPO_EDGE_EDGE
    INTERFACE_ROLES = (InterfaceRole.MAIN, InterfaceRole.CROSS)

    @property
    def main_panel(self) -> Panel:
        """Return the main plate."""
        return self.plate_a

    @property
    def cross_panel(self) -> Panel:
        """Return the cross plate."""
        return self.plate_b

    def __repr__(self) -> str:
        return "PanelLButtJoint({0}, {1}, {2})".format(self.main_panel, self.cross_panel, JointTopology.get_name(self.topology))


class PanelTButtJoint(PanelJoint, PlateTButtJoint):
    """Creates a plate-to-plate butt-joint connection."""

    SUPPORTED_TOPOLOGY = JointTopology.TOPO_EDGE_FACE
    INTERFACE_ROLES = (InterfaceRole.MAIN, InterfaceRole.CROSS)

    @property
    def main_panel(self) -> Panel:
        """Return the main plate."""
        return self.plate_a

    @property
    def cross_panel(self) -> Panel:
        """Return the cross plate."""
        return self.plate_b

    def __repr__(self) -> str:
        return "PanelTButtJoint({0}, {1}, {2})".format(self.main_panel, self.cross_panel, JointTopology.get_name(self.topology))
