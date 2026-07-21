from compas.geometry import Line
from compas.geometry import Point
from compas.geometry import Polygon
from compas.geometry import Polyline
from compas.geometry import Translation
from compas.geometry import Vector
from compas.geometry import dot_vectors
from compas_timber.elements import Beam


class AABB2D(object):
    """Lightweight 2D axis-aligned bounding box.

    Stores only ``xmin``, ``xmax``, ``ymin``, ``ymax`` and avoids the
    :class:`~compas.geometry.Box` construction path, which raises a
    ``ZeroDivisionError`` when all input points are coplanar at z=0
    (the typical case for a 2D panel).

    Parameters
    ----------
    xmin, xmax, ymin, ymax : float
    """

    def __init__(self, xmin, xmax, ymin, ymax):
        self.xmin = xmin
        self.xmax = xmax
        self.ymin = ymin
        self.ymax = ymax

    def __bool__(self):
        return True

    @classmethod
    def from_points(cls, points):
        """Return the smallest ``AABB2D`` that contains all *points*."""
        xs = [p.x for p in points]
        ys = [p.y for p in points]
        return cls(min(xs), max(xs), min(ys), max(ys))

    @property
    def points(self):
        """Four corners as :class:`~compas.geometry.Point` objects (CCW from bl)."""
        return [
            Point(self.xmin, self.ymin, 0),
            Point(self.xmax, self.ymin, 0),
            Point(self.xmax, self.ymax, 0),
            Point(self.xmin, self.ymax, 0),
        ]

    @property
    def geometry(self):
        return Polyline(
            [
                Point(self.xmin, self.ymin, 0),
                Point(self.xmax, self.ymin, 0),
                Point(self.xmax, self.ymax, 0),
                Point(self.xmin, self.ymax, 0),
                Point(self.xmin, self.ymin, 0),
            ]
        )


