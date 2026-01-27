import math
from typing import Union

from compas.geometry import Line
from compas.geometry import Plane
from compas.geometry import Point
from compas.geometry import Vector
from compas.geometry import angle_vectors
from compas.geometry import angle_vectors_signed
from compas.geometry import dot_vectors
from compas.geometry import intersection_line_line
from compas.geometry import intersection_plane_plane
from compas.tolerance import TOL
from compas_timber.connections import LButtJoint
from compas_timber.connections import LMiterJoint
from compas_timber.connections import beam_ref_side_incidence
from compas_timber.elements import Beam
from compas_timber.elements import Panel
from compas_timber.fabrication import LongitudinalCutProxy
from compas_timber.utils import extend_line_segments
from compas_timber.utils import get_polyline_segment_perpendicular_vector
from compas_timber.utils import is_polyline_clockwise
from compas_timber.utils import join_polyline_segments

from timber_design.populators import ElementGenerator
from timber_design.populators import FeatureBoundaryType
from timber_design.populators import ElementGeneratorParams
from timber_design.populators import split_beam_with_element_generators
from timber_design.workflow import CategoryRule
from timber_design.workflow import DirectRule


class EdgeElementGeneratorParams(ElementGeneratorParams):
    def __init__(
        self,
        standard_beam_width: float,
        standard_beam_width_increment: Union[float, None] = None,
        edge_beam_min_width: Union[float, None] = None,
        beam_width_overrides: Union[dict, None] = None,
        joint_rule_overrides: Union[list[CategoryRule], None] = None,
    ):
        super(EdgeElementGeneratorParams, self).__init__(beam_width_overrides, joint_rule_overrides)
        self.standard_beam_width = standard_beam_width
        self.standard_beam_width_increment = standard_beam_width_increment
        self.edge_beam_min_width = edge_beam_min_width

    @property
    def __data__(self):
        data = super().__data__
        data["standard_beam_width"] = self.standard_beam_width,
        data["standard_beam_width_increment"] = self.standard_beam_width_increment,
        data["edge_beam_min_width"] = self.edge_beam_min_width,
        


