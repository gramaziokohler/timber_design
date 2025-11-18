from collections import OrderedDict

from compas.geometry import Box
from compas.geometry import Translation
from compas.geometry import Line
from compas.geometry import Polyline
from compas.geometry import Vector
from compas.geometry import dot_vectors
from compas.geometry import intersection_line_plane
from compas.geometry import intersection_line_segment_xy

from compas_timber.elements import Beam
from compas_timber.elements import Plate
from compas_timber.connections import LButtJoint
from compas_timber.connections import TButtJoint
from compas_timber.fabrication.free_contour import FreeContour
from compas_timber.utils import do_segments_overlap
from compas_timber.utils import get_polyline_segment_perpendicular_vector
from compas_timber.utils import move_polyline_segment_to_line
from compas_timber.utils import is_point_in_polyline
from compas_timber.utils import extend_line_segments
from compas_timber.utils import join_polyline_segments


from timber_design.workflow import CategoryRule
from timber_design.element_generators import ElementGeneratorParameters
from .generator_functions import get_beam_edges_feature_def_intersection
from timber_design.populators import FeatureBoundaryType
from timber_design.populators import FeatureDefinition
from timber_design.populators import SlabPopulator


BEAM_CATEGORY_NAMES = ["header", "sill", "king_stud", "jack_stud"]

# ==========================================================================
# Opening element creation functions
# ==========================================================================

def create_elements(parameters, feature_definition):
    """Generate the beams for a opening."""
    frame_polyline = _create_frame_polyline(feature_definition.feature)
    segments = [line for line in frame_polyline.lines]
    segments[2].flip()   # align to slab populator stud direction

    elements = OrderedDict()
    elements["left_king_stud"] = parameters.beam_from_category(segments[0], "king_stud")
    elements["header"] = parameters.beam_from_category(segments[1], "header")
    elements["right_king_stud"] = parameters.beam_from_category(segments[2], "king_stud")
    if parameters.lintel_posts:
        elements["left_jack_stud"] = parameters.beam_from_category(segments[0], "jack_stud")
        elements["right_jack_stud"] = parameters.beam_from_category(segments[2], "jack_stud")
    if not parameters.extend_to_bottom_edge:
        elements["sill"] = parameters.beam_from_category(segments[3], "sill")


    edge_elements = OrderedDict()
    edge_elements[0] = [elements["left_king_stud"]]
    edge_elements[1] = [elements["header"]]
    edge_elements[2] = [elements["right_king_stud"]]
    if parameters.lintel_posts:
        edge_elements[0].append(elements["left_jack_stud"])
        edge_elements[2].append(elements["right_jack_stud"])
    if not parameters.extend_to_bottom_edge:
        edge_elements[3] = [elements["sill"]]
    _offset_frame_beams(edge_elements, frame_polyline)
    
    feature_definition.edges = _get_feature_edges(edge_elements, frame_polyline)
    feature_definition.outline = join_polyline_segments(list(feature_definition.edges.values()), close_loop=True)
    feature_definition.elements = elements
    feature_definition.edge_elements = edge_elements
    feature_definition.boundary_type = FeatureBoundaryType.EXCLUSIVE
    return feature_definition

def _create_frame_polyline(opening, slab_populator=None, extend_to_bottom_edge=False):
    """Bounding rectangle aligned orthogonal to the slab_populator.stud_direction."""
    box = Box.from_points(opening.outline_a.points)
    frame_polyline = Polyline([box.corner(0), box.corner(1), box.corner(2), box.corner(3), box.corner(0)])
    for pt in frame_polyline.points:
        pt[2] = 0  # set to same plane as opening
    if extend_to_bottom_edge and not slab_populator:
        raise ValueError("slab_populator must be provided to extend frame polyline to bottom edge.")
    if extend_to_bottom_edge and slab_populator:
        frame_polyline = _extend_frame_polyline_to_bottom_edge(slab_populator, frame_polyline)
    return frame_polyline

def _extend_frame_polyline_to_bottom_edge(slab_populator, frame_polyline):
    """Extend the frame outline to the bottom edge of the slab."""
    edge_index = None
    for i in range(slab_populator.edge_count):
        if intersection_line_segment_xy(frame_polyline.lines[0], slab_populator.outline_a.lines[i]):
            edge_index = i
            break
    if edge_index is None:
        raise ValueError("Could not find bottom edge for opening frame extension.")
    edge = min(slab_populator.outline_a.lines[edge_index], slab_populator.outline_b.lines[edge_index], key=lambda l: l.midpoint[1]) # choose lower edge
    return move_polyline_segment_to_line(frame_polyline, 3, edge)