class Beam2D(Beam):
    """A :class:`~compas_timber.elements.Beam` extended with 2D blank geometry.

    Adds lazy properties for the beam's projected blank edges and polygon,
    used by :class:`~timber_design.populators.Beam2DPolylineIntersectionResult` and
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
    edges : tuple of :class:`compas.geometry.Line`
        Both long blank edges as ``(edge_a, edge_b)``, computed together and cached.
    edge_a : :class:`compas.geometry.Line`
        The ``-yaxis`` long blank edge (offset by ``-width/2``).
    edge_b : :class:`compas.geometry.Line`
        The ``+yaxis`` long blank edge (offset by ``+width/2``).
    blank_outline : :class:`compas.geometry.Polyline`
        Closed 2D outline of the blank rectangle (five points, CCW).
    blank_polygon : :class:`compas.geometry.Polygon`
        The 2D footprint of the blank as a four-vertex polygon.
    """

    def __init__(self, frame, length, width, height, **kwargs):
        super().__init__(frame, length, width, height, **kwargs)
        self._blank_outline = None
        self._blank_polygon = None

    # ------------------------------------------------------------------
    # Blank edge properties
    # ------------------------------------------------------------------

    @property
    def edges(self):
        """The two long blank edges as a tuple of :class:`compas.geometry.Line`s."""
        return self.blank_outline.lines

    @property
    def edge_a(self):
        """The ``-yaxis`` long blank edge.

        Returns
        -------
        :class:`compas.geometry.Line`
            Centerline translated by ``-width / 2`` along ``frame.yaxis``.
        """
        return self.edges[0]

    @property
    def edge_b(self):
        """The ``+yaxis`` long blank edge, oriented start→end (same as beam axis).

        ``blank_outline.lines[2]`` runs ``tr→tl`` (CCW outline order); this
        property flips it to ``tl→tr`` so both long edges share the same
        orientation as the centreline.

        Returns
        -------
        :class:`compas.geometry.Line`
            Centerline translated by ``+width / 2`` along ``frame.yaxis``.
        """
        line = self.blank_outline.lines[2]  # tr→tl in CCW outline
        return Line(line.end, line.start)  # flip to tl→tr

    @property
    def start_segment(self):
        """The start cap of the blank (perpendicular to beam axis at the start).

        Returns
        -------
        :class:`compas.geometry.Line`
            ``tl → bl`` edge (blank_outline index 3).
        """
        return self.edges[3]

    @property
    def end_segment(self):
        """The end cap of the blank (perpendicular to beam axis at the end).

        Returns
        -------
        :class:`compas.geometry.Line`
            ``br → tr`` edge (blank_outline index 1).
        """
        return self.edges[1]

    @property
    def aabb(self):
        """The 2D axis-aligned bounding box of the blank rectangle.

        Returns an :class:`AABB2D` rather than a :class:`~compas.geometry.Box`
        to avoid the ``ZeroDivisionError`` that ``Box.from_points`` raises when
        all blank corner points are coplanar at z=0 (a 2D panel).
        """
        return AABB2D.from_points([self.edge_a.start, self.edge_a.end, self.edge_b.start, self.edge_b.end])

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
        if not self._blank_outline:
            origin = self.frame.point
            end = origin + self.frame.xaxis * self.length
            half_y = self.frame.yaxis * (self.width / 2.0)
            bl = origin - half_y
            br = end - half_y
            tr = end + half_y
            tl = origin + half_y
            self._blank_outline = Polyline([bl, br, tr, tl, bl])
        return self._blank_outline

    @property
    def blank_polygon(self):
        """The 2D footprint of the beam blank as a four-vertex polygon.

        Vertices are ordered counter-clockwise: bl, br, tr, tl.

        Returns
        -------
        :class:`compas.geometry.Polygon`
        """
        if not self._blank_polygon:
            origin = self.frame.point
            end = origin + self.frame.xaxis * self.length
            half_y = self.frame.yaxis * (self.width / 2.0)
            self._blank_polygon = Polygon([origin - half_y, end - half_y, end + half_y, origin + half_y])
        return self._blank_polygon

    # ------------------------------------------------------------------
    # Point containment
    # ------------------------------------------------------------------

    def contains_point(self, point, tolerance=0.0):
        """Return ``True`` if *point* lies within (or on) the 2D blank rectangle.

        Uses a fast axis-aligned projection test in the beam's local frame.
        *tolerance* is expanded symmetrically on all four sides so that points
        sitting exactly on a blank edge — or floating-point-epsilon outside it —
        are still considered contained.  This is critical for topology detection:
        a stud end that lands flush against a plate face must register as inside
        the plate blank so ``find_topology`` classifies the joint as ``TOPO_T``
        rather than ``TOPO_X``.

        Parameters
        ----------
        point : :class:`compas.geometry.Point`
        tolerance : float, optional
            Absolute tolerance in model units applied to all four sides.
            Defaults to ``1.0``.

        Returns
        -------
        bool
        """
        vec = Vector.from_start_end(self.frame.point, point)
        along = dot_vectors(vec, self.frame.xaxis)
        perp = dot_vectors(vec, self.frame.yaxis)
        return -tolerance <= along <= self.length + tolerance and -self.width / 2.0 - tolerance <= perp <= self.width / 2.0 + tolerance

    def _invalidate_blank_cache(self):
        """Clear all cached blank geometry so it is recomputed on next access."""
        self._blank_outline = None
        self._blank_polygon = None

    def transform(self, transformation):
        """Transform this beam and invalidate the cached blank geometry."""
        super().transform(transformation)
        self._invalidate_blank_cache()

    def to_beam(self):
        # type: (Beam2D) -> Beam
        """Return a plain :class:`~compas_timber.elements.Beam` with this beam's data.

        Drops the Beam2D-specific blank-outline caching and 2D helper
        properties; frame, dimensions, features and attributes are preserved
        via ``__data__``.

        Returns
        -------
        :class:`~compas_timber.elements.Beam`
        """
        return Beam(**self.__data__)

    def get_beam_segment(self, start_length, end_length):
        # type: (Beam2D, float, float) -> Beam2D
        seg_length = end_length - start_length
        if seg_length <= 0.000001:
            raise ValueError(
                "get_beam_segment called with degenerate range [{}, {}] on beam '{}' (length={})".format(start_length, end_length, self.attributes.get("name", "?"), self.length)
            )
        beam_seg = Beam2D(**self.__data__)
        # copy() deep-copies any cached _blank_outline/_blank_polygon which would
        # be stale after the translate + length change below — clear them first.
        # beam_seg._invalidate_blank_cache()
        beam_seg.transform(Translation.from_vector(self.frame.xaxis * start_length))
        beam_seg.length = seg_length
        for feature in self.features:
            feature.beam = beam_seg  # TODO: check feature position?
        return beam_seg
