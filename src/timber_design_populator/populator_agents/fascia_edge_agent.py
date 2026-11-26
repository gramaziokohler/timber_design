from __future__ import annotations

import math
from typing import Optional

from compas.geometry import Line
from compas.geometry import Plane
from compas.geometry import Vector
from compas.geometry import dot_vectors
from compas_timber.fabrication import LongitudinalCutProxy
from compas_timber.utils import get_polyline_segment_perpendicular_vector

from timber_design_populator.connections_2d.fascia_beam import FasciaBeam
from timber_design_populator.populator_agents.edge_agent import EdgeAgent


class FasciaEdgeAgent(EdgeAgent):
    """An :class:`EdgeAgent` that puts angled fascia beams on the sloped edges of the panel.

    On an edge whose edge plane is perpendicular to the panel, the edge beam is the same as
    :class:`EdgeAgent`'s.  On a sloped edge (e.g. the plumb-cut eave of a roof panel) the beam
    is a :class:`~timber_design_populator.connections_2d.FasciaBeam`: rotated about its axis so
    its outer face lies on the edge plane, as wide as its category width, and high enough to
    cover the layer's thickness on both of its faces, so it is higher than the layer is thick.
    Its inner face is sloped too, so the studs and other beams butted against it get angled
    jack rafter cuts from the usual joint rules.

    Parameters
    ----------
    layer, edge_stud_width, top_plate_beam_width, bottom_plate_beam_width, internal_joint_overrides, external_joint_overrides, standard_beam_width_increment : optional
        See :class:`EdgeAgent`.  With *standard_beam_width_increment*, a fascia's height is
        rounded up to it as well.
    flush_cuts : bool, optional
        Cut each fascia flush with the layer's two faces with longitudinal cuts, removing what
        overhangs them.  Default ``False``.
    """

    NAME = "FasciaEdgeAgent"

    def __init__(
        self,
        layer=None,
        edge_stud_width: Optional[float] = None,
        top_plate_beam_width: Optional[float] = None,
        bottom_plate_beam_width: Optional[float] = None,
        internal_joint_overrides=None,
        external_joint_overrides=None,
        standard_beam_width_increment=None,
        flush_cuts: bool = False,
        **kwargs,
    ):
        super().__init__(
            layer=layer,
            edge_stud_width=edge_stud_width,
            top_plate_beam_width=top_plate_beam_width,
            bottom_plate_beam_width=bottom_plate_beam_width,
            internal_joint_overrides=internal_joint_overrides,
            external_joint_overrides=external_joint_overrides,
            standard_beam_width_increment=standard_beam_width_increment,
            **kwargs,
        )
        self.flush_cuts = flush_cuts

    @property
    def __data__(self):
        data = super().__data__
        data["flush_cuts"] = self.flush_cuts
        return data

    # ------------------------------------------------------------------
    # edge beams
    # ------------------------------------------------------------------

    def _edge_beam_line_and_width(self, segment_index):
        if self._edge_plane_is_perpendicular(segment_index):
            return super()._edge_beam_line_and_width(segment_index)
        width = self._rounded(self.beam_width(self._get_segment_category(segment_index)))
        normal, along_plane = self._fascia_axes(segment_index)
        seg_a = self.layer.outline_a.lines[segment_index]
        seg_b = self.layer.outline_b.lines[segment_index]
        # the edge at the layer's mid-height, on the edge plane
        start = (Vector(*seg_a.start) + Vector(*seg_b.start)) * 0.5
        end = (Vector(*seg_a.end) + Vector(*seg_b.end)) * 0.5
        # the centre of the fascia section, still at mid-height: half the width in from the edge
        # plane, moved along the plane so it stays level
        shift = normal * (-width / 2.0) + along_plane * (width / 2.0 * normal[2] / along_plane[2])
        return Line(start + shift, end + shift), width

    def _edge_beam(self, segment_index, centerline, width):
        if self._edge_plane_is_perpendicular(segment_index):
            return super()._edge_beam(segment_index, centerline, width)
        normal, along_plane = self._fascia_axes(segment_index)
        thickness = self.layer.thickness
        height = self._rounded((thickness + width * abs(normal[2])) / abs(along_plane[2]))
        fascia = FasciaBeam.from_centerline(
            centerline,
            width=width,
            height=height,
            z_vector=along_plane,
            edge_index=segment_index,
            category=self._get_segment_category(segment_index),
        )
        if self.flush_cuts:
            face_a, face_b = self.layer.planes
            for plane in (Plane(face_a.point, -face_a.normal), Plane(face_b.point, face_b.normal)):  # normals point away from the layer
                fascia.add_features(LongitudinalCutProxy.from_plane_and_beam(plane, fascia, is_joinery=False))
        return fascia

    def _fascia_axes(self, segment_index):
        """The outward edge-plane normal and the direction up the edge plane, perpendicular to the edge."""
        plane = self.layer.edge_planes[segment_index]
        outward = get_polyline_segment_perpendicular_vector(self.layer.outline_a, segment_index)
        normal = Vector(*plane.normal).unitized()
        if dot_vectors(normal, outward) < 0:
            normal = -normal
        direction = self.layer.outline_a.lines[segment_index].direction
        along_plane = normal.cross(Vector(*direction)).unitized()
        if along_plane[2] < 0:
            along_plane = -along_plane
        return normal, along_plane

    def _rounded(self, value):
        if self.standard_beam_width_increment:
            return math.ceil(value / self.standard_beam_width_increment) * self.standard_beam_width_increment
        return value
