from __future__ import annotations

import math
from typing import Optional

from compas.geometry import Line
from compas.geometry import Vector
from compas.geometry import angle_vectors
from compas.geometry import distance_point_line
from compas_timber.connections import TButtJoint

from timber_design_populator.connections_2d.connection_solver_2d import aabb_overlap
from timber_design_populator.populator_agents.populator_agent import PopulatorAgent
from timber_design_rules import CategoryRule


class BackingStudDetailAgent(PopulatorAgent):
    """Places backing studs on given lines, e.g. under the inside corners of a panel junction.

    Each position plus :attr:`direction` gives a stud line on the element layer (normally the
    core).  The studs are made over-long and trimmed to the plates like ordinary studs.  With
    the panel's layers at hand, the agent also:

    - merges two studs closer than one stud width into one, in the middle;
    - drops a stud within one stud width of a parallel panel edge, which the edge stud already
      backs;
    - removes regular studs that run alongside a backing stud and overlap it (studs crossing
      it, e.g. a horizontal backing stud in a wall, are kept).

    Parameters
    ----------
    positions : list[:class:`~compas.geometry.Point`]
        A point on each stud line, in populator space, at the element layer's mid-height.
    direction : :class:`~compas.geometry.Vector`
        The direction of the studs.
    width : float, optional
        The stud width.  Unset: the populator's ``standard_beam_width``.
    element_layers, trimming_layers, feature, priority, internal_joint_overrides, external_joint_overrides, composite_joint_overrides : optional
        See :class:`~timber_design_populator.PopulatorAgent`.
    """

    NAME = "BackingStudDetailAgent"
    IS_DETAIL = True
    BEAM_CATEGORY_NAMES = ["backing_stud"]
    EXTERNAL_JOINT_RULES = [
        CategoryRule(TButtJoint, "backing_stud", "top_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(TButtJoint, "backing_stud", "bottom_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(TButtJoint, "backing_stud", "edge_stud", mill_depth=10.0, max_distance=1.0),
        CategoryRule(TButtJoint, "backing_stud", "header", mill_depth=10.0, max_distance=1.0),
        CategoryRule(TButtJoint, "backing_stud", "sill", mill_depth=10.0, max_distance=1.0),
    ]
    PARALLEL_TOLERANCE = 0.01  # radians: lines this close to the stud direction count as parallel

    def __init__(self, positions: Optional[list] = None, direction: Optional[Vector] = None, width: Optional[float] = None, **kwargs):
        super().__init__(**kwargs)
        self.positions = list(positions) if positions else []
        self.direction = direction
        self.beam_widths["backing_stud"] = width

    @property
    def __data__(self):
        data = super().__data__
        data["positions"] = self.positions
        data["direction"] = self.direction
        data["width"] = self.beam_widths.get("backing_stud")
        return data

    @property
    def width(self) -> float:
        return self.beam_width("backing_stud")

    def generate_elements_for_layer(self, layer):
        if not self.positions or self.direction is None:
            return [], None
        direction = Vector(*self.direction).unitized()
        width = self.width
        positions = [Vector(*p) for p in self.positions]
        if len(positions) == 2 and (positions[0] - positions[1]).length < width:  # too close for two studs
            positions = [(positions[0] + positions[1]) * 0.5]
        reach = (layer.aabb.xsize + layer.aabb.ysize) * 2.0
        studs = []
        for position in positions:
            if self._backed_by_edge(layer, position, direction, width):
                continue
            line = Line(position - direction * reach, position + direction * reach)
            studs.append(self.beam_from_category(line, "backing_stud", layer))
        return studs, None

    def cull_beam(self, beam) -> bool:
        """Also remove regular studs that run alongside one of these backing studs and overlap it."""
        if super().cull_beam(beam):
            return True
        if beam.attributes.get("category") != "stud":
            return False
        return any(self._parallel(backing, beam) and aabb_overlap(backing, beam) for backing in self.elements_for_layer(beam.parent))

    def _parallel(self, beam_a, beam_b) -> bool:
        angle = angle_vectors(beam_a.centerline.direction, beam_b.centerline.direction)
        return min(angle, math.pi - angle) <= self.PARALLEL_TOLERANCE

    def _backed_by_edge(self, layer, position, direction, width) -> bool:
        """Whether a stud at *position* would lie within *width* of a parallel edge of *layer*."""
        flat = [position[0], position[1], 0.0]
        for segment in layer.outline_a.lines:
            angle = angle_vectors(segment.direction, direction)
            if min(angle, math.pi - angle) > self.PARALLEL_TOLERANCE:
                continue
            edge = Line([segment.start[0], segment.start[1], 0.0], [segment.end[0], segment.end[1], 0.0])
            if distance_point_line(flat, edge) < width:
                return True
        return False
