from typing import Optional

from compas.geometry import Frame
from compas.geometry import Polyline
from compas.geometry import Transformation
from compas.geometry import Vector
from compas.geometry import dot_vectors
from compas_timber.connections import JointTopology
from compas_timber.connections import PlateJoint

from compas_arch.elements import Panel
from compas_arch.panel_features import InterfaceRole
from compas_arch.panel_features import PanelConnectionInterface


def _get_edge_face_outline(panel: Panel, edge_index: int) -> Polyline:
    return Polyline(
        [
            panel.outline_a[edge_index],
            panel.outline_a[edge_index + 1],
            panel.outline_b[edge_index + 1],
            panel.outline_b[edge_index],
            panel.outline_a[edge_index],
        ]
    )


class PanelJoint(PlateJoint):
    """Models a plate to plate interaction.

    Parameters
    ----------
    panel_a : :class:`compas_arch.elements.Panel`
        The first plate.
    panel_b : :class:`compas_arch.elements.Panel`
        The second plate.
    topology : literal(JointTopology)
        The topology in which the plates are connected.
    a_segment_index : int
        The index of the segment in panel_a's outline where the plates are connected.
    b_segment_index : int
        The index of the segment in panel_b's outline where the plates are connected.
    **kwargs : dict, optional
        Additional keyword arguments to pass to the parent class.

    Attributes
    ----------
    panel_a : :class:`compas_arch.elements.Panel`
        The first plate.
    panel_b : :class:`compas_arch.elements.Panel`
        The second plate.
    panels : tuple of :class:`compas_arch.elements.Panel`
        The panels that are connected.
    interface_a : :class:`~compas_arch.panel_features.PanelConnectionInterface`
        The interface of panel_a where it meets panel_b.
    interface_b : :class:`~compas_arch.panel_features.PanelConnectionInterface`
        The interface of panel_b where it meets panel_a.

    """

    INTERFACE_ROLES = (InterfaceRole.NONE, InterfaceRole.NONE)  # roles of panel_a's and panel_b's interfaces

    @property
    def __data__(self) -> dict:
        data = super(PanelJoint, self).__data__
        data["interfaces"] = self.interfaces
        return data

    def __init__(
        self,
        panel_a: Optional[Panel] = None,
        panel_b: Optional[Panel] = None,
        topology: Optional[JointTopology] = None,
        a_segment_index: Optional[int] = None,
        b_segment_index: Optional[int] = None,
        **kwargs,
    ):
        super(PanelJoint, self).__init__(panel_a, panel_b, topology, a_segment_index, b_segment_index, **kwargs)
        self.interface_a = None
        self.interface_b = None

    def __repr__(self) -> str:
        return "PanelJoint({0}, {1}, {2})".format(self.panel_a, self.panel_b, JointTopology.get_name(self.topology))

    @property
    def panels(self) -> tuple[Optional[Panel], Optional[Panel]]:
        return self.elements

    @property
    def panel_a(self) -> Optional[Panel]:
        return self.plate_a

    @property
    def panel_b(self) -> Optional[Panel]:
        return self.plate_b

    @property
    def interfaces(self) -> Optional[list[PanelConnectionInterface]]:
        return [self.interface_a, self.interface_b] if self.interface_a and self.interface_b else None

    def create_interfaces(self) -> tuple[PanelConnectionInterface, PanelConnectionInterface]:
        assert self.panel_a is not None
        assert self.panel_b is not None
        assert self.a_segment_index is not None

        a_interface_polyline = _get_edge_face_outline(self.panel_a, self.a_segment_index)

        frame_a = Frame.from_points(a_interface_polyline.points[0], a_interface_polyline.points[1], a_interface_polyline.points[-2])
        if dot_vectors(frame_a.normal, Vector.from_start_end(self.b_planes[1].point, self.b_planes[0].point)) < 0:
            frame_a = Frame.from_points(a_interface_polyline.points[1], a_interface_polyline.points[0], a_interface_polyline.points[2])
        interface_a = self._create_interface(self.panel_a, self.panel_b, a_interface_polyline, frame_a, self.a_segment_index, self.INTERFACE_ROLES[0])

        if self.b_segment_index is None:  # panel_b is the cross panel and therefor has no edge index
            b_interface_polyline = Polyline(a_interface_polyline[::-1])
        else:
            b_interface_polyline = _get_edge_face_outline(self.panel_b, self.b_segment_index)
        frame_b = Frame.from_points(b_interface_polyline.points[0], b_interface_polyline.points[1], b_interface_polyline.points[-2])
        if dot_vectors(frame_b.normal, Vector.from_start_end(self.b_planes[0].point, self.b_planes[1].point)) < 0:
            frame_b = Frame.from_points(b_interface_polyline.points[1], b_interface_polyline.points[0], b_interface_polyline.points[2])
        interface_b = self._create_interface(self.panel_b, self.panel_a, b_interface_polyline, frame_b, self.b_segment_index, self.INTERFACE_ROLES[1])
        return interface_a, interface_b

    def _create_interface(self, panel, partner, polyline, frame, edge_index, role) -> PanelConnectionInterface:
        """Create *panel*'s interface from its world-space edge face *polyline* and *frame*."""
        return PanelConnectionInterface(
            polyline.transformed(Transformation.from_frame(frame).inverse()),
            frame.transformed(panel.modeltransformation.inverse()),
            edge_index,
            interface_role=role,
        )

    def add_features(self) -> None:
        assert self.panel_a is not None
        assert self.panel_b is not None

        # NOTE: I called this add_features to fit with joint workflow, as interface is the panel equivalent of a joint-generated feature.
        """Add features to the plates based on the joint."""
        self.interface_a, self.interface_b = self.create_interfaces()
        self.panel_a.add_feature(self.interface_a)  # TODO: TypeError: should PanelFeature inherit from Element AND Feature?
        self.panel_b.add_feature(self.interface_b)
        self.features = [self.interface_a, self.interface_b]
