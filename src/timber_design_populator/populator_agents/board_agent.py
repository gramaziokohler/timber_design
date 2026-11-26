from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Optional

from compas.geometry import Line
from compas.geometry import Point
from compas.geometry import Vector
from compas.geometry import dot_vectors
from compas.geometry import is_point_in_polygon_xy

from timber_design_populator.populator_agents.layer_boundary_agent import layer_outer_boundary
from timber_design_populator.populator_agents.populator_agent import PopulatorAgent

if TYPE_CHECKING:
    from timber_design_arch.elements import Layer  # noqa: F401

_TOL = 1e-6


class BoardAgent(PopulatorAgent):
    """Parallel members at a fixed on-centre spacing across a layer: battens, counter-battens, cladding boards, studs.

    The members run along *direction* (in the panel plane) and sit on a grid of
    ``offset + k * spacing`` measured across them from the panel's local origin, not from
    the layer's own extent.  Grids with the same spacing therefore line up from layer to
    layer (battens @ 625 over studs @ 625), however far a layer is extended at its edges.
    A member is placed where its full width lies within the layer, and is clipped to the
    layer's outline.

    Each member is as high as the layer is thick, and is a ``Beam2D`` of :attr:`category`.
    The agent has no joint rules of its own: boards meet nothing in their layer.

    Parameters
    ----------
    layer : :class:`~timber_design_arch.elements.Layer` or tuple, optional
        The layer to fill, or its path.
    board_width : float, optional
        The members' width.  Unset: the populator's ``standard_beam_width``.
    spacing : float, optional
        On-centre spacing.  For cladding, the board width plus the gap.  Unset: eight
        member widths.
    direction : :class:`~compas.geometry.Vector`, optional
        The members' direction in the panel's local XY plane.  Default ``(0, 1, 0)``: the
        panel's y axis, i.e. "up" on a wall (see the panel's orientation).
    offset : float, optional
        Shift of the grid across the members, e.g. ``spacing / 2`` to sit between members
        of another layer.  Default ``0``.
    category : str, optional
        The members' beam category, e.g. ``"batten"`` or ``"cladding"``.  Default ``"board"``.
    internal_joint_overrides, external_joint_overrides : list, optional
        Per-agent joint-rule overrides, see :class:`PopulatorAgent`.

    Attributes
    ----------
    direction : :class:`~compas.geometry.Vector`
    spacing : float or None
    offset : float
    category : str
    """

    NAME = "BoardAgent"
    DEFAULT_CATEGORY = "board"
    CLIP_TO_LAYER = True

    def __init__(
        self,
        layer: Optional[Layer | tuple] = None,
        board_width: Optional[float] = None,
        spacing: Optional[float] = None,
        direction: Optional[Vector] = None,
        offset: float = 0.0,
        category: Optional[str] = None,
        internal_joint_overrides: Optional[list] = None,
        external_joint_overrides: Optional[list] = None,
        **kwargs,
    ) -> None:
        super().__init__(layer=layer, internal_joint_overrides=internal_joint_overrides, external_joint_overrides=external_joint_overrides, **kwargs)
        self.category = category or self.DEFAULT_CATEGORY
        self.BEAM_CATEGORY_NAMES = [self.category]  # per instance: the populator fills widths by category
        self.beam_widths[self.category] = board_width
        self.spacing = spacing
        self.direction = _in_plane_unit(direction)
        self.offset = offset or 0.0

    @property
    def __data__(self):
        data = super().__data__
        data["board_width"] = self.beam_widths.get(self.category)
        data["spacing"] = self.spacing
        data["direction"] = self.direction
        data["offset"] = self.offset
        data["category"] = self.category
        return data

    def generate_elements_for_layer(self, layer):
        """The members on *layer*, at the grid positions within it.

        Returns
        -------
        tuple[list[:class:`~timber_design_populator.connections_2d.Beam2D`], None]
            The members, and no boundary outline.
        """
        width = self.beam_width(self.category)
        spacing = self.spacing if self.spacing is not None else width * 8
        if spacing <= 0:
            raise ValueError(
                "{} requires a positive spacing; got {!r}. Pass an explicit spacing or set the populator's standard_beam_width so the default (width * 8) is positive.".format(
                    type(self).__name__, spacing
                )
            )
        direction = self.direction
        across = direction.cross(Vector(0, 0, 1))  # +x for the default +y direction
        points = list(layer.outline_a.points) + list(layer.outline_b.points)
        lo, hi = _extent(points, across)
        start, end = _extent(points, direction)
        reach = end - start  # members overshoot the layer by its length on both sides, as studs always have
        z = self.layer_center_height
        boundary = layer_outer_boundary(layer) if self.CLIP_TO_LAYER else None

        members = []
        for position in self._positions(lo, hi, spacing, width):
            base = across * position
            line = Line(
                Point(base[0] + direction[0] * (start - reach), base[1] + direction[1] * (start - reach), z),
                Point(base[0] + direction[0] * (end + reach), base[1] + direction[1] * (end + reach), z),
            )
            for segment in _clip_to_polygon(line, boundary) if boundary is not None else [line]:
                members.append(self.beam_from_category(segment, self.category))
        return members, None

    def _positions(self, lo, hi, spacing, width):
        """The grid positions across the members, ``offset + k * spacing``, where a member's full width is within ``[lo, hi]``."""
        k = _ceil((lo + width / 2.0 - self.offset) / spacing - _TOL)
        positions = []
        position = self.offset + k * spacing
        while position + width / 2.0 <= hi + _TOL:
            positions.append(position)
            k += 1
            position = self.offset + k * spacing
        return positions