class EdgeElementGenerator(ElementGenerator):
    """A panel detail set that uses the default edge beams, studs, and plates."""

    BEAM_CATEGORY_NAMES = ["edge_stud", "top_plate_beam", "bottom_plate_beam"]
    NAME = "PanelEdgeElementGenerator"
    RULES = [
        CategoryRule(LButtJoint, "edge_stud", "edge_stud", mill_depth=10.0, max_distance=1.0),
        CategoryRule(LButtJoint, "edge_stud", "top_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(LButtJoint, "edge_stud", "bottom_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(LButtJoint, "top_plate_beam", "top_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(LButtJoint, "top_plate_beam", "bottom_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(LButtJoint, "bottom_plate_beam", "bottom_plate_beam", mill_depth=10.0, max_distance=1.0),
    ]

    def __init__(
        self,
        panel: Panel,
        standard_beam_width: float,
        standard_beam_width_increment: Union[float, None] = None,
        edge_beam_min_width: Union[float, None] = None,
        beam_width_overrides: Union[dict, None] = None,
        joint_rule_overrides: Union[list[CategoryRule], None] = None,
    ) -> None:
        super(EdgeElementGenerator, self).__init__(
            panel,
            standard_beam_width,
            beam_width_overrides,
            joint_rule_overrides,
        )
        self.standard_beam_width_increment = standard_beam_width_increment
        self.edge_beam_min_width = edge_beam_min_width or standard_beam_width
        self._interior_corner_indices = []

    @property
    def panel(self) -> Panel:
        """The panel associated with this element generator."""
        return self.feature  # type: ignore

    @property
    def interior_corner_indices(self):
        """Get the indices of the interior corners of the panel outline."""
        if not self._interior_corner_indices:
            """Get the indices of the interior corners of the panel outline."""
            points = self.panel.outline_a.points[0:-1]
            cw = is_polyline_clockwise(self.panel.outline_a, Vector(0, 0, 1))
            for i in range(len(points)):
                angle = angle_vectors_signed(points[i - 1] - points[i], points[(i + 1) % len(points)] - points[i], Vector(0, 0, 1), deg=True)
                if not (cw ^ (angle < 0)):
                    self._interior_corner_indices.append(i)
        return self._interior_corner_indices

    @property
    def interior_segment_indices(self):
        """Get the indices of the interior segments of the panel outline."""
        if not self._interior_corner_indices:
            for i in range(len(self.panel.outline_a) - 1):
                if i in self.interior_corner_indices and (i + 1) % len(self.panel.outline_a) - 1 in self.interior_corner_indices:
                    yield i

    # ==========================================================================
    # methods for edge beams
    # ==========================================================================

    def generate_elements(self) -> None:
        """generates the edge beams for the panel."""
        self._create_edge_beams()

    def cull_beam_segment(self, beam: Beam) -> bool:
        """Cull and split the studs for door openings."""
        return False

    def join_elements(self, populator_direct_rules: list[DirectRule], element_generators: list[ElementGenerator]) -> list[DirectRule]:
        """Join the elements for WindowDetailB."""
        rules = []
        intersecting_generators = [eg for eg in element_generators if eg is not self]
        if intersecting_generators:
            rules.extend(self._create_external_joints(populator_direct_rules, intersecting_generators))
        rules.extend(self._create_internal_joints())
        return [rule for rule in rules if rule is not None]

    # ==========================================================================
    # private methods for creating edge beams
    # ==========================================================================

    def _create_edge_beams(self) -> None:
        """Get the edge beams for the outer polyline of the panel."""
        segs, widths = [], []
        for i in range(len(self.panel.outline_a) - 1):
            seg, width = self._get_edge_beam_line_and_width(i, min_width=self.edge_beam_min_width, edge_beam_dim_increment=self.standard_beam_width_increment)
            segs.append(seg)
            widths.append(width)
        extend_line_segments(segs, close_loop=True)
        edges: list[Line] = []  # boundaries of this generator
        for i, (seg, width) in enumerate(zip(segs, widths)):
            edge_beam = Beam.from_centerline(seg, width=width, height=self.panel.thickness, z_vector=Vector(0, 0, 1))
            self._set_edge_beam_category(edge_beam, i)
            self._apply_linear_cut_to_edge_beam(edge_beam, i)
            self.edge_elements[i] = [edge_beam]
            self.elements.append(edge_beam)
            vector = get_polyline_segment_perpendicular_vector(self.panel.outline_a, i)
            edges.append(seg.translated(vector * (-edge_beam.width / 2)))
        extend_line_segments(edges, close_loop=True)
        self.outline = join_polyline_segments(edges, close_loop=True)  # TODO: do we need both outline and edges?
        self.edges = {index: edge for index, edge in enumerate(edges)}
        self.boundary_type = FeatureBoundaryType.INCLUSIVE

    def _get_edge_beam_line_and_width(self, segment_index, min_width=0.0, edge_beam_dim_increment=None) -> tuple[Line, float]:
        perp_vector = get_polyline_segment_perpendicular_vector(self.panel.outline_a, segment_index)
        seg_a = self.panel.outline_a.lines[segment_index]
        seg_b = self.panel.outline_b.lines[segment_index]
        dot = dot_vectors(perp_vector, Vector.from_start_end(seg_a.start, seg_b.start))
        if TOL.is_zero(dot):  # edges are perpendicular to panel
            outer_segment = Line(Point(seg_a.start[0], seg_a.start[1], 0), Point(seg_a.end[0], seg_a.end[1], 0))
            width = min_width
            offset = width / 2
        else:
            if dot < 0:  # seg_b is closer to the middle
                outer_segment = Line(Point(seg_a.start[0], seg_a.start[1], 0), Point(seg_a.end[0], seg_a.end[1], 0))
            else:  # seg_a is closer to the middle
                outer_segment = Line(Point(seg_b.start[0], seg_b.start[1], 0), Point(seg_b.end[0], seg_b.end[1], 0))
            if not edge_beam_dim_increment:
                width = abs(dot) + min_width
                offset = width / 2
            else:
                width = math.ceil((abs(dot) + min_width) / edge_beam_dim_increment) * edge_beam_dim_increment
                offset = abs(dot) + min_width - width / 2
        return outer_segment.translated(-perp_vector * offset), width

    def _set_edge_beam_category(self, beam: Beam, index: int) -> None:
        if abs(beam.centerline.direction[0]) < abs(beam.centerline.direction[1]):
            beam.attributes["category"] = "edge_stud"
        else:
            if dot_vectors(get_polyline_segment_perpendicular_vector(self.panel.outline_a, index), Vector(0, 1, 0)) < 0:
                beam.attributes["category"] = "bottom_plate_beam"
            else:
                beam.attributes["category"] = "top_plate_beam"

    def _apply_linear_cut_to_edge_beam(self, beam: Beam, edge_index: int) -> None:
        """Trim the edge beams to fit between the plate beams."""
        plane = self.panel.edge_planes[edge_index]
        if not TOL.is_zero(dot_vectors(Vector(0, 0, 1), plane.normal)):
            long_cut = LongitudinalCutProxy.from_plane_and_beam(plane, beam, is_joinery=False)
            beam.add_features(long_cut)

    # ==========================================================================
    # methods for creating beam joints
    # ==========================================================================

    def _create_external_joints(self, populator_direct_rules: list[DirectRule], intersecting_element_generators: list[ElementGenerator]) -> list[DirectRule]:
        rules = []
        edge_elements = {}
        for index, edge_beams in self.edge_elements.items():
            edge_elements[index] = []
            for raw_edge_beam in edge_beams:
                beam_int_tuples, joints_to_cull = split_beam_with_element_generators(raw_edge_beam, intersecting_element_generators)
                for j in joints_to_cull:
                    if j in populator_direct_rules:
                        populator_direct_rules.remove(j)
                self.elements.remove(raw_edge_beam)
                for beam, ints in beam_int_tuples:
                    if beam:
                        self.elements.append(beam)
                        edge_elements[index].append(beam)
                        for intersection in ints:
                            if not intersection:
                                continue
                            for int_index in intersection.edge_indices:
                                beams = intersection.generator.edge_elements.get(int_index, []) if intersection.generator else []
                                params = intersection.generator or self
                                for intersecting_beam in beams:
                                    rules.append(params.get_direct_rule_from_elements(beam, intersecting_beam))

        self.edge_elements = edge_elements
        return [rule for rule in rules if rule is not None]

    def _create_internal_joints(self) -> list[DirectRule]:
        """Generate the joint definitions for the panel edges. When there is an interface, we use the interface.detail_set to create the joint definition."""
        rules = []
        for corner_index in range(len(self.panel.outline_a) - 1):
            edge_a_index = corner_index
            edge_b_index = (edge_a_index - 1) % len(self.panel.outline_a) - 1
            interior_corner = edge_a_index in self.interior_corner_indices
            rule = self._create_edge_beam_joint_rule(self.panel.edge_planes, edge_a_index, edge_b_index, interior_corner)
            point = intersection_line_line(rule.elements[0].centerline, rule.elements[1].centerline)[0]
            for element in rule.elements:
                if element.attributes.get("joint_defs", None) is None:
                    element.attributes["joint_defs"] = {}
                element_dot = dot_vectors(Vector.from_start_end(element.centerline.start, point), element.centerline.direction)
                element.attributes["joint_defs"][element_dot] = rule
            rules.append(rule)
        return [rule for rule in rules if rule is not None]

    def _create_edge_beam_joint_rule(self, edge_planes: dict[int, Plane], edge_a_index: int, edge_b_index: int, interior_corner: bool) -> DirectRule:
        """Generate the joint definition between two edge beams. Used when there is no interface on either edge."""
        beam_a = self.edge_elements[edge_a_index][0]
        beam_b = self.edge_elements[edge_b_index][-1]
        beam_a_slope = abs(dot_vectors(beam_a.frame.xaxis, Vector(0, 1, 0)))
        beam_b_slope = abs(dot_vectors(beam_b.frame.xaxis, Vector(0, 1, 0)))
        edge_plane_a = edge_planes[edge_a_index]
        edge_plane_b = edge_planes[edge_b_index]
        miter = False
        if angle_vectors(beam_a.frame.xaxis, beam_b.frame.xaxis) < math.pi / 3:
            miter = True

        if miter:
            if interior_corner:
                ppx = intersection_plane_plane(edge_plane_a, edge_plane_b)
                ref_side_main: dict[int, float] = beam_ref_side_incidence(beam_a, beam_b)
                front_a = Plane.from_frame(beam_a.ref_sides[min(ref_side_main.items(), key=lambda x: x[1])])

                ref_side_cross: dict[int, float] = beam_ref_side_incidence(beam_b, beam_a)
                front_b = Plane.from_frame(beam_b.ref_sides[min(ref_side_cross.items(), key=lambda x: x[1])])

                ccx = intersection_plane_plane(front_a, front_b)

                if not ppx or not ccx:
                    raise ValueError("Could not compute miter joint for edge beams at edges {} and {}, edges appear to be parallel".format(edge_a_index, edge_b_index))
                miter_plane = Plane.from_points([ppx[0], ppx[1], ccx[0]])
                if beam_a_slope < beam_b_slope:  # b = main, a = cross
                    plane = Plane(edge_plane_a.point, -edge_plane_a.normal)  # plane comes from edge a
                    return DirectRule(LMiterJoint, [beam_b, beam_a], miter_plane=miter_plane, clean=True)
                else:  # a = main, b = cross
                    plane = Plane(edge_plane_b.point, -edge_plane_b.normal)
                    return DirectRule(LMiterJoint, [beam_a, beam_b], miter_plane=miter_plane, clean=True)

            else:
                if beam_a_slope < beam_b_slope:  # b = main, a = cross
                    return DirectRule(LMiterJoint, [beam_b, beam_a], miter_type="ref_surfaces", trim_plane_a=edge_plane_a, trim_plane_b=edge_plane_b)
                else:  # a = main, b = cross
                    return DirectRule(LMiterJoint, [beam_a, beam_b], miter_type="ref_surfaces", trim_plane_a=edge_plane_b, trim_plane_b=edge_plane_a)

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
