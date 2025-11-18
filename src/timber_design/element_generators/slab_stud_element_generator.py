from compas.geometry import Line
from compas.itertools import pairwise
from compas.tolerance import TOL
from compas_timber.connections import LButtJoint
from compas_timber.connections import TButtJoint


from compas_timber.design import CategoryRule
from timber_design.element_generators import ElementGeneratorParameters
from timber_design.populators import FeatureDefinition
from timber_design.workflow import DirectRule
from .generator_functions import get_beam_edges_feature_def_intersection

# ==========================================================================
# methods for stud beams
# ==========================================================================

def create_studs(parameters, slab_populator):
    """Generates the stud beams."""
    x_position = parameters.stud_spacing
    studs = {}
    while x_position < slab_populator.obb.xmax - parameters.beam_dimensions["stud"][0]:
        studs[x_position] = parameters.beam_from_category(Line.from_point_and_vector((x_position, 0, 0), (0, slab_populator.width, 0)), "stud")
        x_position += parameters.stud_spacing
    return FeatureDefinition(slab_populator, parameters, elements=studs)

def join_studs(parameters, slab_populator, studs):
    """Joins the stud beams."""
    intersecting_features= slab_populator.feature_definitions
    min_length = parameters.beam_dimensions["stud"][0]
    rules = []
    for raw_stud in studs:
        intersections = []
        for ft in intersecting_features:
            simple_intersections, corner_intersections, notch_intersections, lap_intersections = get_beam_edges_feature_def_intersection(raw_stud, ft)
            if simple_intersections or corner_intersections:
                intersections.extend(simple_intersections + corner_intersections)
        print("intersection x values for raw_stud at", raw_stud.frame.point.x, ":", [i["point"].x for i in intersections])
        intersections = sorted(intersections, key=lambda x: x.get("dot"))
        slab_populator.remove_element(raw_stud)

        for pair in pairwise(intersections):
            # cull short studs
            if pair[0]["point"].distance_to_point(pair[1]["point"]) < min_length:
                continue
            # cull studs outside inner outline
            stud = parameters.beam_from_category(Line(pair[0]["point"], pair[1]["point"]), "stud")
            skip = False
            for ft in intersecting_features:
                if ft.parameters.cull_stud(stud, ft):
                    skip = True
                    break
            if skip:
                continue
            slab_populator.add_element(stud)
            for intersection in pair:
                for beam in intersection["beams"]:  # multiple beams possible if corner intersection
                    params = intersection["feature_def"].parameters
                    try:
                        dr = params.get_direct_rule_from_elements(stud, beam, location=intersection["point"])
                    except:
                        dr = DirectRule(TButtJoint, [stud, beam], location=intersection["point"])
                    rules.append(dr)

    return rules



class SlabStudElementGeneratorParametersA(ElementGeneratorParameters):
    """A slab detail set that uses the default edge beams, studs, and plates."""

    BEAM_CATEGORY_NAMES = ["stud"]
    RULES = [
        CategoryRule(TButtJoint, "stud", "top_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(TButtJoint, "stud", "bottom_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(TButtJoint, "stud", "edge_stud", mill_depth=10.0, max_distance=1.0),
    ]

    def __init__(
        self,
        stud_spacing,
        standard_beam_width,
        beam_width_overrides=None,
        joint_rule_overrides=None,
    ):
        super(SlabStudElementGeneratorParametersA, self).__init__(
            standard_beam_width,
            beam_width_overrides,
            joint_rule_overrides,
        )
        self.stud_spacing = stud_spacing


    def generate_elements(self, slab_populator):
        """Populates the slab with elements and joints according to the detail set.

        Parameters
        ----------
        slab_populator : :class:`compas_timber.populators.SlabPopulator`
            The slab populator to populate.
        """
        return create_studs(self, slab_populator)

    def cull_stud(self, stud, feature_def) -> bool:
        """Cull and split the studs for door openings."""
        return False

    def cull_beam_segment(self, stud, feature_def) -> bool:
        """Cull and split the studs for door openings."""
        return False
        
    def join_elements(self, slab_populator, feature_definition=None):
        """Join the elements for WindowDetailB."""
        return join_studs(self, slab_populator, list(feature_definition.elements.values()))