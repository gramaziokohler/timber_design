from collections import OrderedDict

from compas.geometry import Box
from compas.geometry import Translation
from compas.geometry import Line
from compas.geometry import Polyline
from compas.geometry import Vector
from compas.geometry import dot_vectors
from compas.geometry import intersection_line_plane
from compas_timber.connections import LButtJoint
from compas_timber.connections import TButtJoint
from compas_timber.fabrication.free_contour import FreeContour
from compas_timber.utils import do_segments_overlap
from compas_timber.utils import get_polyline_segment_perpendicular_vector
from compas_timber.utils import intersection_line_beams
from compas_timber.utils import is_point_in_polyline
from compas_timber.utils import extend_lines_pairwise


from timber_design.workflow import CategoryRule
from timber_design.element_generators import ElementGeneratorParameters
from .generator_functions import get_beam_edges_feature_def_intersection
from timber_design.populators.populator import FeatureBoundaryType





BEAM_CATEGORY_NAMES = ["header", "sill", "king_stud", "jack_stud"]

def _create_frame_polyline(opening):
    """Bounding rectangle aligned orthogonal to the slab_populator.stud_direction."""
    box = Box.from_points(opening.outline_a.points)
    frame_polyline = Polyline([box.corner(0), box.corner(1), box.corner(2), box.corner(3), box.corner(0)])
    for pt in frame_polyline.points:
        pt[2] = 0  # set to same plane as opening
    return frame_polyline

def _create_jack_studs(parameters, slab_populator, beams):
    beam_a = parameters.beam_from_category(beams[2].centerline, "jack_stud")
    beam_b = parameters.beam_from_category(beams[0].centerline, "jack_stud")
    slab_populator.add_element(beam_a)
    slab_populator.add_element(beam_b)
    beams[2].transform(Translation.from_vector([(parameters.beam_dimensions["jack_stud"][0] + parameters.beam_dimensions["king_stud"][0]) * 0.5,0,0]))
    beams[0].transform(Translation.from_vector([-(parameters.beam_dimensions["jack_stud"][0] + parameters.beam_dimensions["king_stud"][0]) * 0.5,0,0]))
    return [beam_a, beam_b]


def create_elements(parameters, slab_populator, feature_definition):
    """Generate the beams for a opening."""
    parameters.update_beam_dimensions(slab_populator)
    frame_polyline = _create_frame_polyline(feature_definition.feature)
    segments = [line for line in frame_polyline.lines]
    for i in range(4):
        if dot_vectors(segments[i].direction, [0,1,0]) < 0:
            segments[i] = Line(segments[i].end, segments[i].start)  # reverse the segment to match the stud direction
    beam_edge_dict = OrderedDict()
    beam_edge_dict[0] = {"beam": parameters.beam_from_category(segments[0], "king_stud")}
    beam_edge_dict[1] = {"beam": parameters.beam_from_category(segments[1], "header")}
    beam_edge_dict[2] = {"beam": parameters.beam_from_category(segments[2], "king_stud")}
    beam_edge_dict[3] = {"beam": parameters.beam_from_category(segments[3], "sill")}
    for index, beam in beam_edge_dict.items():
        vector = get_polyline_segment_perpendicular_vector(frame_polyline, index)
        beam["beam"].transform(Translation.from_vector(vector * beam["beam"].width * 0.5))
        slab_populator.add_element(beam["beam"])
        feature_definition.elements.append(beam["beam"])
    if parameters.lintel_posts:
        feature_definition.elements.extend(_create_jack_studs(parameters, slab_populator, [val["beam"] for val in beam_edge_dict.values()]))
    for index, dict in beam_edge_dict.items():
        vector = get_polyline_segment_perpendicular_vector(frame_polyline, index)
        beam_edge_dict[index]["edge"] = dict["beam"].centerline.translated(vector * dict["beam"].width / 2)
    segs = [val["edge"] for val in beam_edge_dict.values()]
    extend_lines_pairwise(segs)
    outline = Polyline([seg.start for seg in segs]+[segs[0].start])
    feature_definition.element_edge_dict = beam_edge_dict
    feature_definition.outline = outline
    feature_definition.boundary_type = FeatureBoundaryType.EXCLUSIVE

