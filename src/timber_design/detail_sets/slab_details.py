import math

from compas.geometry import Line
from compas.geometry import Plane
from compas.geometry import Point
from compas.geometry import Polyline
from compas.geometry import Vector
from compas.geometry import dot_vectors
from compas.geometry import intersection_line_segment
from compas.itertools import pairwise
from compas.tolerance import TOL
from compas_timber.connections import LButtJoint
from compas_timber.connections import TButtJoint
from compas_timber.elements import Beam
from compas_timber.elements import Plate
from compas_timber.fabrication import LongitudinalCutProxy
from compas_timber.utils import extend_lines_pairwise
from compas_timber.utils import intersection_line_beams
from compas_timber.utils import is_point_in_polyline

from timber_design.detail_sets import DetailBase
from timber_design.workflow import CategoryRule


class SlabDetailBase(DetailBase):
    """Contains one or more configuration set for the WallPopulator.

    Parameters
    ----------
    stud_spacing : float
        Space between the studs.
    beam_width : float
        Width of the beams.
    tolerance : :class:`compas_tolerances.Tolerance`, optional
        The tolerance for the populator.
    sheeting_outside : float, optional
        The thickness of the sheeting outside.
    sheeting_inside : float, optional
        The thickness of the sheeting inside.
    edge_stud_offset : float, optional
        Additional offset for the edge studs.
    custom_dimensions : dict, optional
        Custom cross section for the beams, by category. (e.g. {"bottom_plate_beam": (120, 60)})
    joint_overrides : list(`compas_timber.workflow.CategoryRule), optional
        List of joint rules to override the default ones.
    connection_details : dict, optional
        Mapping of `JointTopology` to and instace of ConnectionDetail class.

    """

    def __init__(
        self,
        stud_spacing,
        beam_width,
        stud_direction=None,
        sheeting_outside=0,
        sheeting_inside=0,
        beam_width_overrides=None,
        joint_overrides=None,
    ):
        super(SlabDetailBase, self).__init__(beam_width_overrides, joint_overrides)
        self.stud_spacing = stud_spacing
        self.beam_width = beam_width
        self.stud_direction = stud_direction
        self.sheeting_outside = sheeting_outside
        self.sheeting_inside = sheeting_inside
        self.test = []

    def __str__(self):
        return "SlabDetailSet({}, {}, {})".format(self.stud_spacing, self.beam_width, self.stud_direction)

    @classmethod
    def default(cls, stud_spacing, beam_width):
        return cls(stud_spacing, beam_width)

    def populate_details(self, slab_populator):
        raise NotImplementedError("Subclasses of SlabDetailBase must implement the populate_details method.")

    # ==========================================================================
    # methods for preparaing slab populator
    # ==========================================================================

    def _set_frame_outlines(self, slab_populator):
        """Handles the sheeting offsets for the slab outlines."""
        """This method creates new outlines for the beam frame based on the sheeting thicknesses."""
        if not self.sheeting_inside:
            slab_populator.frame_outline_a = slab_populator.outline_a
        else:
            offset_inside = self.sheeting_inside / slab_populator.thickness
            pts_inside = []
            for pt_a, pt_b in zip(slab_populator.outline_a.points, slab_populator.outline_b.points):
                pt = pt_a * (1 - offset_inside) + pt_b * offset_inside
                pts_inside.append(pt)
            slab_populator.frame_outline_a = Polyline(pts_inside)

        if not self.sheeting_outside:
            slab_populator.frame_outline_b = slab_populator.outline_b
        else:
            offset_outside = self.sheeting_outside / slab_populator.thickness
            pts_outside = []
            for pt_a, pt_b in zip(slab_populator.outline_a.points, slab_populator.outline_b.points):
                pts_outside.append(pt_a * offset_outside + pt_b * (1 - offset_outside))

            slab_populator.frame_outline_b = Polyline(pts_outside)

    # ==========================================================================
    # methods for edge beams
    # ==========================================================================

    def _create_edge_beams(self, slab_populator, min_width=None, edge_beam_dim_increment=None):
        """Get the edge beam definitions for the outer polyline of the slab."""
        if min_width is None:
            min_width = self.beam_width
        elements = []
        segs, widths = [], []

        for i in range(slab_populator.edge_count):
            seg, width = self._get_edge_beam_line_and_width(slab_populator, i, min_width=min_width, edge_beam_dim_increment=edge_beam_dim_increment)
            segs.append(seg)
            widths.append(width)
        extend_lines_pairwise(segs)
        for seg, width, i in zip(segs, widths, range(slab_populator.edge_count)):
            beam = Beam.from_centerline(seg, width=width, height=slab_populator.frame_thickness, z_vector=Vector(0, 0, 1))
            beam.attributes["edge_index"] = i
            self._set_edge_beam_category(slab_populator, beam)
            self._apply_linear_cut_to_edge_beam(beam, slab_populator)
            slab_populator.add_element(beam)
        return elements

    def _get_edge_beam_line_and_width(self, slab_populator, segment_index, min_width=0.0, edge_beam_dim_increment=None):
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

    def _set_edge_beam_category(self, slab_populator, beam):
        if abs(beam.centerline.direction[0]) < abs(beam.centerline.direction[1]):
            beam.attributes["category"] = "edge_stud"
        else:
            if dot_vectors(slab_populator.edge_perpendicular_vectors[beam.attributes["edge_index"]], Vector(0, 1, 0)) < 0:
                beam.attributes["category"] = "bottom_plate_beam"
            else:
                beam.attributes["category"] = "top_plate_beam"

    def _apply_linear_cut_to_edge_beam(self, beam, slab_populator):
        """Trim the edge beams to fit between the plate beams."""
        plane = slab_populator.edge_planes[beam.attributes["edge_index"]]
        if not TOL.is_zero(dot_vectors(Vector(0, 0, 1), plane.normal)):
            long_cut = LongitudinalCutProxy.from_plane_and_beam(plane, beam, is_joinery=False)
            beam.add_features(long_cut)

    # ==========================================================================
    # methods for beam joints
    # ==========================================================================

    def _create_edge_joints(self, slab_populator):
        """Generate the joint definitions for the slab edges. When there is an interface, we use the interface.detail_set to create the joint definition."""
        for corner_index in range(slab_populator.edge_count):
            edge_a_index = corner_index
            edge_b_index = (edge_a_index - 1) % slab_populator.edge_count
            interior_corner = edge_a_index in slab_populator.interior_corner_indices
            rule = self._create_edge_beam_joint_rule(slab_populator, edge_a_index, edge_b_index, interior_corner)
            rule.joint_type.create(slab_populator, *rule.elements, **rule.kwargs)

    def _create_edge_beam_joint_rule(self, slab_populator, edge_a_index, edge_b_index, interior_corner):
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
                direct_rule = self.get_direct_rule_from_elements(beam_b, beam_a, butt_plane=plane.transformed(beam_b.transformation_to_local()))
            else:  # a = main, b = cross
                plane = Plane(edge_plane_b.point, -edge_plane_b.normal)
                direct_rule = self.get_direct_rule_from_elements(beam_a, beam_b, butt_plane=plane.transformed(beam_a.transformation_to_local()))
        else:
            if beam_a_slope < beam_b_slope:  # b = main, a = cross
                direct_rule = self.get_direct_rule_from_elements(beam_b, beam_a, back_plane=edge_plane_b.transformed(beam_b.transformation_to_local()))
            else:  # a = main, b = cross
                direct_rule = self.get_direct_rule_from_elements(beam_a, beam_b, back_plane=edge_plane_a.transformed(beam_a.transformation_to_local()))

        return direct_rule

    # ==========================================================================
    # methods for stud beams
    # ==========================================================================

    def _create_and_join_studs(self, slab_populator, min_length=0.0):
        """Generates the stud beams."""
        min_length = self.beam_width_overrides.get("stud", None) or self.beam_width
        x_position = self.stud_spacing
        beam_dimensions = self.get_beam_dimensions(slab_populator)
        studs = []
        while x_position < slab_populator.obb.xmax - beam_dimensions["stud"][0]:
            # get intersections with edge beams and openings and interfaces
            intersections = intersection_line_beams(
                Line(Point(x_position, 0, 0), Point(x_position, 1, 0)),
                [b for b in slab_populator.elements() if b.attributes.get("edge_index", None) is not None],
                max_distance=self.beam_width,
            )
            if not intersections:
                break

            intersections = sorted(intersections, key=lambda x: x.get("dot"))
            for pair in pairwise(intersections):
                if pair[0]["point"].distance_to_point(pair[1]["point"]) < min_length:
                    continue
                if not is_point_in_polyline((pair[0]["point"] + pair[1]["point"]) / 2, slab_populator.edge_beams_inner_outline, in_plane=False):
                    continue
                beam = self.beam_from_category(Line(pair[0]["point"], pair[1]["point"]), "stud", slab_populator)
                slab_populator.add_element(beam)
                for intersection in pair:
                    rule = self.get_direct_rule_from_elements(beam, intersection["beam"])
                    rule.joint_type.create(slab_populator, beam, intersection["beam"], point=intersection["point"], **rule.kwargs)
            x_position += self.stud_spacing
        return studs


    def _create_and_join_studs(self, slab_populator, min_length=0.0):
        """Generates the stud beams."""
        min_length = self.beam_width_overrides.get("stud", None) or self.beam_width
        x_position = self.stud_spacing
        beam_dimensions = self.get_beam_dimensions(slab_populator)
        studs = []
        i=0
        while x_position < slab_populator.obb.xmax - beam_dimensions["stud"][0]:
            # get intersections with edge beams and openings and interfaces
            edge_a = (Line(Point(x_position-beam_dimensions["stud"][0]/2, 0, 0), Point(x_position-beam_dimensions["stud"][0]/2, 1, 0)))
            edge_b = (Line(Point(x_position+beam_dimensions["stud"][0]/2, 0, 0), Point(x_position+beam_dimensions["stud"][0]/2, 1, 0)))
            intersections_a = {}
            intersections_b = {}
            for index, line in slab_populator.edge_beams_inner_edges.items():
                pt = intersection_line_segment(edge_a, line)[0]
                if pt:
                    intersections_a[index] = {"point": Point(*pt), "dot": dot_vectors(Vector.from_start_end(edge_a.start, pt), line.direction)}
                pt = intersection_line_segment(edge_b, line)[0]
                if pt:
                    intersections_b[index] = {"point": Point(*pt), "dot": dot_vectors(Vector.from_start_end(edge_b.start, pt), line.direction)}

            simple_intersections, corner_intersections, notch_intersections, lap_intersections = self.classify_intersections(intersections_a, intersections_b, slab_populator)

            intersections = simple_intersections + corner_intersections

            intersections = sorted(intersections, key=lambda x: x.get("dot"))
            for pair in pairwise(intersections):
                # cull short studs
                if pair[0]["point"].distance_to_point(pair[1]["point"]) < min_length:
                    continue
                # cull studs outside inner outline
                if not is_point_in_polyline((pair[0]["point"] + pair[1]["point"]) / 2, slab_populator.edge_beams_inner_outline, in_plane=False):
                    continue
                stud = self.beam_from_category(Line(pair[0]["point"], pair[1]["point"]), "stud", slab_populator)
                slab_populator.add_element(stud)
                for intersection in pair:
                    for beam in intersection["beams"]:
                        rule = self.get_direct_rule_from_elements(stud, beam)
                        rule.joint_type.create(slab_populator, stud, beam, point=intersection["point"], **rule.kwargs)
            x_position += self.stud_spacing
            i+=1
        return studs


    def classify_intersections(self, intersections_a, intersections_b, slab_populator):
        simple_keys = list(set(intersections_a).intersection(set(intersections_b)))
        simple_intersections = []
        for i in simple_keys:
            simple_intersections.append({"point": (intersections_a[i]["point"] + intersections_b[i]["point"]) / 2, "dot": (intersections_a[i]["dot"] + intersections_b[i]["dot"]) / 2, "beams": [slab_populator.edge_beams[i][0]]})
        leftovers_a = list(set(intersections_a)-set(intersections_b))
        leftovers_b = list(set(intersections_b)-set(intersections_a))
        corner_intersections = []
        notch_intersections = []
        lap_intersections = []

        while leftovers_a:
            ia = leftovers_a.pop()
            for i_adjacent in [(ia-1)%slab_populator.edge_count, (ia+1)%slab_populator.edge_count]:
                if i_adjacent in leftovers_b:
                    ib = leftovers_b.pop(leftovers_b.index(i_adjacent))
                    intersection = {"point": (intersections_a[ia]["point"] + intersections_b[ib]["point"]) / 2, "dot": (intersections_a[ia]["dot"] + intersections_b[ib]["dot"]) / 2, "beams": [slab_populator.edge_beams[ia][0], slab_populator.edge_beams[ib][0]]}
                    corner_intersections.append(intersection)
                    break
                elif i_adjacent in leftovers_a:
                    ia_b = leftovers_a.pop(leftovers_a.index(i_adjacent))
                    intersection = {"point": (intersections_a[ia]["point"] + intersections_a[ia_b]["point"]) / 2, "dot": (intersections_a[ia]["dot"] + intersections_a[ia_b]["dot"]) / 2, "beams": [slab_populator.edge_beams[ia][0], slab_populator.edge_beams[ia_b][0]]}
                    corner_intersections.append(intersection)
                    break
            else:
                lap_intersections.append({"point": intersections_a[ia]["point"], "dot": intersections_a[ia]["dot"], "beams": [slab_populator.edge_beams[ia][0]]})


        while leftovers_b:
            ib = leftovers_b.pop()
            for i_adjacent in [(ib-1)%slab_populator.edge_count, (ib+1)%slab_populator.edge_count]:
                if i_adjacent in leftovers_b:
                    ib_b = leftovers_b.pop(leftovers_b.index(i_adjacent))
                    intersection = {"point": (intersections_b[ib]["point"] + intersections_b[ib_b]["point"]) / 2, "dot": (intersections_b[ib]["dot"] + intersections_b[ib_b]["dot"]) / 2, "beams": [slab_populator.edge_beams[ib][0], slab_populator.edge_beams[ib_b][0]]}
                    corner_intersections.append(intersection)
                    break
            else:
                lap_intersections.append({"point": intersections_b[ib]["point"], "dot": intersections_b[ib]["dot"], "beams": [slab_populator.edge_beams[ib][0]]})


        return simple_intersections, corner_intersections, notch_intersections, lap_intersections




    def _create_plates(self, slab_populator):
        if self.sheeting_inside:
            plate = Plate.from_outlines(slab_populator.outline_a, slab_populator.frame_outline_a)
            slab_populator.add_element(plate)
        if self.sheeting_outside:
            slab_populator.add_element(Plate.from_outlines(slab_populator.outline_b, slab_populator.frame_outline_b))