def _in_plane_unit(direction):
    """*direction* (or panel y) flattened onto the panel plane and unitized."""
    if direction is None:
        return Vector(0, 1, 0)
    flat = Vector(direction[0], direction[1], 0.0)
    if flat.length < _TOL:
        raise ValueError("A BoardAgent direction must lie in the panel plane; got {!r}.".format(direction))
    return flat.unitized()


def _extent(points, axis):
    values = [dot_vectors(point, axis) for point in points]
    return min(values), max(values)


def _ceil(value):
    whole = int(value)
    return whole if whole >= value else whole + 1


def _clip_to_polygon(line, polygon):
    """The parts of *line* inside the closed XY *polygon*, as lines at the line's height."""
    start, end = line.start, line.end
    d = (end[0] - start[0], end[1] - start[1])
    params = {0.0, 1.0}
    pts = polygon.points
    for a, b in zip(pts[:-1], pts[1:]):
        e = (b[0] - a[0], b[1] - a[1])
        denom = d[0] * e[1] - d[1] * e[0]
        if abs(denom) < 1e-12:
            continue
        w = (a[0] - start[0], a[1] - start[1])
        t = (w[0] * e[1] - w[1] * e[0]) / denom
        u = (w[0] * d[1] - w[1] * d[0]) / denom
        if -_TOL <= u <= 1 + _TOL and 0.0 < t < 1.0:
            params.add(t)
    params = sorted(params)
    xy = [(p[0], p[1]) for p in pts]
    pieces = []
    for t0, t1 in zip(params[:-1], params[1:]):
        if t1 - t0 < 1e-9:
            continue
        mid = ((t0 + t1) / 2.0) * d[0] + start[0], ((t0 + t1) / 2.0) * d[1] + start[1]
        if not is_point_in_polygon_xy(mid, xy):
            continue
        if pieces and abs(pieces[-1][1] - t0) < 1e-9:
            pieces[-1][1] = t1  # merge pieces split at a vertex
        else:
            pieces.append([t0, t1])
    return [Line(line.point_at(t0), line.point_at(t1)) for t0, t1 in pieces]
