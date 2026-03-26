from compas.geometry import Line
from compas.geometry import Point
from compas.geometry import Polygon
from compas.geometry import Polyline
from compas.geometry import Vector
from compas.geometry import dot_vectors
from compas_timber.elements import Beam


class Beam2D(Beam):
    """A :class:`~compas_timber.elements.Beam` extended with 2D blank geometry.

    Adds lazy properties for the beam's projected blank edges and polygon,
    used by :class:`~timber_design.populators.BeamGeneratorIntersection` and
    :meth:`~timber_design.populators.Model2D.connect_adjacent_beams` for intersection
    detection and classification.

    All geometry is expressed in the beam's own local XY plane (the panel
    plane), where ``frame.xaxis`` runs along the centerline and ``frame.yaxis``
    is the width direction.

    Parameters
    ----------
    Inherited from :class:`~compas_timber.elements.Beam`.

    Properties
    ----------
    blank_a : :class:`compas.geometry.Line`
        The ``-yaxis`` long blank edge (offset by ``-width/2``).
    blank_b : :class:`compas.geometry.Line`
        The ``+yaxis`` long blank edge (offset by ``+width/2``).
    blank_outline : :class:`compas.geometry.Polyline`
        Closed 2D outline of the blank rectangle (five points, CCW).
    blank_polygon : :class:`compas.geometry.Polygon`
        The 2D footprint of the blank as a four-vertex polygon.
    """

    @classmethod
    def from_centerline(cls, centerline, width, height, z_vector=None):
        """Create a :class:`Beam2D` from a centerline.

        Delegates to :meth:`compas_timber.elements.Beam.from_centerline` and
        promotes the result to :class:`Beam2D` in-place.

        Parameters
        ----------
        centerline : :class:`compas.geometry.Line`
        width : float
        height : float
        z_vector : :class:`compas.geometry.Vector`, optional

        Returns
        -------
        :class:`Beam2D`
        """
        instance = Beam.from_centerline(centerline, width=width, height=height, z_vector=z_vector)
        instance.__class__ = cls
        return instance

    # ------------------------------------------------------------------
    # Blank edge properties
    # ------------------------------------------------------------------

    @property
    def blank_a(self):
        """The ``-yaxis`` long blank edge.

        Returns
        -------
        :class:`compas.geometry.Line`
            Centerline translated by ``-width / 2`` along ``frame.yaxis``.
        """
        return self.centerline.translated(self.frame.yaxis * -self.width / 2.0)

    @property
    def blank_b(self):
        """The ``+yaxis`` long blank edge.

        Returns
        -------
        :class:`compas.geometry.Line`
            Centerline translated by ``+width / 2`` along ``frame.yaxis``.
        """
        return self.centerline.translated(self.frame.yaxis * self.width / 2.0)

    @property
    def blank_outline(self):
        """The closed 2D outline of the beam blank as a :class:`~compas.geometry.Polyline`.

        Vertices are ordered counter-clockwise starting from the ``-yaxis``
        corner so that :attr:`~compas.geometry.Polyline.lines` yields edges in
        the same sequence used by adjacency-based classification (CORNER,
        NOTCH)::

            3 ← (start cap)     tl ┌────────────┐ tr
                                   │            │
            0 → (bottom, -y)    bl └────────────┘ br   start→end
                                                1 (end cap, bl→tl)
            2 ← (top, +y)       tr ┌────────────┐ tl   end→start

        ``outline.lines[i]`` is adjacent to ``outline.lines[(i ± 1) % 4]``.

        Returns
        -------
        :class:`compas.geometry.Polyline`
            Closed five-point polyline ``[bl, br, tr, tl, bl]``.
        """
        origin = self.frame.point
        end = origin + self.frame.xaxis * self.length
        half_y = self.frame.yaxis * (self.width / 2.0)
        bl = origin - half_y
        br = end - half_y
        tr = end + half_y
        tl = origin + half_y
        return Polyline([bl, br, tr, tl, bl])

    @property
    def blank_polygon(self):
        """The 2D footprint of the beam blank as a four-vertex polygon.

        Vertices are ordered counter-clockwise: bl, br, tr, tl.

        Returns
        -------
        :class:`compas.geometry.Polygon`
        """
        origin = self.frame.point
        end = origin + self.frame.xaxis * self.length
        half_y = self.frame.yaxis * (self.width / 2.0)
        return Polygon([origin - half_y, end - half_y, end + half_y, origin + half_y])

    # ------------------------------------------------------------------
    # Point containment
    # ------------------------------------------------------------------

    def contains_point(self, point):
        """Return ``True`` if *point* lies within the 2D blank rectangle.

        Uses a fast axis-aligned projection test in the beam's local frame.
        The ``tolerance`` is applied symmetrically to all four sides so that
        points on or very near a blank edge are included.

        Parameters
        ----------
        point : :class:`compas.geometry.Point`
        tolerance : float, optional
            Absolute tolerance in model units.  Defaults to ``1.0``.

        Returns
        -------
        bool
        """
        vec = Vector.from_start_end(self.frame.point, point)
        along = dot_vectors(vec, self.frame.xaxis)
        perp = dot_vectors(vec, self.frame.yaxis)
        return (
            0 <= along <= self.length
            and -self.width / 2.0 <= perp <= self.width / 2.0 
        )