def _join_sill_header(parameters, slab_populator, feature_definition):
    """Join the sill and header to neighboring slab populator beams."""
    sill = list(filter(lambda x: x.attributes.get("category", None) == "sill", feature_definition.elements))[0]
    header = list(filter(lambda x: x.attributes.get("category", None) == "header", feature_definition.elements))[0]
    jack_studs = list(filter(lambda x: x.attributes.get("category", None) == "jack_stud", feature_definition.elements))
    king_studs = list(filter(lambda x: x.attributes.get("category", None) == "king_stud", feature_definition.elements))

    for beam in jack_studs:
        slab_populator.direct_rules.append(parameters.get_direct_rule_from_elements(sill, beam, max_distance=beam.width/2))
        slab_populator.direct_rules.append(parameters.get_direct_rule_from_elements(beam, header, max_distance=beam.width/2))

    for beam in king_studs:
        if not parameters.lintel_posts:
            slab_populator.direct_rules.append(parameters.get_direct_rule_from_elements(sill, beam, max_distance=beam.width/2))
        slab_populator.direct_rules.append(parameters.get_direct_rule_from_elements(header, beam, max_distance=beam.width/2))


def _join_king_studs(parameters, slab_populator, opening_feature_definition, intersecting_features):
    """Extend king studs and join them to neighboring slab populator beams."""
    for king_stud in list(filter(lambda x: x.attributes.get("category", None) == "king_stud", opening_feature_definition.elements)):
        intersections = []
        # get beams to intersect with
        beams = []
        for val in slab_populator.edge_beams.values():
            beams.extend(val)
        intersections = []
        for ft in intersecting_features:
            if ft != opening_feature_definition:
                simple_intersections, corner_intersections, notch_intersections, lap_intersections = get_beam_edges_feature_def_intersection(king_stud, ft)
                if not simple_intersections and not corner_intersections:
                    continue
                intersections.extend(simple_intersections + corner_intersections)
        # get closest intersections above and below the king stud
        intersections.sort(key=lambda x: x["dot"])
        bottom_int = None
        top_int = None
        for intersection in intersections:
            if intersection["dot"] < 0:
                bottom_int = intersection
            else:
                top_int = intersection
                break
        # create joints
        king_stud.transform(Translation.from_vector(king_stud.frame.xaxis * bottom_int["dot"]))
        king_stud.length = top_int["dot"] - bottom_int["dot"]
        for intersection in [bottom_int, top_int]:
            for beam in intersection["beams"]:
                slab_populator.direct_rules.append(parameters.get_direct_rule_from_elements(king_stud, beam))

def _join_jack_studs(parameters, slab_populator, opening_feature_definition, intersecting_features):
    for jack_stud in list(filter(lambda x: x.attributes.get("category", None) == "jack_stud", opening_feature_definition.elements)):
        intersections = []
        # get beams to intersect with
        beams = []
        for val in slab_populator.edge_beams.values():
            beams.extend(val)
        intersections = []
        for ft in intersecting_features:
            if ft != opening_feature_definition:
                simple_intersections, corner_intersections, notch_intersections, lap_intersections = get_beam_edges_feature_def_intersection(jack_stud, ft)
                if not simple_intersections and not corner_intersections:
                    continue
                intersections.extend(simple_intersections + corner_intersections)

        intersections.sort(key=lambda x: x["dot"])
        bottom_int = None
        for intersection in intersections:
            if intersection["dot"] < 0:
                bottom_int = intersection
            else:
                break
        # create joints

        if bottom_int:
            jack_stud.transform(Translation.from_vector(jack_stud.frame.xaxis * bottom_int["dot"]))
            jack_stud.length = jack_stud.length - bottom_int["dot"]
            for beam in bottom_int["beams"]:
                slab_populator.direct_rules.append(parameters.get_direct_rule_from_elements(jack_stud, beam))