class SlabDetailA(SlabDetailBase):
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

    def populate_details(self, slab_populator):
        """Populates the slab with elements and joints according to the detail set.

        Parameters
        ----------
        slab_populator : :class:`compas_timber.populators.SlabPopulator`
            The slab populator to populate.
        """
        self._set_frame_outlines(slab_populator)
        self._create_edge_beams(slab_populator, edge_beam_dim_increment=60.0)
        self._create_edge_joints(slab_populator)
        self._create_and_join_studs(slab_populator)
        self._create_plates(slab_populator)


class SlabDetailB(SlabDetailBase):
    """A slab detail set that uses the edge beams and plates but no studs."""

    BEAM_CATEGORY_NAMES = ["stud", "edge_stud", "top_plate_beam", "bottom_plate_beam"]
    RULES = [
        CategoryRule(LButtJoint, "edge_stud", "top_plate_beam", mill_depth=10.0),
        CategoryRule(LButtJoint, "edge_stud", "bottom_plate_beam", mill_depth=10.0),
    ]

    def populate_details(self, slab_populator):
        """Populates the slab with elements and joints according to the detail set.

        Parameters
        ----------
        slab_populator : :class:`compas_timber.populators.SlabPopulator`
            The slab populator to populate.
        """
        self._set_frame_outlines(slab_populator)
        self._create_edge_beams(slab_populator, edge_beam_dim_increment=60.0)
        self._create_edge_joints(slab_populator)
        self._create_plates(slab_populator)