def _offset_frame_beams(edge_elements, frame_polyline):
    #offset so that the beam edges align with the frame polyline
    for edge_index, beams in edge_elements.items():
        vector = get_polyline_segment_perpendicular_vector(frame_polyline, edge_index)
        distance = 0
        for beam in beams[::-1]:
            beam.transform(Translation.from_vector(vector * (distance + beam.width * 0.5)))
            distance += beam.width


def _get_feature_edges(edge_elements, frame_polyline):
    segs = []
    for index, segment in enumerate(frame_polyline.lines):
        beams = edge_elements.get(index)
        if not beams: # in case there is no sill
            segs.append(segment)
            continue
        vector = get_polyline_segment_perpendicular_vector(frame_polyline, index)
        segs.append(beams[0].centerline.translated(vector * beams[0].width / 2))
    edges = {}
    extend_line_segments(segs, close_loop=True)
    for i, segment in enumerate(segs):
        edges[i] = segment
    return edges




# ==========================================================================
# Opening element joining functions
# ==========================================================================    

def _get_internal_joints(parameters, feature_definition):
    """Join the sill and header to king and jack studs."""
    sill = feature_definition.elements.get("sill", None)
    header = feature_definition.elements.get("header", None)
    jack_studs = [feature_definition.elements.get("left_jack_stud", None), feature_definition.elements.get("right_jack_stud", None)]
    king_studs = [feature_definition.elements["left_king_stud"], feature_definition.elements["right_king_stud"]]
    rules = []
    #join header
    for king in king_studs:
        rules.append(parameters.get_direct_rule_from_elements(header, king, max_distance=king.width/2))
    for jack in jack_studs:
        if jack:
            rules.append(parameters.get_direct_rule_from_elements(jack, header, max_distance=jack.width/2))

    # join sill
    if sill:
        for jack, king in zip(jack_studs, king_studs):
            if jack:
                rules.append(parameters.get_direct_rule_from_elements(sill, jack, max_distance=jack.width/2))
            else:
                rules.append(parameters.get_direct_rule_from_elements(sill, king, max_distance=king.width/2))
    return rules

def _get_external_joints(parameters: ElementGeneratorParameters, feature_definition: FeatureDefinition, intersecting_features: list[FeatureDefinition]):
    """Join the king and jack studs to neighboring slab populator beams."""
    rules = []
    rules.extend(_join_jack_studs(parameters, feature_definition, intersecting_features))
    rules.extend(_join_king_studs(parameters, feature_definition, intersecting_features))
    return rules

def _join_king_studs(parameters: ElementGeneratorParameters, opening_feature_definition: FeatureDefinition, intersecting_features: list[FeatureDefinition]):
    """Extend king studs and join them to neighboring slab populator beams."""
    rules = []
    for king_stud in [opening_feature_definition.elements.get("left_king_stud", None), opening_feature_definition.elements.get("right_king_stud", None)]:
        if king_stud is None:
            continue #TODO: error handling

        # get intersections with other features
        intersections = []
        for ft in intersecting_features:
            if ft != opening_feature_definition:
                simple_intersections, corner_intersections, notch_intersections, lap_intersections = get_beam_edges_feature_def_intersection(king_stud, ft)
                if not simple_intersections and not corner_intersections:
                    continue
                intersections.extend(simple_intersections + corner_intersections)

        # get closest intersections above and below the king stud
        intersections.sort(key=lambda x: x["dot"])
        bottom_int = intersections[0] if parameters.extend_to_bottom_edge else None
        top_int = None
        previous_int = intersections.pop(0)
        if previous_int["dot"] > 0:
            raise ValueError("No intersection found below king stud: {}".format(king_stud))
        while intersections:
            current_int = intersections.pop(0)
            if not bottom_int and current_int["dot"] > 0:
                bottom_int = previous_int
            if current_int["dot"] > king_stud.length:
                top_int = current_int
                break
        
        #extend king stud 
        king_stud.transform(Translation.from_vector(king_stud.frame.xaxis * bottom_int["dot"]))
        king_stud.length = top_int["dot"] - bottom_int["dot"]
        
        # create joints
        for intersection in [bottom_int, top_int]:
            for beam in intersection["beams"]:
                rules.append(parameters.get_direct_rule_from_elements(king_stud, beam))
    return rules