def _cull_stud(parameters, slab_populator, stud, feature_definition) -> bool:
    """Split the bottom plate beam for door openings."""


    header = list(filter(lambda x: x.attributes.get("category", None) == "header", feature_definition.elements))[0]
    king_studs = list(filter(lambda x: x.attributes.get("category", None) == "king_stud", feature_definition.elements))
    jack_studs = list(filter(lambda x: x.attributes.get("category", None) == "jack_stud", feature_definition.elements))
    king_studs.sort(key=lambda x: x.frame.point[0])
    jack_studs.sort(key=lambda x: x.frame.point[0])

    stud_x = stud.frame.point[0]
    for i in range(2):
        king = king_studs[i]
        king_x = king.frame.point[0]
        bounds = (king_x-(king.width / 2), king_x+(king.width / 2))
        if do_segments_overlap(stud.centerline, king.centerline):
            if stud_x + stud.width/2 > bounds[0] and stud_x - stud.width/2 < bounds[1]:
                return True
        if jack_studs:
            jack = jack_studs[i]
            if do_segments_overlap(stud.centerline, jack.centerline):
                jack_x = jack.frame.point[0]
                if i == 0:
                    bounds = (king_x-(king.width / 2), jack_x+(jack.width / 2))
                else: # right jack stud
                    bounds = (jack_x-(jack.width / 2), king_x+(king.width / 2))
                if stud_x + stud.width/2 > bounds[0] and stud_x - stud.width/2 < bounds[1]:
                    return True
    if is_point_in_polyline(stud.centerline.midpoint, feature_definition.outline, in_plane=False):
        return True
    return False



class OpeningElementGeneratorParameters(ElementGeneratorParameters):
    """A slab detail set that uses the edge beams and plates but no studs."""

    BEAM_CATEGORY_NAMES = ["header", "sill", "king_stud", "jack_stud"]


    RULES = [
        CategoryRule(TButtJoint, "header", "king_stud"),
        CategoryRule(TButtJoint, "jack_stud", "header"),
        CategoryRule(TButtJoint, "sill", "jack_stud"),
        CategoryRule(TButtJoint, "jack_stud", "header"),
        CategoryRule(TButtJoint, "jack_stud", "bottom_plate_beam"),
        CategoryRule(TButtJoint, "jack_stud", "edge_stud"),
        CategoryRule(TButtJoint, "king_stud", "bottom_plate_beam"),
        CategoryRule(TButtJoint, "king_stud", "top_plate_beam"),
        CategoryRule(TButtJoint, "king_stud", "header"),
        CategoryRule(TButtJoint, "king_stud", "sill"),
        CategoryRule(TButtJoint, "king_stud", "edge_stud"),
        CategoryRule(TButtJoint, "stud", "header"),
        CategoryRule(TButtJoint, "stud", "sill"),
    ]

    def __init__(self, standard_beam_width, lintel_posts = False, beam_width_overrides=None, joint_rule_overrides=None):
        super().__init__(standard_beam_width, beam_width_overrides, joint_rule_overrides)
        self.lintel_posts = lintel_posts


    def generate_elements(self, slab_populator, feature_def):
        """Populates the slab with elements and joints according to the detail set.

        Parameters
        ----------
        slab_populator : :class:`compas_timber.populators.SlabPopulator`
            The slab populator to populate.
        """
        self.update_beam_dimensions(slab_populator)
        return create_elements(self, slab_populator, feature_def)


    def join_elements(self, slab_populator, feature_def, intersecting_features = None):
        """Join the elements for WindowDetailB."""
        _join_jack_studs(self, slab_populator, feature_def, intersecting_features)
        _join_king_studs(self, slab_populator, feature_def, intersecting_features)
        _join_sill_header(self, slab_populator, feature_def)

    def cull_stud(self, slab_populator, stud, feature_def) -> bool:
        """Cull and split the studs for door openings."""
        return _cull_stud(self, slab_populator, stud, feature_def)

    def apply_to_plate(self, plate, feature_def):
        """Apply the opening contour to the given plate.

        Parameters
        ----------
        slab : :class:`compas_timber.elements.Slab`
            The slab to which the opening will be applied.

        Raises
        ------
        :class:`compas_timber.errors.FeatureApplicationError`
            If the opening cannot be applied to the slab.
        """
        lines = [Line(feature_def.feature.outline_a.points[i], feature_def.feature.outline_b.points[i]) for i in range(len(feature_def.feature.outline_a.points))]
        outline_a_projected = Polyline([intersection_line_plane(line, plate.planes[0]) for line in lines])
        outline_b_projected = Polyline([intersection_line_plane(line, plate.planes[1]) for line in lines])
        free_contour = FreeContour.from_top_bottom_and_elements(outline_a_projected, outline_b_projected, plate, interior=True)
        plate.add_feature(free_contour)

