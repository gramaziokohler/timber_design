import math

from compas.geometry import Line
from compas.geometry import Plane
from compas.geometry import Point
from compas.geometry import Vector
from compas.geometry import dot_vectors
from compas.tolerance import TOL
from compas_timber.connections import LButtJoint
from compas_timber.design import CategoryRule
from compas_timber.elements import Beam
from compas_timber.fabrication import LongitudinalCutProxy
from compas_timber.utils import extend_line_segments
from compas_timber.utils import join_polyline_segments

from timber_design.element_generators import ElementGeneratorParameters
from timber_design.element_generators.generator_functions import split_beam_with_element_groups
from timber_design.populators import ElementGroup
from timber_design.populators import FeatureBoundaryType

# ==========================================================================
# methods for edge beams
# ==========================================================================


def create_edge_beams(parameters, slab_populator):
    #type: (ElementGeneratorParameters, SlabPopulator) -> ElementGroup
    """Get the edge beam definitions for the outer polyline of the slab."""
    segs, widths = [], []
    for i in range(slab_populator.edge_count):
        seg, width = _get_edge_beam_line_and_width(slab_populator, i, min_width=parameters.edge_beam_min_width, edge_beam_dim_increment=parameters.standard_beam_width_increment)
        segs.append(seg)
        widths.append(width)
    extend_line_segments(segs, close_loop=True)
    edges = []
    edge_elements = {}
    elements = []
    for i, (seg, width) in enumerate(zip(segs, widths)):
        edge_beam = Beam.from_centerline(seg, width=width, height=slab_populator.frame_thickness, z_vector=Vector(0, 0, 1))
        _set_edge_beam_category(slab_populator, edge_beam, i)
        _apply_linear_cut_to_edge_beam(edge_beam, slab_populator, i)
        edge_elements[i] = [edge_beam]
        elements.append(edge_beam)
        edges.append(seg.translated(slab_populator.edge_perpendicular_vectors[i] * (-edge_beam.width / 2)))
    extend_line_segments(edges, close_loop=True)
    outline = join_polyline_segments(edges, close_loop=True)
    eg = ElementGroup(
        slab_populator,
        parameters,
        elements=elements,
        edges={index: edge for index, edge in enumerate(edges)},
        edge_elements=edge_elements,
        outline=outline,
        boundary_type=FeatureBoundaryType.INCLUSIVE,
    )
    return eg


def _get_edge_beam_line_and_width(slab_populator, segment_index, min_width=0.0, edge_beam_dim_increment=None):
    #type: (SlabPopulator, int, float, float | None) -> tuple[Line, float]
    perp_vector = slab_populator.edge_perpendicular_vectors[segment_index]
    seg_a = slab_populator.frame_outline_a.lines[segment_index]
    seg_b = slab_populator.frame_outline_b.lines[segment_index]
    dot = dot_vectors(perp_vector, Vector.from_start_end(seg_a.start, seg_b.start))
    if TOL.is_zero(dot):  # edges are perpendicular to slab
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


def _set_edge_beam_category(slab_populator, beam, index):
    #type: (SlabPopulator, Beam, int) -> None
    if abs(beam.centerline.direction[0]) < abs(beam.centerline.direction[1]):
        beam.attributes["category"] = "edge_stud"
    else:
        if dot_vectors(slab_populator.edge_perpendicular_vectors[index], Vector(0, 1, 0)) < 0:
            beam.attributes["category"] = "bottom_plate_beam"
        else:
            beam.attributes["category"] = "top_plate_beam"


def _apply_linear_cut_to_edge_beam(beam, slab_populator, index):
    #type: (Beam, SlabPopulator, int) -> None
    """Trim the edge beams to fit between the plate beams."""
    plane = slab_populator.edge_planes[index]
    if not TOL.is_zero(dot_vectors(Vector(0, 0, 1), plane.normal)):
        long_cut = LongitudinalCutProxy.from_plane_and_beam(plane, beam, is_joinery=False)
        beam.add_features(long_cut)


# ==========================================================================
# methods for beam joints
# ==========================================================================


def create_external_joints(parameters, slab_populator, element_group, intersecting_element_groups):
    #type: (ElementGeneratorParameters, SlabPopulator, ElementGroup, list[ElementGroup]) -> list[DirectRule]
    """Joins the stud beams."""
    rules = []
    edge_elements = {}
    for index, edge_beams in element_group.edge_elements.items():
        edge_elements[index] = []
        for raw_edge_beam in edge_beams:
            beam_int_tuples, joints_to_cull = split_beam_with_element_groups(raw_edge_beam, intersecting_element_groups)
            for j in joints_to_cull:
                if j in slab_populator.direct_rules:
                    slab_populator.direct_rules.remove(j)
            element_group.elements.remove(raw_edge_beam)
            for beam, ints in beam_int_tuples:
                if beam:
                    element_group.elements.append(beam)
                    edge_elements[index].append(beam)
                for intersection in ints:
                    if not intersection:
                        continue
                    for int_index in intersection.get("edge_indices", []):
                        beams = intersection["element_group"].edge_elements.get(int_index, [])
                        params = intersection["element_group"].parameters
                        for intersecting_beam in beams:
                            rules.append(params.get_direct_rule_from_elements(beam, intersecting_beam))

    element_group.edge_elements = edge_elements
    return [rule for rule in rules if rule is not None]


