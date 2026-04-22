import math
from dataclasses import dataclass
from typing import Optional

from compas.geometry import Line
from compas.geometry import Plane
from compas.geometry import Point
from compas.geometry import Vector
from compas.geometry import angle_vectors
from compas.geometry import dot_vectors
from compas.geometry import intersection_plane_plane
from compas.tolerance import TOL
from compas_timber.connections import LButtJoint
from compas_timber.connections import LMiterJoint
from compas_timber.connections import beam_ref_side_incidence
from compas_timber.fabrication import LongitudinalCutProxy
from compas_timber.utils import extend_line_segments
from compas_timber.utils import get_interior_corner_indices
from compas_timber.utils import get_polyline_segment_perpendicular_vector
from compas_timber.utils import join_polyline_segments

from timber_design.populators.beam2d import Beam2D
from timber_design.populators.layer import Layer
from timber_design.populators.populator_agents.layer_agent import AgentBoundaryType
from timber_design.populators.populator_agents.layer_agent import LayerAgent
from timber_design.populators.populator_agents.layer_agent import LayerAgentConfig
from timber_design.workflow import CategoryRule
from timber_design.workflow import DirectRule


@dataclass
class EdgePopulatorAgentConfig(LayerAgentConfig):
    standard_beam_width_increment: Optional[float] = None
    edge_beam_min_width: Optional[float] = None

    @property
    def __data__(self):
        data = super().__data__
        data["standard_beam_width_increment"] = self.standard_beam_width_increment
        data["edge_beam_min_width"] = self.edge_beam_min_width
        return data


