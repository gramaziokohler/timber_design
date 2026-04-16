from dataclasses import dataclass

from compas.geometry import Line
from compas.geometry import Point
from compas.geometry import Vector
from compas.geometry import dot_vectors

try:
    from compas_timber.utils import extend_line_segments
except ImportError:

    def extend_line_segments(segments, close_loop=False):
        raise NotImplementedError("extend_line_segments is not available in this version of compas_timber")


try:
    from compas_timber.utils import get_interior_corner_indices
    from compas_timber.utils import get_polyline_segment_perpendicular_vector
    from compas_timber.utils import join_polyline_segments
except ImportError:

    def get_interior_corner_indices(*args, **kwargs):
        raise NotImplementedError("get_interior_corner_indices is not available in this version of compas_timber")

    def get_polyline_segment_perpendicular_vector(*args, **kwargs):
        raise NotImplementedError("get_polyline_segment_perpendicular_vector is not available in this version of compas_timber")

    def join_polyline_segments(*args, **kwargs):
        raise NotImplementedError("join_polyline_segments is not available in this version of compas_timber")

from timber_design.populators import FeatureBoundaryType
from timber_design.populators import PopulatorAgent
from timber_design.populators import PopulatorAgentConfig
from timber_design.populators.beam2d import AABB2D


@dataclass
class PanelBoundaryPopulatorAgentConfig(PopulatorAgentConfig):

    @property
    def __data__(self):
        data = super().__data__
        return data


class PanelBoundaryPopulatorAgent(PopulatorAgent):
    """Generates edge beams (plates and edge studs) along the panel outline.

    Creates one :class:`~timber_design.populators.Beam2D` per segment of the
    panel outline.  Each beam's width is derived from the depth of the panel
    chamfer at that edge (the distance between ``outline_a`` and ``outline_b``
    projected onto the outward normal).  An optional *minimum width* and
    *width increment* allow widths to be snapped to standard lumber sizes.

    Beam categories are assigned automatically:

    - ``"top_plate_beam"`` — horizontal edge whose outward normal points in
      the ``+Y`` direction.
    - ``"bottom_plate_beam"`` — horizontal edge whose outward normal points
      in the ``-Y`` direction.
    - ``"edge_stud"`` — vertical edges.

    The agent's :attr:`~PopulatorAgent.outline` is the innermost boundary
    formed by all edge-beam inner faces.  Its
    :attr:`~PopulatorAgent.BOUNDARY_TYPE` is
    :attr:`~FeatureBoundaryType.INCLUSIVE`, meaning that elements from other
    agents that fall outside this outline are discarded.

    Parameters
    ----------
    layer : :class:`~timber_design.populators.Layer`
        The layer whose panel outline drives boundary generation.
    params : :class:`PanelBoundaryPopulatorAgentConfig`
        Agent configuration.

    Attributes
    ----------
    standard_beam_width_increment : float or None
        When set, edge-beam widths are rounded up to the next multiple of
        this value.
    edge_beam_min_width : float
        Minimum edge-beam width (default ``0.0``).
    """

    NAME = "PanelBoundaryPopulatorAgent"
    BOUNDARY_TYPE = FeatureBoundaryType.INCLUSIVE

    def __init__(
        self,
        layer: "Layer",
        params: PanelBoundaryPopulatorAgentConfig,
    ) -> None:
        super(PanelBoundaryPopulatorAgent, self).__init__(layer, params)


    # ==========================================================================
    # private methods for creating edge beams
    # ==========================================================================
    def generate_elements(self):
        pass

    def generate_boundaries(self) -> None:
        """Get the edge beams for the outer polyline of the panel."""
        inner_segs = []
        outer_segs = []
        for i in range(len(self.panel.outline_a) - 1):
            inner_seg, outer_seg = self._get_inner_and_outer_segments(i)
            inner_segs.append(inner_seg)
            outer_segs.append(outer_seg)
        extend_line_segments(inner_segs, close_loop=True)
        extend_line_segments(outer_segs, close_loop=True)
        self.outline = join_polyline_segments(inner_segs, close_loop=True)[0][0]

    def _get_inner_and_outer_segments(self, segment_index) -> tuple[Line, float]:
        perp_vector = get_polyline_segment_perpendicular_vector(self.panel.outline_a, segment_index)
        seg_a = Line(self.panel.outline_a[segment_index], self.panel.outline_a[segment_index + 1])
        seg_b = Line(self.panel.outline_b[segment_index], self.panel.outline_b[segment_index + 1])

        projected_a = Line(Point(seg_a.start[0], seg_a.start[1], 0), Point(seg_a.end[0], seg_a.end[1], 0))
        projected_b = Line(Point(seg_b.start[0], seg_b.start[1], 0), Point(seg_b.end[0], seg_b.end[1], 0))
        dot = dot_vectors(perp_vector, Vector.from_start_end(seg_a.start, seg_b.start))

        if dot < 0:  # seg_b is closer to the middle
            return projected_b, projected_a
        else:  # seg_a is closer to the middle
            return projected_a, projected_b

    @property
    def aabb(self):
        """Get the axis-aligned bounding box of the agent's outline."""
        if not self.outline:
            self.generate_boundaries()
        aabb2d = AABB2D.from_points(self.outline.points)
        return aabb2d




# Set after both classes are defined so forward reference is resolved
PanelBoundaryPopulatorAgentConfig.AGENT_TYPE = PanelBoundaryPopulatorAgent
