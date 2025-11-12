import math

from compas.geometry import Line
from compas.geometry import Plane
from compas.geometry import Point
from compas.geometry import Polyline
from compas.geometry import Vector
from compas.geometry import dot_vectors
from compas.itertools import pairwise
from compas.tolerance import TOL
from compas_timber.connections import LButtJoint
from compas_timber.connections import TButtJoint
from compas_timber.elements import Beam
from compas_timber.elements import Plate
from compas_timber.fabrication import LongitudinalCutProxy
from compas_timber.utils import extend_lines_pairwise
from compas_timber.utils import is_point_in_polyline

from compas_timber.design import CategoryRule
from timber_design.element_generators import ElementGeneratorParameters
from .generator_functions import get_beam_edges_feature_def_intersection



def _set_frame_outlines(parameters, slab_populator):
    """Handles the sheeting offsets for the slab outlines."""
    """This method creates new outlines for the beam frame based on the sheeting thicknesses."""
    if not parameters.sheeting_inside:
        slab_populator.frame_outline_a = slab_populator.outline_a
    else:
        offset_inside = parameters.sheeting_inside / slab_populator.thickness
        pts_inside = []
        for pt_a, pt_b in zip(slab_populator.outline_a.points, slab_populator.outline_b.points):
            pt = pt_a * (1 - offset_inside) + pt_b * offset_inside
            pts_inside.append(pt)
        slab_populator.frame_outline_a = Polyline(pts_inside)

    if not parameters.sheeting_outside:
        slab_populator.frame_outline_b = slab_populator.outline_b
    else:
        offset_outside = parameters.sheeting_outside / slab_populator.thickness
        pts_outside = []
        for pt_a, pt_b in zip(slab_populator.outline_a.points, slab_populator.outline_b.points):
            pts_outside.append(pt_a * offset_outside + pt_b * (1 - offset_outside))

        slab_populator.frame_outline_b = Polyline(pts_outside)

# ==========================================================================
# methods for edge beams
# ==========================================================================

def _create_edge_beams(parameters, slab_populator):
    """Get the edge beam definitions for the outer polyline of the slab."""
    segs, widths = [], []

    for i in range(slab_populator.edge_count):
        seg, width = _get_edge_beam_line_and_width(slab_populator, i, min_width=parameters.edge_beam_min_width, edge_beam_dim_increment=parameters.standard_beam_width_increment)
        segs.append(seg)
        widths.append(width)
    extend_lines_pairwise(segs)
    for seg, width, i in zip(segs, widths, range(slab_populator.edge_count)):
        beam = Beam.from_centerline(seg, width=width, height=slab_populator.frame_thickness, z_vector=Vector(0, 0, 1))
        _set_edge_beam_category(slab_populator, beam, i)
        _apply_linear_cut_to_edge_beam(beam, slab_populator, i)
        slab_populator.add_element(beam, edge_index=i)

def _get_edge_beam_line_and_width(slab_populator, segment_index, min_width=0.0, edge_beam_dim_increment=None):
    perp_vector = slab_populator.edge_perpendicular_vectors[segment_index]
    seg_a = slab_populator.frame_outline_a.lines[segment_index]
    seg_b = slab_populator.frame_outline_b.lines[segment_index]
    dot = dot_vectors(perp_vector, Vector.from_start_end(seg_a.start, seg_b.start))
    if TOL.is_zero(dot): #edges are perpendicular to slab
        outer_segment = Line(Point(seg_a.start[0], seg_a.start[1], 0), Point(seg_a.end[0], seg_a.end[1], 0))
        width =  min_width
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
    if abs(beam.centerline.direction[0]) < abs(beam.centerline.direction[1]):
        beam.attributes["category"] = "edge_stud"
    else:
        if dot_vectors(slab_populator.edge_perpendicular_vectors[index], Vector(0, 1, 0)) < 0:
            beam.attributes["category"] = "bottom_plate_beam"
        else:
            beam.attributes["category"] = "top_plate_beam"

def _apply_linear_cut_to_edge_beam(beam, slab_populator, index):
    """Trim the edge beams to fit between the plate beams."""
    plane = slab_populator.edge_planes[index]
    if not TOL.is_zero(dot_vectors(Vector(0, 0, 1), plane.normal)):
        long_cut = LongitudinalCutProxy.from_plane_and_beam(plane, beam, is_joinery=False)
        beam.add_features(long_cut)

# ==========================================================================
# methods for beam joints
# ==========================================================================