# Door methods

# BEAM_CATEGORY_NAMES = ["header", "king_stud", "jack_stud"]

# def _create_door_elements(parameters, opening, slab_populator):
#     """Generate the beams for a main interface."""
#     frame_polyline = _create_frame_polyline(opening, slab_populator)
#     segments = [line for line in frame_polyline.lines]
#     for i in range(4):
#         if dot_vectors(segments[i].direction, slab_populator.stud_direction) < 0:
#             segments[i] = Line(segments[i].end, segments[i].start)  # reverse the segment to match the stud direction
#     opening.beams.append(beam_from_category(parameters, segments[1], "header", slab_populator, opening_edge_index=1))
#     opening.beams.append(beam_from_category(parameters, segments[2], "king_stud", slab_populator, opening_edge_index=2))
#     opening.beams.append(beam_from_category(parameters, segments[0], "king_stud", slab_populator, opening_edge_index=0))
#     for beam in opening.beams:
#         vector = get_polyline_segment_perpendicular_vector(frame_polyline, beam.attributes["opening_edge_index"])
#         beam.frame.translate(vector * beam.width * 0.5)
#     _apply_plate_contour(opening, slab_populator)
#     return opening.beams

# def _apply_plate_contour(opening, slab_populator):
#     """Apply the plate contour to the given slab populator."""
#     outline = _get_adjusted_door_outline(opening, slab_populator)
#     for plate in slab_populator.plates:
#         feature = FreeContour.from_polyline_and_element(outline, plate)
#         plate.add_feature(feature)

# def _get_adjusted_door_outline(opening, slab_populator):
#     """Adjust the door outline for the given opening."""
#     outline = Polyline([p for p in opening.outline_a])
#     slab_index = _get_slab_segment_index(slab_populator._slab, outline)
#     if slab_index is None:
#         raise ValueError("Door outline does not intersect with the slab outline.")
#     door_index = _get_door_segment_index(outline, slab_populator.outline_a.lines[slab_index])
#     vector = slab_populator.edge_perpendicular_vectors[slab_index]
#     seg_a = slab_populator.outline_a.lines[slab_index]
#     seg_b = slab_populator.outline_b.lines[slab_index]
#     if dot_vectors(vector, seg_a.start) > dot_vectors(vector, seg_b.start):
#         plane = Plane(seg_a.start, vector)
#     else:
#         plane = Plane(seg_b.end, vector)
#     move_polyline_segment_to_plane(outline, door_index, plane)
#     return outline

# def _get_slab_segment_index(slab_populator, polyline):
#     """Get the index of the segment in the slab outline where the door is located."""
#     for pl in slab_populator.outlines:
#         for i, segment_a in enumerate(pl.lines):
#             for segment_b in polyline.lines:
#                 if intersection_segment_segment(segment_a, segment_b)[0]:
#                     return i
#     return None

# def _get_door_segment_index(polyline, segment):
#     """Get the index of the door outline segment that lies on the slab edge."""
#     lines = [line for line in polyline.lines]
#     sorted_lines = sorted(lines, key=lambda x: distance_point_line(x.midpoint, segment))
#     return lines.index(sorted_lines[0])

# def _split_edge_beam(opening, slab_populator):
#     """Split the edge beam for door openings."""