def create_internal_joints(parameters, slab_populator, element_group):
    #type: (ElementGeneratorParameters, SlabPopulator, ElementGroup) -> list[DirectRule]
    """Generate the joint definitions for the slab edges. When there is an interface, we use the interface.detail_set to create the joint definition."""
    rules = []
    for corner_index in range(slab_populator.edge_count):
        edge_a_index = corner_index
        edge_b_index = (edge_a_index - 1) % slab_populator.edge_count
        interior_corner = edge_a_index in slab_populator.interior_corner_indices
        rule = _create_edge_beam_joint_rule(parameters, element_group, slab_populator.edge_planes, edge_a_index, edge_b_index, interior_corner)
        rules.append(rule)
    return [rule for rule in rules if rule is not None]


def _create_edge_beam_joint_rule(parameters, element_group, edge_planes, edge_a_index, edge_b_index, interior_corner):
    #type: (ElementGeneratorParameters, ElementGroup, dict[int, Plane], int, int, bool) -> DirectRule
    """Generate the joint definition between two edge beams. Used when there is no interface on either edge."""
    beam_a = element_group.edge_elements[edge_a_index][0]
    beam_b = element_group.edge_elements[edge_b_index][-1]
    beam_a_slope = abs(dot_vectors(beam_a.frame.xaxis, Vector(0, 1, 0)))
    beam_b_slope = abs(dot_vectors(beam_b.frame.xaxis, Vector(0, 1, 0)))
    edge_plane_a = edge_planes[edge_a_index]
    edge_plane_b = edge_planes[edge_b_index]

    if interior_corner:
        if beam_a_slope < beam_b_slope:  # b = main, a = cross
            plane = Plane(edge_plane_a.point, -edge_plane_a.normal)  # plane comes from edge a
            return parameters.get_direct_rule_from_elements(beam_b, beam_a, butt_plane=plane.transformed(beam_b.transformation_to_local()))
        else:  # a = main, b = cross
            plane = Plane(edge_plane_b.point, -edge_plane_b.normal)
            return parameters.get_direct_rule_from_elements(beam_a, beam_b, butt_plane=plane.transformed(beam_a.transformation_to_local()))
    else:
        if beam_a_slope < beam_b_slope:  # b = main, a = cross
            return parameters.get_direct_rule_from_elements(beam_b, beam_a, back_plane=edge_plane_b.transformed(beam_b.transformation_to_local()))
        else:  # a = main, b = cross
            return parameters.get_direct_rule_from_elements(beam_a, beam_b, back_plane=edge_plane_a.transformed(beam_a.transformation_to_local()))



class SlabEdgeElementGeneratorParametersA(ElementGeneratorParameters):
    """A slab detail set that uses the default edge beams, studs, and plates."""

    BEAM_CATEGORY_NAMES = ["edge_stud", "top_plate_beam", "bottom_plate_beam"]
    NAME = "SlabEdgeElementGenerator"
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
        standard_beam_width=None,
        standard_beam_width_increment=None,
        edge_beam_min_width=None,
        beam_width_overrides=None,
        joint_rule_overrides=None,
    ):
        #type: (float | None, float | None, float | None, dict | None, list[CategoryRule] | None) -> None
        super(SlabEdgeElementGeneratorParametersA, self).__init__(
            standard_beam_width,
            beam_width_overrides,
            joint_rule_overrides,
        )
        self.standard_beam_width_increment = standard_beam_width_increment
        self.edge_beam_min_width = edge_beam_min_width or standard_beam_width

    def generate_elements(self, slab_populator):
        #type: (SlabPopulator) -> ElementGroup
        """Populates the slab with elements and joints according to the detail set.

        Parameters
        ----------
        slab_populator : :class:`compas_timber.populators.SlabPopulator`
            The slab populator to populate.
        """
        edge_group = create_edge_beams(self, slab_populator)
        return edge_group

    def cull_beam_segment(self, stud, element_group) -> bool:
        #type: (Beam, ElementGroup) -> bool
        """Cull and split the studs for door openings."""
        return False

    def join_elements(self, slab_populator, element_group):
        #type: (SlabPopulator, ElementGroup) -> list[DirectRule]
        """Join the elements for WindowDetailB."""
        rules = []
        intersecting_groups = [f for f in slab_populator.element_groups if f.feature is not slab_populator]
        if intersecting_groups:
            rules.extend(create_external_joints(self, slab_populator, element_group, intersecting_groups))
        rules.extend(create_internal_joints(self, slab_populator, element_group))
        return [rule for rule in rules if rule is not None]