def _create_edge_joints(parameters, slab_populator):
    """Generate the joint definitions for the slab edges. When there is an interface, we use the interface.detail_set to create the joint definition."""
    for corner_index in range(slab_populator.edge_count):
        edge_a_index = corner_index
        edge_b_index = (edge_a_index - 1) % slab_populator.edge_count
        interior_corner = edge_a_index in slab_populator.interior_corner_indices
        rule = _create_edge_beam_joint_rule(parameters, slab_populator, edge_a_index, edge_b_index, interior_corner)
        slab_populator.direct_rules.append(rule)

def _create_edge_beam_joint_rule(parameters, slab_populator, edge_a_index, edge_b_index, interior_corner):
    """Generate the joint definition between two edge beams. Used when there is no interface on either edge."""
    beam_a = slab_populator.edge_beams[edge_a_index][-1]
    beam_b = slab_populator.edge_beams[edge_b_index][0]
    beam_a_slope = abs(dot_vectors(beam_a.frame.xaxis, Vector(0, 1, 0)))
    beam_b_slope = abs(dot_vectors(beam_b.frame.xaxis, Vector(0, 1, 0)))
    edge_plane_a = slab_populator.edge_planes[edge_a_index]
    edge_plane_b = slab_populator.edge_planes[edge_b_index]

    if interior_corner:
        if beam_a_slope < beam_b_slope:  # b = main, a = cross
            plane = Plane(edge_plane_a.point, -edge_plane_a.normal)  # plane comes from edge a
            direct_rule = parameters.get_direct_rule_from_elements(beam_b, beam_a, butt_plane=plane.transformed(beam_b.transformation_to_local()))
        else:  # a = main, b = cross
            plane = Plane(edge_plane_b.point, -edge_plane_b.normal)
            direct_rule = parameters.get_direct_rule_from_elements(beam_a, beam_b, butt_plane=plane.transformed(beam_a.transformation_to_local()))
    else:
        if beam_a_slope < beam_b_slope:  # b = main, a = cross
            direct_rule = parameters.get_direct_rule_from_elements(beam_b, beam_a, back_plane=edge_plane_b.transformed(beam_b.transformation_to_local()))
        else:  # a = main, b = cross
            direct_rule = parameters.get_direct_rule_from_elements(beam_a, beam_b, back_plane=edge_plane_a.transformed(beam_a.transformation_to_local()))

    return direct_rule

# ==========================================================================
# methods for stud beams
# ==========================================================================



def create_studs(parameters, slab_populator, intersecting_features=None):
    """Generates the stud beams."""
    min_length = parameters.standard_beam_width
    x_position = parameters.stud_spacing
    intersecting_features = intersecting_features or []
    studs = []
    while x_position < slab_populator.obb.xmax - parameters.beam_dimensions["stud"][0]:
        raw_stud = parameters.beam_from_category(Line.from_point_and_vector((x_position, 0, 0), (0, 1, 0)), "stud")
        intersections = []
        for ft in intersecting_features:
            simple_intersections, corner_intersections, notch_intersections, lap_intersections = get_beam_edges_feature_def_intersection(raw_stud, ft)
            if notch_intersections or lap_intersections:
                slab_populator.test.extend([i.get("point") for i in notch_intersections+lap_intersections])
            if simple_intersections or corner_intersections:
                intersections.extend(simple_intersections + corner_intersections)
        intersections = sorted(intersections, key=lambda x: x.get("dot"))
        for pair in pairwise(intersections):
            # cull short studs
            if pair[0]["point"].distance_to_point(pair[1]["point"]) < min_length:
                continue
            # cull studs outside inner outline
            stud = parameters.beam_from_category(Line(pair[0]["point"], pair[1]["point"]), "stud")
            skip = False
            for ft in intersecting_features:
                if ft.parameters.cull_stud(slab_populator, stud, ft):
                    skip = True
                    break
            if skip:
                continue
            slab_populator.add_element(stud)
            for intersection in pair:
                for beam in intersection["beams"]:
                    params = intersection["feature_def"].parameters
                    dr = params.get_direct_rule_from_elements(stud, beam, location=intersection["point"])
                    slab_populator.direct_rules.append(dr)
        x_position += parameters.stud_spacing
    return studs

def _cull_stud(stud, feature_definition) -> bool:
    """Split the bottom plate beam for door openings."""
    if not is_point_in_polyline(stud.centerline.midpoint, feature_definition.outline, in_plane=False):
        return True
    return False

