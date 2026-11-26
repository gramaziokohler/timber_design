from compas.geometry import Frame
from compas.geometry import Polyline

from .panel_features import PanelFeature
from .panel_features import PanelFeatureType


class LinearService(PanelFeature):
    """A manually routed linear service (electrical or plumbing run): a path and a diameter.

    The feature does not modify the panel.  How the framing it crosses is machined (drilled
    through or notched) is a construction decision, made by whatever builds the feature
    (e.g. a populator detail set).

    Parameters
    ----------
    frame : :class:`~compas.geometry.Frame`
        The feature frame, in the coordinates of the containing panel.
    polyline : :class:`~compas.geometry.Polyline`
        The service path, in the coordinates of *frame*.
    thickness : float
        The diameter of the service.
    """

    def __init__(self, frame: Frame, polyline: Polyline, thickness: float, name="LinearService", **kwargs):
        if thickness <= 0:
            raise ValueError("Linear service thickness must be greater than zero.")
        super(LinearService, self).__init__(frame=frame, panel_feature_type=PanelFeatureType.LINEAR, name=name, **kwargs)
        self._polyline = polyline
        self.thickness = thickness

    @property
    def polyline(self) -> Polyline:
        return self._polyline.transformed(self.transformation)

    @property
    def geometry(self) -> Polyline:
        return self.polyline

    @property
    def __data__(self) -> dict:
        data = super(LinearService, self).__data__
        data["polyline"] = self._polyline
        data["thickness"] = self.thickness
        return data

    def compute_elementgeometry(self, include_features=False) -> Polyline:
        return self._polyline
