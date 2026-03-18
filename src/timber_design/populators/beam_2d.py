from compas_timber.elements import Beam
from compas.geometry import Polygon
from compas.geometry import is_point_in_polygon_xy

class Beam2D(Beam):
    """A 2D beam element.
    Parameters
    ----------
    centerline : :class:`compas.geometry.Line`
        The centerline of the beam.
    width : float
        The width of the beam.
    height : float
        The height of the beam.
    kwargs : dict, optional
        Additional keyword arguments.
    """
    def __init__(self, centerline, width, height, **kwargs):
        super(Beam2D, self).from_centerline(centerline, width, height, **kwargs)
        self._edges = None
        self._polygon = None

    @property
    def edges(self):
        if self._edges is None:
            offset_vector = self.width / 2 * self.frame.yaxis
            self._edges.append(self.centerline.translated(offset_vector))
            self._edges.append(self.centerline.translated(-offset_vector))
        return self._edges

    @property
    def polygon(self):
        if self._polygon is None:

            self._polygon = Polygon([
                self.edges[0].start,
                self.edges[0].end,
                self.edges[1].end,
                self.edges[1].start
                ])
        return self._polygon

    def is_point_inside_beam(self, point):
        """Check if a point is inside the beam.
        Parameters
        ----------
        point : :class:`compas.geometry.Point`
            The point to check.
        Returns
        -------
        bool
            True if the point is inside the beam, False otherwise.
        """
        return is_point_in_polygon_xy(point, self.polygon)