class EdgePopulatorAgent(LayerAgent):
    """Generates edge beams (plates and edge studs) along the panel outline.

    Creates one :class:`~timber_design.populators.Beam2D` per segment of the
    panel outline (``layer.panel.outline_a``).  Each beam's width is derived
    from the depth of the panel chamfer at that edge (the distance between
    ``outline_a`` and ``outline_b`` projected onto the outward normal).  An
    optional *minimum width* and *width increment* allow widths to be snapped
    to standard lumber sizes.

    Beam categories are assigned automatically:

    - ``"top_plate_beam"`` — horizontal edge whose outward normal points in
      the ``+Y`` direction.
    - ``"bottom_plate_beam"`` — horizontal edge whose outward normal points
      in the ``-Y`` direction.
    - ``"edge_stud"`` — vertical edges.

    The agent's :attr:`~LayerAgent.outline` is the innermost boundary
    formed by all edge-beam inner faces.  Its
    :attr:`~LayerAgent.BOUNDARY_TYPE` is
    :attr:`~FeatureBoundaryType.INCLUSIVE`, meaning that elements from other
    agents that fall outside this outline are discarded during
    :meth:`~timber_design.populators.PanelPopulator.trim_within_layer_elements`.

    Parameters
    ----------
    layer : :class:`~timber_design.populators.Layer`
        The layer whose panel outline drives edge-beam placement.
        ``layer.panel`` provides the outline geometry; ``layer.layer_index``
        governs cross-layer trimming.
    params : :class:`EdgePopulatorAgentConfig`
        Controls optional standard-width rounding and minimum beam width.

    Attributes
    ----------
    standard_beam_width_increment : float or None
        When set, edge-beam widths are rounded up to the next multiple of
        this value.
    edge_beam_min_width : float
        Minimum edge-beam width (default ``0.0``).
    """

    BEAM_CATEGORY_NAMES = ["edge_stud", "top_plate_beam", "bottom_plate_beam"]
    NAME = "EdgePopulatorAgent"
    INTERNAL_RULES = [
        CategoryRule(LButtJoint, "edge_stud", "edge_stud", mill_depth=10.0, max_distance=1.0),
        CategoryRule(LButtJoint, "edge_stud", "top_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(LButtJoint, "edge_stud", "bottom_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(LButtJoint, "top_plate_beam", "top_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(LButtJoint, "top_plate_beam", "bottom_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(LButtJoint, "bottom_plate_beam", "bottom_plate_beam", mill_depth=10.0, max_distance=1.0),
    ]
    BOUNDARY_TYPE = AgentBoundaryType.INCLUSIVE

    def __init__(self, layer, params):
        # type: (Layer, EdgePopulatorAgentConfig) -> None
        super(EdgePopulatorAgent, self).__init__(layer, params)
        self.standard_beam_width_increment = params.standard_beam_width_increment
        self.edge_beam_min_width = params.edge_beam_min_width or 0.0

    # ==========================================================================
    # private methods for creating edge beams
    # ==========================================================================

    def generate_elements(self) -> None:
        """Get the edge beams for the outer polyline of the panel."""
        segs, widths = [], []
        for i in range(len(self.panel.outline_a) - 1):
            seg, width = self._get_edge_beam_line_and_width(i, min_width=self.edge_beam_min_width, edge_beam_dim_increment=self.standard_beam_width_increment)
            segs.append(seg)
            widths.append(width)
        extend_line_segments(segs, close_loop=True)
        edges: list[Line] = []  # boundaries of this agent
        for i, (seg, width) in enumerate(zip(segs, widths)):
            edge_beam = Beam2D.from_centerline(seg, width=width, height=self.panel.thickness, z_vector=Vector(0, 0, 1), edge_index=i)
            self._set_edge_beam_category(edge_beam, i)
            self._apply_linear_cut_to_edge_beam(edge_beam, i)
            self.elements.append(edge_beam)
            vector = get_polyline_segment_perpendicular_vector(self.panel.outline_a, i)
            edges.append(seg.translated(vector * (-edge_beam.width / 2)))
        extend_line_segments(edges, close_loop=True)
        self.outline = join_polyline_segments(edges, close_loop=True)[0][0]

    def _get_edge_beam_line_and_width(self, segment_index, min_width=0.0, edge_beam_dim_increment=None) -> tuple[Line, float]:
        perp_vector = get_polyline_segment_perpendicular_vector(self.panel.outline_a, segment_index)
        seg_a = self.panel.outline_a.lines[segment_index]
        seg_b = self.panel.outline_b.lines[segment_index]
        dot = dot_vectors(perp_vector, Vector.from_start_end(seg_a.start, seg_b.start))
        z = self.layer_center_height
        if TOL.is_zero(dot):  # edges are perpendicular to panel
            outer_segment = Line(Point(seg_a.start[0], seg_a.start[1], z), Point(seg_a.end[0], seg_a.end[1], z))
            width = min_width
            offset = width / 2
        else:
            if dot < 0:  # seg_b is closer to the middle
                outer_segment = Line(Point(seg_a.start[0], seg_a.start[1], z), Point(seg_a.end[0], seg_a.end[1], z))
            else:  # seg_a is closer to the middle
                outer_segment = Line(Point(seg_b.start[0], seg_b.start[1], z), Point(seg_b.end[0], seg_b.end[1], z))
            if not edge_beam_dim_increment:
                width = abs(dot) + min_width
                offset = width / 2
            else:
                width = math.ceil((abs(dot) + min_width) / edge_beam_dim_increment) * edge_beam_dim_increment
                offset = abs(dot) + min_width - width / 2
        return outer_segment.translated(-perp_vector * offset), width

    def _set_edge_beam_category(self, beam: Beam2D, index: int) -> None:
        if abs(beam.centerline.direction[0]) < abs(beam.centerline.direction[1]):
            beam.attributes["category"] = "edge_stud"
        else:
            if dot_vectors(get_polyline_segment_perpendicular_vector(self.panel.outline_a, index), Vector(0, 1, 0)) < 0:
                beam.attributes["category"] = "bottom_plate_beam"
            else:
                beam.attributes["category"] = "top_plate_beam"

    def _apply_linear_cut_to_edge_beam(self, beam: Beam2D, edge_index: int) -> None:
        """Trim the edge beams to fit between the plate beams."""
        plane = self.panel.edge_planes[edge_index]
        if not TOL.is_zero(dot_vectors(Vector(0, 0, 1), plane.normal)):
            long_cut = LongitudinalCutProxy.from_plane_and_beam(plane, beam, is_joinery=False)
            beam.add_features(long_cut)

    # ==========================================================================
    # methods for creating beam joints
    # ==========================================================================

    def create_internal_joint_defs(self, model, elements=None) -> list[DirectRule]:
        """Generate the joint definitions for the panel edges."""
        for candidate in self.create_joint_candidates(model, elements=elements):
            rule = self.create_edge_beam_joint_rule(*candidate.elements)
            if rule is not None:
                self.joint_defs.append(rule)

    def create_edge_beam_joint_rule(self, beam_a: Beam2D, beam_b: Beam2D) -> DirectRule:
        """Generate the joint definition between two edge beams. Used when there is no interface on either edge."""
        beam_a_slope = abs(dot_vectors(beam_a.frame.xaxis, Vector(0, 1, 0)))
        beam_b_slope = abs(dot_vectors(beam_b.frame.xaxis, Vector(0, 1, 0)))
        edge_a_index = beam_a.attributes["edge_index"]
        edge_b_index = beam_b.attributes["edge_index"]
        if abs(edge_a_index - edge_b_index) > 1:
            corner_index = 0
        else:
            corner_index = max(edge_a_index, edge_b_index)
        interior_corner = corner_index in get_interior_corner_indices(self.panel.outline_a)

        edge_plane_a = self.panel.edge_planes[edge_a_index]
        edge_plane_b = self.panel.edge_planes[edge_b_index]
        miter = angle_vectors(beam_a.frame.xaxis, beam_b.frame.xaxis) < math.pi / 3

        if miter:
            if interior_corner:
                ppx = intersection_plane_plane(edge_plane_a, edge_plane_b)
                ref_side_main: dict[int, float] = beam_ref_side_incidence(beam_a, beam_b)
                front_a = Plane.from_frame(beam_a.ref_sides[min(ref_side_main.items(), key=lambda x: x[1])[0]])

                ref_side_cross: dict[int, float] = beam_ref_side_incidence(beam_b, beam_a)
                front_b = Plane.from_frame(beam_b.ref_sides[min(ref_side_cross.items(), key=lambda x: x[1])[0]])

                ccx = intersection_plane_plane(front_a, front_b)

                if not ppx or not ccx:
                    raise ValueError("Could not compute miter joint for edge beams at edges {} and {}, edges appear to be parallel".format(edge_a_index, edge_b_index))
                miter_plane = Plane.from_points([ppx[0], ppx[1], ccx[0]])
                return DirectRule(LMiterJoint, [beam_a, beam_b], miter_plane=miter_plane, clean=True)

            else:
                # trim_plane_a=edge_plane_a, trim_plane_b=edge_plane_b)

                return DirectRule(LMiterJoint, [beam_b, beam_a], ref_side_miter=True, clean=True)

        else:
            if interior_corner:
                if beam_a_slope < beam_b_slope:  # b = main, a = cross
                    plane = Plane(edge_plane_a.point, -edge_plane_a.normal)  # plane comes from edge a
                    return DirectRule(LButtJoint, [beam_b, beam_a], butt_plane=plane)
                else:  # a = main, b = cross
                    plane = Plane(edge_plane_b.point, -edge_plane_b.normal)
                    return DirectRule(LButtJoint, [beam_a, beam_b], butt_plane=plane)
            else:
                if beam_a_slope < beam_b_slope:  # b = main, a = cross
                    return DirectRule(LButtJoint, [beam_b, beam_a], back_plane=edge_plane_b)
                else:  # a = main, b = cross
                    return DirectRule(LButtJoint, [beam_a, beam_b], back_plane=edge_plane_a)


# Set after both classes are defined so forward reference is resolved
EdgePopulatorAgentConfig.AGENT_TYPE = EdgePopulatorAgent
