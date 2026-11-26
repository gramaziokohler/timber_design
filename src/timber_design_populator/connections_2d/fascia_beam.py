from __future__ import annotations

from compas.geometry import Frame
from compas.geometry import Vector
from compas.geometry import dot_vectors

from .beam2d import Beam2D


class FasciaBeam(Beam2D):
    """An edge beam rotated about its own axis, so one face lies on a sloped panel edge.

    Its 3D frame is tilted out of the panel plane, so it is not a flat 2D beam.  For the 2D
    logic (topology, splitting, extending) it presents its *footprint*: its section through
    its centerline, parallel to the panel plane (XY).  With the centerline at the layer's
    mid-height, that is where the studs it bounds meet it.

    Parameters
    ----------
    Inherited from :class:`~timber_design_populator.connections_2d.Beam2D`.
    """

    @property
    def footprint_frame(self):
        """The section frame in the panel plane: ``yaxis`` horizontal, perpendicular to the beam."""
        frame = self.frame
        across = Vector(0, 0, 1).cross(frame.xaxis)
        if across.length < 1e-9:
            return frame  # a beam along the panel normal has no footprint direction of its own
        across.unitize()
        if dot_vectors(across, frame.yaxis) < 0:
            across = -across
        return Frame(frame.point, frame.xaxis, across)

    @property
    def footprint_width(self):
        """The width of the section through the centerline, parallel to the panel plane."""
        across = self.footprint_frame.yaxis
        limits = []
        for axis, half in ((self.frame.yaxis, self.width / 2.0), (self.frame.zaxis, self.height / 2.0)):
            component = abs(dot_vectors(across, axis))
            if component > 1e-9:
                limits.append(half / component)
        return 2.0 * min(limits)