def _join_jack_studs(parameters: ElementGeneratorParameters, opening_feature_definition: FeatureDefinition, intersecting_features: list[FeatureDefinition]):
    rules = []
    print("left.frame = ", opening_feature_definition.elements.get("left_jack_stud", None).frame.point)
    print("right.frame = ", opening_feature_definition.elements.get("right_jack_stud", None).frame.point)
    for jack_stud in [opening_feature_definition.elements.get("left_jack_stud", None), opening_feature_definition.elements.get("right_jack_stud", None)]:
        if jack_stud is None:
            continue #TODO: error handling

        # get intersections with other features
        intersections = []
        print("Finding jack stud intersections for:", jack_stud)
        for ft in intersecting_features:
            if ft != opening_feature_definition:
                simple_intersections, corner_intersections, notch_intersections, lap_intersections = get_beam_edges_feature_def_intersection(jack_stud, ft)
                if not simple_intersections and not corner_intersections:
                    continue
                intersections.extend(simple_intersections + corner_intersections)
        #get closest intersection below the opening
        intersections.sort(key=lambda x: x["dot"])
        # print("Jack stud intersections:", [(intersection["point"][1],intersection["dot"]) for intersection in intersections])
        if parameters.extend_to_bottom_edge:
            bottom_int = intersections[0]
        else:
            bottom_int =   None
            previous_int = intersections.pop(0)
            if previous_int["dot"] > 0:
                raise ValueError("No intersection found below jack stud: {}".format(jack_stud))
            while intersections:
                current_int = intersections.pop(0)
                if current_int["dot"] > 0:
                    bottom_int = previous_int
                    break
                previous_int = current_int

        if bottom_int:
            #extend jack stud 
            jack_stud.transform(Translation.from_vector(jack_stud.frame.xaxis * bottom_int["dot"]))
            jack_stud.length = jack_stud.length - bottom_int["dot"]
            # create joints
            for beam in bottom_int["beams"]:
                rules.append(parameters.get_direct_rule_from_elements(jack_stud, beam))
    return rules

# ==========================================================================
# Opening element culling functions
# ==========================================================================

def _cull_stud(stud: Beam, feature_definition: FeatureDefinition) -> bool:
    """Split the bottom plate beam for door openings."""
    king_studs = [feature_definition.elements["left_king_stud"], feature_definition.elements["right_king_stud"]]
    jack_studs = [feature_definition.elements.get("left_jack_stud"), feature_definition.elements.get("right_jack_stud")]

    stud_x = stud.frame.point[0]
    for king, jack, side in zip(king_studs, jack_studs, ["left", "right"]):
        king_x = king.frame.point[0]
        bounds = (king_x-(king.width / 2), king_x+(king.width / 2))
        # check king stud overlap
        if do_segments_overlap(stud.centerline, king.centerline):
            if stud_x + stud.width/2 > bounds[0] and stud_x - stud.width/2 < bounds[1]:
                return True
        if all(jack_studs):
            # check jack stud overlap
            if do_segments_overlap(stud.centerline, jack.centerline):
                jack_x = jack.frame.point[0]
                if side == "left":
                    bounds = (king_x-(king.width / 2), jack_x+(jack.width / 2))
                else: # right jack stud
                    bounds = (jack_x-(jack.width / 2), king_x+(king.width / 2))
                if stud_x + stud.width/2 > bounds[0] and stud_x - stud.width/2 < bounds[1]:
                    return True
    return _cull_beam_segment(stud, feature_definition)

def _cull_beam_segment(beam, feature_definition) -> bool:
    if is_point_in_polyline(beam.centerline.midpoint, feature_definition.outline, in_plane=False):
        return True
    return False

def cut_out_of_plate(plate, feature_def):
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
        free_contour = FreeContour.from_top_bottom_and_elements(outline_a_projected, outline_b_projected, plate, interior=True, is_joinery=False)
        plate.add_feature(free_contour)
        
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

    def __init__(self, standard_beam_width, lintel_posts = False, beam_width_overrides=None, joint_rule_overrides=None, extend_to_bottom_edge = False, split_bottom_plate_beam = False):
        super().__init__(standard_beam_width, beam_width_overrides, joint_rule_overrides)
        self.lintel_posts = lintel_posts
        self.extend_to_bottom_edge = extend_to_bottom_edge
        self.split_bottom_plate_beam = split_bottom_plate_beam

    def generate_elements(self, feature_def):
        """Populates the slab with elements and joints according to the detail set.

        Parameters
        ----------
        slab_populator : :class:`compas_timber.populators.SlabPopulator`
            The slab populator to populate.
        """
        return create_elements(self, feature_def)


    def join_elements(self, slab_populator, feature_def):
        """Join the elements for WindowDetailB."""
        intersecting_features = slab_populator.feature_definitions
        rules = []
        print("joining opening elements")
        rules.extend(_get_external_joints(self, feature_def, intersecting_features))
        rules.extend(_get_internal_joints(self, feature_def))
        return rules

    def cull_stud(self, stud, feature_def) -> bool:
        """determines whether a stud should be culled."""
        return _cull_stud(stud, feature_def)

    def cull_beam_segment(self, stud, feature_def) -> bool:
        """determines whether a beam segment should be culled. Typically checks for feature inclusion."""
        return _cull_beam_segment(stud, feature_def)

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
        cut_out_of_plate(plate, feature_def)