def create_plates(parameters, slab_populator, intersecting_features=None):
    if parameters.sheeting_inside:
        plate = Plate.from_outlines(slab_populator.outline_a, slab_populator.frame_outline_a)
        if intersecting_features:
            for feature_definition in intersecting_features:
                feature_definition.parameters.apply_to_plate(plate, feature_definition)
        slab_populator.add_element(plate)
    if parameters.sheeting_outside:
        plate = Plate.from_outlines(slab_populator.outline_b, slab_populator.frame_outline_b)
        if intersecting_features:
            for feature_definition in intersecting_features:
                feature_definition.parameters.apply_to_plate(plate, feature_definition)
        slab_populator.add_element(plate)



class SlabElementGeneratorParameters(ElementGeneratorParameters):
    """Base class for opening detail sets.

    Parameters
    ----------
    beam_width_overrides : dict, optional
        A dictionary of beam width overrides for specific beam categories.
        key = beam category name, value = beam width.
    joint_rule_overrides : list[:class:`compas_timber.design.CategoryRule`], optional
        A list of category rules to override the default ones.
    """

    BEAM_CATEGORY_NAMES = []

    def __init__(
        self,
        stud_spacing,
        standard_beam_width,
        standard_beam_width_increment=None,
        edge_beam_min_width=None,
        stud_direction=None,
        sheeting_outside=0,
        sheeting_inside=0,
        beam_width_overrides=None,
        joint_rule_overrides=None,
    ):
        super(SlabElementGeneratorParameters, self).__init__(
            standard_beam_width,
            beam_width_overrides,
            joint_rule_overrides,
        )
        self.standard_beam_width_increment = standard_beam_width_increment
        self.edge_beam_min_width = edge_beam_min_width or standard_beam_width
        self.stud_spacing = stud_spacing
        self.stud_direction = stud_direction
        self.sheeting_outside = sheeting_outside
        self.sheeting_inside = sheeting_inside



class SlabElementGeneratorParametersA(SlabElementGeneratorParameters):
    """A slab detail set that uses the default edge beams, studs, and plates."""

    BEAM_CATEGORY_NAMES = ["stud", "edge_stud", "top_plate_beam", "bottom_plate_beam"]
    RULES = [
        CategoryRule(TButtJoint, "stud", "top_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(LButtJoint, "edge_stud", "edge_stud", mill_depth=10.0, max_distance=1.0),
        CategoryRule(LButtJoint, "edge_stud", "top_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(LButtJoint, "bottom_plate_beam", "top_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(LButtJoint, "top_plate_beam", "bottom_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(LButtJoint, "top_plate_beam", "top_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(LButtJoint, "bottom_plate_beam", "bottom_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(TButtJoint, "stud", "bottom_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(LButtJoint, "edge_stud", "bottom_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(TButtJoint, "stud", "edge_stud", mill_depth=10.0, max_distance=1.0),
        CategoryRule(TButtJoint, "stud", "detail", mill_depth=10.0, max_distance=1.0),
    ]


    def generate_edge_elements(self, slab_populator):
        """Populates the slab with elements and joints according to the detail set.

        Parameters
        ----------
        slab_populator : :class:`compas_timber.populators.SlabPopulator`
            The slab populator to populate.
        """
        self.update_beam_dimensions(slab_populator)
        _set_frame_outlines(self, slab_populator)
        _create_edge_beams(self, slab_populator)
        _create_edge_joints(self, slab_populator)

    def generate_stud_elements(self, slab_populator, intersecting_features=None):
        """Populates the slab with stud elements according to the detail set.

        Parameters
        ----------
        slab_populator : :class:`compas_timber.populators.SlabPopulator`
            The slab populator to populate.
        intersecting_features : list[:class:`compas_timber.populators.FeatureDefinition`], optional
            A list of feature definitions that intersect with the studs.
        """
        create_studs(self, slab_populator, intersecting_features=intersecting_features)

    def generate_plate_elements(self, slab_populator, intersecting_features=None):
        """Populates the slab with plate elements according to the detail set.

        Parameters
        ----------
        slab_populator : :class:`compas_timber.populators.SlabPopulator`
            The slab populator to populate.
        """
        create_plates(self, slab_populator, intersecting_features=intersecting_features)

    def cull_stud(self, slab_populator, stud, feature_def) -> bool:
        """Cull and split the studs for door openings."""
        return _cull_stud(stud, feature_def)

