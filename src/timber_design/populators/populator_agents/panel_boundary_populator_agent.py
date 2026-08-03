from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Optional

from compas.geometry import Line
from compas.geometry import Point
from compas.geometry import Vector
from compas.geometry import dot_vectors
from compas_timber.utils import extend_line_segments
from compas_timber.utils import get_polyline_segment_perpendicular_vector
from compas_timber.utils import join_polyline_segments

from timber_design.populators.populator_agents.layer_agent import LayerAgent
from timber_design.populators.populator_agents.populator_agent import AgentBoundaryType

if TYPE_CHECKING:
    from compas.geometry import Polyline  # noqa: F401
    from compas_timber.elements import Layer  # noqa: F401


class PanelBoundaryPopulatorAgent(LayerAgent):
    """Contributes the panel outline as a boundary, without generating any elements.

    Unlike :class:`~timber_design.populators.EdgePopulatorAgent`, this agent
    creates no beams — it exists purely to publish the panel's own outline as
    an :attr:`~AgentBoundaryType.INCLUSIVE` boundary, so that peer agents'
    elements falling outside the panel are split and culled at its edge.

    The boundary is the outer of the two per-segment outlines: for each segment
    of the layer, ``outline_a`` and ``outline_b`` are projected flat and the
    one further from the panel centre is taken, so a chamfered edge is bounded
    by its widest face.

    Parameters
    ----------
    layer : :class:`~compas_timber.elements.Layer` or str, optional
        The layer whose panel outline drives boundary generation, or its path.
    internal_joint_overrides, external_joint_overrides : list, optional
        Per-agent joint-rule overrides, see :class:`PopulatorAgent`.
    """

    NAME = "PanelBoundaryPopulatorAgent"
    BOUNDARY_TYPE = AgentBoundaryType.INCLUSIVE

    def __init__(
        self,
        layer: Optional[Layer | str] = None,
        internal_joint_overrides: Optional[list] = None,
        external_joint_overrides: Optional[list] = None,
        **kwargs,
    ) -> None:
        super().__init__(layer, internal_joint_overrides, external_joint_overrides, **kwargs)

    def generate_layer_elements(self):
        """Generate no elements, contributing only the panel outline as a boundary.

        Returns
        -------
        tuple[list, :class:`~compas.geometry.Polyline`]
            An empty element list and this agent's boundary outline.
        """
        return [], self.generate_boundaries()

    def generate_boundaries(self) -> Polyline:
        """Build the outer boundary polyline from the layer's panel outline.

        Returns
        -------
        :class:`~compas.geometry.Polyline`
        """
        inner_segs = []
        outer_segs = []
        for i in range(len(self.layer.outline_a) - 1):
            inner_seg, outer_seg = self._get_inner_and_outer_segments(i)
            inner_segs.append(inner_seg)
            outer_segs.append(outer_seg)
        extend_line_segments(inner_segs, close_loop=True)
        extend_line_segments(outer_segs, close_loop=True)
        return join_polyline_segments(outer_segs, close_loop=True)[0][0]

    def _get_inner_and_outer_segments(self, segment_index: int) -> tuple[Line, Line]:
        perp_vector = get_polyline_segment_perpendicular_vector(self.layer.outline_a, segment_index)
        seg_a = Line(self.layer.outline_a[segment_index], self.layer.outline_a[segment_index + 1])
        seg_b = Line(self.layer.outline_b[segment_index], self.layer.outline_b[segment_index + 1])

        projected_a = Line(Point(seg_a.start[0], seg_a.start[1], 0), Point(seg_a.end[0], seg_a.end[1], 0))
        projected_b = Line(Point(seg_b.start[0], seg_b.start[1], 0), Point(seg_b.end[0], seg_b.end[1], 0))
        dot = dot_vectors(perp_vector, Vector.from_start_end(seg_a.start, seg_b.start))

        if dot < 0:  # seg_b is closer to the middle
            return projected_b, projected_a
        else:  # seg_a is closer to the middle
            return projected_a, projected_b
