import math
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
from compas_timber.fabrication import JackRafterCutProxy
from compas_timber.fabrication import LongitudinalCutProxy
from compas_timber.utils import extend_line_segments
from compas_timber.utils import get_interior_corner_indices
from compas_timber.utils import get_polyline_segment_perpendicular_vector
from compas_timber.utils import join_polyline_segments

from timber_design.populators.beam2d import Beam2D
from timber_design.populators.populator_agents.layer_agent import AgentBoundaryType
from timber_design.populators.populator_agents.layer_agent import LayerAgent
from timber_design.workflow import CategoryRule
from timber_design.workflow import DirectRule


class EdgePopulatorAgent(LayerAgent):
    """Generates edge beams (plates and edge studs) along the panel outline.

    Creates one :class:`~timber_design.populators.Beam2D` per segment of the
    panel outline (``layer.outline_a``).  Each beam's width comes from
    :attr:`~PopulatorAgent.beam_widths` — resolved from explicit per-category
    constructor kwargs (``edge_stud_width``, ``top_plate_beam_width``,
    ``bottom_plate_beam_width``) and falls back to *standard_beam_width*.

    An optional *width increment* rounds each beam width up to the next
    multiple of that value.

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
    :meth:`~timber_design.populators.PanelPopulator.trim_elements`.

    Parameters
    ----------
    layer : :class:`~timber_design.populators.Layer`
        The layer whose panel outline drives edge-beam placement.
    params : :class:`EdgePopulatorAgentConfig`
        Controls optional standard-width rounding.

    Attributes
    ----------
    standard_beam_width_increment : float or None
        When set, edge-beam widths are rounded up to the next multiple of
        this value.
    """

    BEAM_CATEGORY_NAMES = ["edge_stud", "top_plate_beam", "bottom_plate_beam"]
    NAME = "EdgePopulatorAgent"
    INTERNAL_JOINT_RULES = [
        CategoryRule(LButtJoint, "edge_stud", "edge_stud", mill_depth=10.0, max_distance=1.0),
        CategoryRule(LButtJoint, "edge_stud", "top_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(LButtJoint, "edge_stud", "bottom_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(LButtJoint, "top_plate_beam", "top_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(LButtJoint, "top_plate_beam", "bottom_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(LButtJoint, "bottom_plate_beam", "bottom_plate_beam", mill_depth=10.0, max_distance=1.0),
    ]
    BOUNDARY_TYPE = AgentBoundaryType.INCLUSIVE

    def __init__(
        self,
        layer,
        edge_stud_width: Optional[float] = None,
        top_plate_beam_width: Optional[float] = None,
        bottom_plate_beam_width: Optional[float] = None,
        internal_joint_overrides=None,
        external_joint_overrides=None,
        standard_beam_width_increment=None,
    ):
        super(EdgePopulatorAgent, self).__init__(layer, internal_joint_overrides, external_joint_overrides)
        self.beam_widths["edge_stud"] = edge_stud_width
        self.beam_widths["top_plate_beam"] = top_plate_beam_width
        self.beam_widths["bottom_plate_beam"] = bottom_plate_beam_width
        self.standard_beam_width_increment = standard_beam_width_increment

    @property
    def __data__(self):
        data = super().__data__
        data["edge_stud_width"] = self.beam_widths.get("edge_stud")
        data["top_plate_beam_width"] = self.beam_widths.get("top_plate_beam")
        data["bottom_plate_beam_width"] = self.beam_widths.get("bottom_plate_beam")
        data["standard_beam_width_increment"] = self.standard_beam_width_increment
        return data

    # ==========================================================================
    # private methods for creating edge beams
    # ==========================================================================

    def generate_elements_for_layer(self, layer=None):
        """Get the edge beams for the outer polyline of the panel."""
        segs, widths = [], []
        elements = []
        for i in range(len(self.layer.outline_a) - 1):
            category = self._get_segment_category(i)
            width = self.beam_widths[category]
            seg, width = self._get_edge_beam_line_and_width(i, width)
            segs.append(seg)
            widths.append(width)
        extend_line_segments(segs, close_loop=True)
        edges: list[Line] = []  # boundaries of this agent
        for i, (seg, width) in enumerate(zip(segs, widths)):
            edge_beam = Beam2D.from_centerline(seg, width=width, height=self.layer.thickness, z_vector=Vector(0, 0, 1), edge_index=i)
            self._set_edge_beam_category(edge_beam, i)
            self._apply_linear_cut_to_edge_beam(edge_beam, i)
            elements.append(edge_beam)
            vector = get_polyline_segment_perpendicular_vector(self.layer.outline_a, i)
            edges.append(seg.translated(vector * (-edge_beam.width / 2)))
        extend_line_segments(edges, close_loop=True)
        outline = join_polyline_segments(edges, close_loop=True)[0][0]
        return elements, outline


    def _get_segment_category(self, segment_index: int) -> str:
        """Return the beam category for the outline segment at *segment_index*.

        Uses the same direction-based logic as :meth:`_set_edge_beam_category`
        but operates directly on the outline geometry, so it can be called
        before the beam object exists.
        """
        seg = self.layer.outline_a.lines[segment_index]
        direction = Vector.from_start_end(seg.start, seg.end)
        if abs(direction[0]) < abs(direction[1]):
            return "edge_stud"
        if dot_vectors(get_polyline_segment_perpendicular_vector(self.layer.outline_a, segment_index), Vector(0, 1, 0)) < 0:
            return "bottom_plate_beam"
        return "top_plate_beam"

    def _get_edge_beam_line_and_width(self, segment_index: int, width: float) -> tuple[Line, float]:
        """Return the beam centreline and final width for the edge at *segment_index*.

        The outermost of ``outline_a`` / ``outline_b`` at this segment is
        used as the outer face reference.  The beam centreline is offset
        inward by ``width / 2`` so that the outer face of the beam is flush
        with the panel edge.

        If :attr:`standard_beam_width_increment` is set, *width* is rounded
        up to the next multiple of that increment before computing the offset.
        """
        perp_vector = get_polyline_segment_perpendicular_vector(self.layer.outline_a, segment_index)
        seg_a = self.layer.outline_a.lines[segment_index]
        seg_b = self.layer.outline_b.lines[segment_index]
        dot = dot_vectors(perp_vector, Vector.from_start_end(seg_a.start, seg_b.start))
        width += abs(dot)
        z = self.layer_center_height
        if TOL.is_zero(dot) or dot < 0:  # seg_a is outermost (or edges are flush)
            outer_segment = Line(Point(seg_a.start[0], seg_a.start[1], z), Point(seg_a.end[0], seg_a.end[1], z))
        else:  # seg_b is outermost
            outer_segment = Line(Point(seg_b.start[0], seg_b.start[1], z), Point(seg_b.end[0], seg_b.end[1], z))
        if self.standard_beam_width_increment:
            width = math.ceil(width / self.standard_beam_width_increment) * self.standard_beam_width_increment
        offset = width / 2
        return outer_segment.translated(-perp_vector * offset), width

    def _set_edge_beam_category(self, beam: Beam2D, index: int) -> None:
        beam.attributes["category"] = self._get_segment_category(index)

    def _apply_linear_cut_to_edge_beam(self, beam: Beam2D, edge_index: int) -> None:
        """Trim the edge beams to fit between the plate beams."""
        plane = self.layer.edge_planes[edge_index]
        if not TOL.is_zero(dot_vectors(Vector(0, 0, 1), plane.normal)):
            long_cut = LongitudinalCutProxy.from_plane_and_beam(plane, beam, is_joinery=False)
            beam.add_features(long_cut)

    # ==========================================================================
    # methods for creating beam joints
    # ==========================================================================

    def create_joint_defs(self) -> list[DirectRule]:
        """Generate the joint definitions for the panel edges."""
        for candidate in self.create_joint_candidates():
            rule = self._edge_joint_rule(*candidate.elements)
            if rule is not None:
                self.joint_defs.append(rule)

    def _edge_joint_rule(self, beam_a: Beam2D, beam_b: Beam2D) -> DirectRule:
        """Return the joint rule for two edge beams.

        The strategy depends on the panel-edge geometry at the two beams:

        - When **both** edge planes are perpendicular to the panel (clean
          vertical faces), the joint is resolved from :attr:`internal_rules`
          via :meth:`~PopulatorAgent.get_direct_rule_from_elements`, so it
          honors ``internal_joint_overrides``.
        - When **either** edge is sloped/chamfered (its edge plane is not
          perpendicular to the panel), the joint type and cut planes are
          computed geometrically by :meth:`_create_edge_beam_joint_rule`, which
          is required to fit the bevel.
        """
        edge_a = beam_a.attributes["edge_index"]
        edge_b = beam_b.attributes["edge_index"]
        if self._edge_plane_is_perpendicular(edge_a) and self._edge_plane_is_perpendicular(edge_b):
            return self.get_direct_rule_from_elements(beam_a, beam_b)
        return self._create_edge_beam_joint_rule(beam_a, beam_b)

    def _edge_plane_is_perpendicular(self, edge_index: int) -> bool:
        """Return ``True`` if the panel edge plane at *edge_index* is perpendicular to the panel.

        A perpendicular (clean vertical) edge has an edge-plane normal lying in
        the panel plane — no component along the panel normal (Z in populator
        space).  Sloped/chamfered edges carry a Z component in their normal.
        """
        plane = self.layer.edge_planes[edge_index]
        return TOL.is_zero(plane.normal[2])

    def _create_edge_beam_joint_rule(self, beam_a: Beam2D, beam_b: Beam2D) -> DirectRule:
        """Generate the joint definition between two edge beams. Used when there is no interface on either edge."""

        edge_a_index = beam_a.attributes["edge_index"]
        edge_b_index = beam_b.attributes["edge_index"]
        if abs(edge_a_index - edge_b_index) > 1:
            corner_index = 0
        else:
            corner_index = max(edge_a_index, edge_b_index)
        interior_corner = corner_index in get_interior_corner_indices(self.layer.outline_a)

        edge_plane_a = self.layer.edge_planes[edge_a_index]
        edge_plane_b = self.layer.edge_planes[edge_b_index]
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
                # HACK: these cuts should be tied to the Joint, but if the beams are copied or the features are cleared, the joint cannot currently re-generate these features.
                beam_a.add_feature(JackRafterCutProxy.from_plane_and_beam(edge_plane_b, beam_a, is_joinery=False))
                beam_b.add_feature(JackRafterCutProxy.from_plane_and_beam(edge_plane_a, beam_b, is_joinery=False))
                return DirectRule(LMiterJoint, [beam_b, beam_a], ref_side_miter=True, clean=True)

        else:
            beam_a_slope = abs(dot_vectors(beam_a.frame.xaxis, Vector(0, 1, 0)))
            beam_b_slope = abs(dot_vectors(beam_b.frame.xaxis, Vector(0, 1, 0)))
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

