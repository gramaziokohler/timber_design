from compas.geometry import Line
from compas_timber.connections import TButtJoint
from compas_timber.design import CategoryRule

from timber_design.element_generators import ElementGeneratorParameters
from timber_design.populators import ElementGroup

from .generator_functions import split_beam_with_element_groups

# ==========================================================================
# methods for stud beams
# ==========================================================================


def create_studs(parameters, slab_populator):
    """Generates the stud beams."""
    x_position = parameters.stud_spacing
    studs = []
    while x_position < slab_populator.obb.xmax - parameters.beam_dimensions["stud"][0]:
        studs.append(parameters.beam_from_category(Line.from_point_and_vector((x_position, 0, 0), (0, slab_populator.width, 0)), "stud"))
        x_position += parameters.stud_spacing
    return ElementGroup(slab_populator, parameters, elements=studs)


def join_studs(parameters, slab_populator, element_group):
    """Joins the stud beams."""
    intersecting_groups = slab_populator.element_groups
    elements = []
    min_length = parameters.beam_dimensions["stud"][0]
    rules = []
    for raw_stud in element_group.elements:
        beam_tuples, joints_to_cull = split_beam_with_element_groups(raw_stud, intersecting_groups)
        for j in joints_to_cull:
            if j in slab_populator.direct_rules:
                slab_populator.direct_rules.remove(j)
        for bt in beam_tuples:
            beam, (start_int, end_int) = bt
            if not beam or beam.length < min_length:
                continue
            elements.append(beam)
            for intersection in [start_int, end_int]:
                if not intersection:
                    continue
                for index in intersection.get("edge_indices", []):
                    beams = intersection["element_group"].edge_elements.get(index, [])
                    for intersecting_beam in beams:
                        rules.append(parameters.get_direct_rule_from_elements(beam, intersecting_beam))
    element_group.elements = elements
    return [rule for rule in rules if rule is not None]


class SlabStudElementGeneratorParametersA(ElementGeneratorParameters):
    """A slab detail set that uses the default edge beams, studs, and plates."""

    BEAM_CATEGORY_NAMES = ["stud"]
    NAME = "StudElementGenerator"
    RULES = [
        CategoryRule(TButtJoint, "stud", "top_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(TButtJoint, "stud", "bottom_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(TButtJoint, "stud", "edge_stud", mill_depth=10.0, max_distance=1.0),
        CategoryRule(TButtJoint, "stud", "header", mill_depth=10.0, max_distance=1.0),
        CategoryRule(TButtJoint, "stud", "sill", mill_depth=10.0, max_distance=1.0),
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

    def cull_beam_segment(self, stud, element_group) -> bool:
        """Cull and split the studs for door openings."""
        return False

    def join_elements(self, slab_populator, element_group=None):
        """Join the elements for WindowDetailB."""
        return join_studs(self, slab_populator, element_group)