#     slab_index = _get_slab_segment_index(slab_populator, opening.frame_polyline)
#     if slab_index is None:
#         raise ValueError("Door outline does not intersect with the slab outline.")
#     door_index = _get_door_segment_index(opening.frame_polyline, slab_populator.outline_a.lines[slab_index])

#     edge_beam = slab_populator.edge_beams[slab_index][-1]
#     outline_edge = opening.frame_polyline.lines[door_index]
#     overlap = get_segment_overlap(edge_beam.centerline, outline_edge)

#     if overlap[0] is None:
#         raise ValueError("Edge beam does not intersect with the door outline.")

#     if not (overlap[0] > 0 and overlap[1] < edge_beam.length):
#         raise ValueError("Door outline must lay within the limits of a single slab edge.")

#     beams = split_beam_at_lengths(edge_beam, [overlap[0], overlap[1]])

#     slab_populator.edge_beams[slab_index].append(beams[2])






        # cull_and_split_studs(self, slab_populator, feature_def.elements, feature_def.polyline)
        # _create_plate_elements(opening, slab_populator)


# class DoorDetailAA(DoorDetailBase):
#     """Detail set for door openings without lintel posts and without splitting the bottom plate."""

#     RULES = [
#         CategoryRule(TButtJoint, "king_stud", "bottom_plate_beam"),
#         CategoryRule(TButtJoint, "king_stud", "top_plate_beam"),
#         CategoryRule(TButtJoint, "king_stud", "header"),
#         CategoryRule(TButtJoint, "header", "king_stud"),
#     ]


# class DoorDetailAB(DoorDetailBase):
#     """Detail set for door openings without lintel posts and with splitting the bottom plate."""

#     RULES = [
#         CategoryRule(LButtJoint, "king_stud", "bottom_plate_beam"),
#         CategoryRule(TButtJoint, "king_stud", "top_plate_beam"),
#         CategoryRule(TButtJoint, "king_stud", "header"),
#         CategoryRule(TButtJoint, "header", "king_stud"),
#     ]

#     def create_elements(self, opening, slab_populator):
#         """Generate the beams for a main interface."""
#         super(DoorDetailAB, self).create_elements(opening, slab_populator)
#         self._split_edge_beam(opening, slab_populator)
#         slab_populator.elements.extend(opening.beams)
#         return opening.beams


# class DoorDetailBA(DoorDetailBase):
#     """Detail set for door openings with lintel posts and without splitting the bottom plate."""

#     RULES = [
#         CategoryRule(TButtJoint, "king_stud", "bottom_plate_beam"),
#         CategoryRule(TButtJoint, "king_stud", "top_plate_beam"),
#         CategoryRule(TButtJoint, "king_stud", "header"),
#         CategoryRule(TButtJoint, "header", "king_stud"),
#     ]

#     def create_elements(self, opening, slab_populator):
#         """Generate the beams for a main interface."""
#         super(DoorDetailBA, self).create_elements(opening, slab_populator)
#         self._add_jack_studs(opening, slab_populator)
#         slab_populator.elements.extend(opening.beams)
#         return opening.beams


# class DoorDetailBB(DoorDetailBase):
#     """Detail set for door openings with lintel posts and with splitting the bottom plate."""

#     RULES = [
#         CategoryRule(TButtJoint, "header", "king_stud"),
#         CategoryRule(LButtJoint, "jack_stud", "header"),
#         CategoryRule(LButtJoint, "jack_stud", "bottom_plate_beam"),
#         CategoryRule(TButtJoint, "king_stud", "bottom_plate_beam"),
#         CategoryRule(TButtJoint, "king_stud", "top_plate_beam"),
#         CategoryRule(TButtJoint, "king_stud", "header"),
#     ]

#     def create_elements(self, opening, slab_populator):
#         """Generate the beams for a main interface."""
#         super(DoorDetailBB, self).create_elements(opening, slab_populator)
#         self._add_jack_studs(opening, slab_populator)
#         self._split_edge_beam(opening, slab_populator)
#         slab_populator.elements.extend(opening.beams)
#         return opening.beams
