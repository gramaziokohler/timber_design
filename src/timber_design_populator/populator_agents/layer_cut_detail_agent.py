from __future__ import annotations

from typing import Optional

from compas.geometry import Line
from compas.geometry import Polyline
from compas.geometry import intersection_line_plane
from compas.itertools import pairwise
from compas_timber.elements import Plate
from compas_timber.fabrication.free_contour import FreeContour
from compas_timber.utils import is_point_in_polyline

from timber_design_populator.connections_2d.beam2d import Beam2D
from timber_design_populator.connections_2d.connection_solver_2d import ConnectionSolver2D

from timber_design_populator.populator_agents.populator_agent import AgentBoundaryType
from timber_design_populator.populator_agents.populator_agent import PopulatorAgent
from timber_design_populator.populator_agents.void_geometry import frame_boundary
from timber_design_populator.populator_agents.void_geometry import frame_through_outlines
from timber_design_populator.populator_agents.void_geometry import lies_on_plane
from timber_design_populator.populator_agents.void_geometry import project_to_layer_midplane
from timber_design_populator.populator_agents.void_geometry import project_to_plane


class LayerCutDetailAgent(PopulatorAgent):
    """Cuts a void into one layer and its sublayers: splits and removes beams, and cuts plates.

    Creates no elements.  On every layer it trims (its layer and the sublayers below it):

    - **beams** (e.g. battens, cladding boards) are split at the cut and every piece that
      overlaps it is removed, unless *cut_beams* is off.  A beam the cut's edge runs along
      (a board straddling an opening's top or bottom) loses the piece alongside the cut, in any
      direction.  The boundary is the cut prism between *outline_a* and *outline_b* at the layer's
      mid-height, or else *outline_a* projected onto the layer's mid-plane;
    - **plates** are cut: through by the prism between *outline_a* and *outline_b*; or, with
      *outline_a* alone, through along *outline_a* projected onto the layer face (no *depth*), or
      as a blind pocket *depth* deep into the plate whose face *outline_a* lies on.

    Parameters
    ----------
    layer : :class:`~timber_design_arch.elements.Layer` or tuple, optional
        The layer to cut (its sublayers are cut too).  Sets the trimming layers only: the agent
        creates nothing.
    outline_a : :class:`~compas.geometry.Polyline`
        The cut outline, in populator space.
    outline_b : :class:`~compas.geometry.Polyline`, optional
        Makes the cut a prism between *outline_a* and *outline_b* (corresponding points), e.g.
        an opening through the whole panel.
    depth : float, optional
        Without *outline_b*: ``None`` cuts through, a depth cuts a blind pocket.
    cut_beams : bool, optional
        Split and remove beams at the cut.  Off where another agent already bounds the beams
        (e.g. the framing of an opening in the core).  Default ``True``.
    bottom_offset : float, optional
        With *outline_b*: how far the beam boundary reaches below the cut, e.g. so a door's cut
        also removes the beams at its bottom edge.  Default ``0``.
    trimming_layers, feature, priority, internal_joint_overrides, external_joint_overrides, composite_joint_overrides : optional
        See :class:`~timber_design_populator.PopulatorAgent`.
    """

    NAME = "LayerCutDetailAgent"
    IS_DETAIL = True
    BOUNDARY_TYPE = AgentBoundaryType.EXCLUSIVE

    def __init__(
        self,
        layer=None,
        outline_a: Optional[Polyline] = None,
        outline_b: Optional[Polyline] = None,
        depth: Optional[float] = None,
        cut_beams: bool = True,
        bottom_offset: float = 0.0,
        trimming_layers=None,
        **kwargs,
    ):
        kwargs.pop("element_layers", None)  # a cut creates nothing
        if layer is not None and trimming_layers is None:
            trimming_layers = [layer]
        super().__init__(trimming_layers=trimming_layers, **kwargs)
        self.outline_a = outline_a
        self.outline_b = outline_b
        self.depth = depth
        self.cut_beams = cut_beams
        self.bottom_offset = bottom_offset

    @property
    def __data__(self):
        data = super().__data__
        data.pop("element_layers", None)
        data["outline_a"] = self.outline_a
        data["outline_b"] = self.outline_b
        data["depth"] = self.depth
        data["cut_beams"] = self.cut_beams
        data["bottom_offset"] = self.bottom_offset
        return data

    def compute_outline_for_layer(self, layer):
        if not self.cut_beams or self.outline_a is None:
            return None
        if self.outline_b is not None:
            frame_a, frame_b = frame_through_outlines(self.outline_a, self.outline_b, layer)
            return frame_boundary(frame_a, frame_b, layer.center_height, self.bottom_offset)
        return project_to_layer_midplane(self.outline_a, layer)

    #: How far into a beam's width its edges are tested against the cut: a beam merely
    #: touching the cut is kept.
    OVERLAP_TOLERANCE = 1.0

    def split_beam(self, beam: Beam2D) -> list:
        """Split *beam* at both ends of every stretch where the cut's outline crosses or runs inside its blank.

        Unlike the base split, a cut edge running along the beam (inside its width) gives a piece
        of its own, so :meth:`cull_beam` can remove it.
        """
        outline = self.outline_for_layer(beam.parent)
        if outline is None:
            return [beam]
        crossings = ConnectionSolver2D.intersection_beam2d_polyline(beam, outline)
        if not crossings:
            return [beam]
        cuts = {0.0, beam.length}
        for crossing in crossings:
            for dot in (min(crossing.all_dots), max(crossing.all_dots)):
                cuts.add(min(max(dot, 0.0), beam.length))
        segments = [beam.get_beam_segment(start, end) for start, end in pairwise(sorted(cuts)) if end - start > 1e-6]
        return segments if len(segments) > 1 else [beam]

    def cull_beam(self, beam: Beam2D) -> bool:
        """Remove *beam* if any part of its width overlaps the cut, not only its centerline."""
        outline = self.outline_for_layer(beam.parent)
        if outline is None:
            return False
        center = beam.centerline.midpoint
        points = [center]
        for index in (0, 2):  # the blank's long edges, pulled in by the tolerance
            edge_mid = beam.blank_outline.lines[index].midpoint
            inward = center - edge_mid
            if inward.length > 2 * self.OVERLAP_TOLERANCE:
                points.append(edge_mid + inward.unitized() * self.OVERLAP_TOLERANCE)
        return any(is_point_in_polyline(point, outline, in_plane=False) for point in points)

    def trim_plate(self, plate: Plate) -> None:
        if self.outline_a is None:
            return
        layer = plate.parent
        if self.outline_b is not None:
            lines = [Line(a, b) for a, b in zip(self.outline_a.points, self.outline_b.points)]
            top = Polyline([intersection_line_plane(line, plate.planes[0]) for line in lines])
            bottom = Polyline([intersection_line_plane(line, plate.planes[1]) for line in lines])
            plate.add_feature(FreeContour.from_top_bottom_and_elements(top, bottom, plate, interior=True, is_joinery=False))
        elif self.depth is None:
            # projected onto this plate's layer face, so plates on every sublayer are cut through
            outline = project_to_plane(self.outline_a, layer.planes[0], layer.normal)
            plate.add_feature(FreeContour.from_polyline_and_element(outline, plate, depth=plate.thickness, interior=True))
        elif any(lies_on_plane(self.outline_a, plane) for plane in layer.planes):
            # a blind pocket starts at the face the outline lies on; other plates are left alone
            plate.add_feature(FreeContour.from_polyline_and_element(self.outline_a, plate, depth=self.depth, interior=True))
