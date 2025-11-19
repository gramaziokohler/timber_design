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
from .generator_functions import get_beam_edges_element_group_intersection
from .generator_functions import split_beam_with_element_groups
from .generator_functions import extend_beam_to_closest_element_groups
from timber_design.populators import FeatureBoundaryType
from timber_design.populators import ElementGroup
from timber_design.populators import SlabPopulator


BEAM_CATEGORY_NAMES = ["header", "sill", "king_stud", "jack_stud"]

# ==========================================================================
# Opening element creation functions
# ==========================================================================

def create_elements(parameters, feature):
    """Generate the beams for a opening."""
    frame_polyline = _create_frame_polyline(feature)
    segments = [line for line in frame_polyline.lines]
    segments[2].flip()   # align to slab populator stud direction

    # create beams
    edge_elements = OrderedDict()
    edge_elements[0] = [parameters.beam_from_category(segments[0], "king_stud", name="left_king_stud")]
    edge_elements[1] = [parameters.beam_from_category(segments[1], "header")]
    edge_elements[2] = [parameters.beam_from_category(segments[2], "king_stud", name="right_king_stud")]
    edge_elements[3] = [parameters.beam_from_category(segments[3], "sill")] if not parameters.door else []
    if parameters.lintel_posts:
        edge_elements[0].append(parameters.beam_from_category(segments[0], "jack_stud", name="left_jack_stud"))
        edge_elements[2].append(parameters.beam_from_category(segments[2], "jack_stud", name="right_jack_stud"))        

    elements=[]
    for beams in edge_elements.values():
        elements.extend(beams)

    _offset_frame_beams(edge_elements, frame_polyline)

    edges = _get_edge_dict(edge_elements, frame_polyline)
    outline = join_polyline_segments(list(edges.values()), close_loop=True)
    return ElementGroup(
        feature,
        parameters,
        elements=elements,
        edge_elements=edge_elements,
        edges=edges,  
        outline=outline,
        boundary_type=FeatureBoundaryType.EXCLUSIVE,
    )

def _create_frame_polyline(opening):
    """Bounding rectangle aligned orthogonal to the slab_populator.stud_direction."""
    box = Box.from_points(opening.outline_a.points)
    frame_polyline = Polyline([box.corner(0), box.corner(1), box.corner(2), box.corner(3), box.corner(0)])
    frame_polyline.translate(Vector(0,-0.001,0))
    for pt in frame_polyline.points:
        pt[2] = 0  # set to same plane as opening
    return frame_polyline


def _offset_frame_beams(edge_elements, frame_polyline):
    #offset so that the beam edges align with the frame polyline
    for edge_index, beams in edge_elements.items():
        vector = get_polyline_segment_perpendicular_vector(frame_polyline, edge_index)
        distance = 0
        for beam in beams[::-1]:
            beam.transform(Translation.from_vector(vector * (distance + beam.width * 0.5)))
            distance += beam.width


def _get_edge_dict(edge_elements, frame_polyline):
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

def get_internal_joints(parameters, element_group):
    """Join the sill and header to king and jack studs."""
    sill = list(filter(lambda x: x.attributes["category"] == "sill", element_group.elements))
    if sill:
        sill = sill[0]
    header = list(filter(lambda x: x.attributes["category"] == "header", element_group.elements))[0]
    king_studs = filter(lambda x: x.attributes["category"] == "king_stud", element_group.elements)
    jack_studs = filter(lambda x: x.attributes["category"] == "jack_stud", element_group.elements)
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
    return [rule for rule in rules if rule is not None]

def get_external_joints(parameters: ElementGeneratorParameters, element_group: ElementGroup, intersecting_groups: list[ElementGroup]):
    """Join the king and jack studs to neighboring slab populator beams."""
    rules = []
    for king_stud in filter(lambda x: x.attributes["category"] == "king_stud", element_group.elements):
        if king_stud is None:
            continue #TODO: error handling
        # extend king stud to closest intersecting features
        king_stud, bottom_int, top_int = extend_beam_to_closest_element_groups(king_stud, intersecting_groups)
        # create joints
        for intersection in [bottom_int, top_int]:
            for index in intersection["edge_indices"]:
                beams = intersection["element_group"].edge_elements.get(index, [])
                for beam in beams:
                    rules.append(parameters.get_direct_rule_from_elements(king_stud, beam))

    for jack_stud in filter(lambda x: x.attributes["category"] == "jack_stud", element_group.elements):
        if jack_stud is None:
            continue #TODO: error handling
        # extend jack stud to closest intersecting features
        jack_stud, bottom_int, _ = extend_beam_to_closest_element_groups(jack_stud, intersecting_groups, only_start=True)
        # create joints
        for index in bottom_int["edge_indices"]:
            beams = bottom_int["element_group"].edge_elements.get(index, [])
            for beam in beams:
                rules.append(parameters.get_direct_rule_from_elements(jack_stud, beam))
    return [rule for rule in rules if rule is not None]


# ==========================================================================
# Opening element culling functions
# ==========================================================================

def _cull_stud(stud: Beam, element_group: ElementGroup) -> bool:
    """Split the bottom plate beam for door openings."""
    element_group.elements.sort(key=lambda x: x.frame.point[0])  # sort left to right
    king_studs = filter(lambda x: x.attributes["category"] == "king_stud", element_group.elements)
    jack_studs = filter(lambda x: x.attributes["category"] == "jack_stud", element_group.elements)

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
    return _cull_beam_segment(stud, element_group)

def _cull_beam_segment(beam, element_group) -> bool:
    if is_point_in_polyline(beam.centerline.midpoint, element_group.outline, in_plane=False):
        return True
    return False

def cut_out_of_plate(plate, element_group):
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
        lines = [Line(element_group.feature.outline_a.points[i], element_group.feature.outline_b.points[i]) for i in range(len(element_group.feature.outline_a.points))]
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

    def __init__(self, standard_beam_width, lintel_posts = False, beam_width_overrides=None, joint_rule_overrides=None, door=False, split_bottom_plate_beam = False):
        super().__init__(standard_beam_width, beam_width_overrides, joint_rule_overrides)
        self.lintel_posts = lintel_posts
        self.split_bottom_plate_beam = split_bottom_plate_beam
        self.door = door
        if self.door:
            if self.split_bottom_plate_beam:
                self.rules=[r for r in self.rules if not (r.category_a == "jack_stud" and r.category_b == "bottom_plate_beam")]
                self.rules.append(
                    CategoryRule(
                        LButtJoint,
                        "jack_stud",
                        "bottom_plate_beam",
                    )
                )

    def generate_elements(self, feature):
        """Populates the slab with elements and joints according to the detail set.

        Parameters
        ----------
        slab_populator : :class:`compas_timber.populators.SlabPopulator`
            The slab populator to populate.
        """
        return create_elements(self, feature)


    def join_elements(self, slab_populator, element_group):
        """Join the elements for WindowDetailB."""
        intersecting_groups = [g for g in slab_populator.element_groups if g != element_group]
        rules = []
        rules.extend(get_external_joints(self, element_group, intersecting_groups))
        rules.extend(get_internal_joints(self, element_group))
        return [rule for rule in rules if rule is not None]

    def cull_stud(self, stud, element_group) -> bool:
        """determines whether a stud should be culled."""
        return _cull_stud(stud, element_group)

    def cull_beam_segment(self, stud, element_group) -> bool:
        """determines whether a beam segment should be culled. Typically checks for feature inclusion."""
        return _cull_beam_segment(stud, element_group)

    def apply_to_plate(self, plate, element_group):
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
        cut_out_of_plate(plate, element_group)

