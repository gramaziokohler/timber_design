from timber_design.element_generators import SlabElementGeneratorParameters
from timber_design.element_generators.element_generator_parameters import ElementGeneratorParameters
from timber_design.populators import ElementGroup
from compas_timber.elements import Plate


def create_plates(parameters, slab_populator):
    elements = []
    if parameters.sheeting_inside:
        plate = Plate.from_outlines(slab_populator.outline_a, slab_populator.frame_outline_a)
        elements.append(plate)
    if parameters.sheeting_outside:
        plate = Plate.from_outlines(slab_populator.outline_b, slab_populator.frame_outline_b)
        elements.append(plate)
    return ElementGroup(slab_populator, parameters, elements=elements)


def apply_plate_cuts(element_group, intersecting_groups):
    for plate in element_group.elements:
        for element_group in intersecting_groups:
            element_group.parameters.apply_to_plate(plate, element_group)


class SlabPlateElementGeneratorParametersA(ElementGeneratorParameters):
    """A slab detail set that uses the default edge beams, studs, and plates."""

    BEAM_CATEGORY_NAMES = ["inside_plate", "outside_plate"]
    NAME = "SlabPlateElementGenerator"
    RULES = []

    def __init__(self, sheeting_inside=None, sheeting_outside=None, beam_width_overrides=None, joint_rule_overrides=None):
        super(SlabPlateElementGeneratorParametersA, self).__init__(
            beam_width_overrides=beam_width_overrides,
            joint_rule_overrides=joint_rule_overrides,
        )
        self.sheeting_inside = sheeting_inside
        self.sheeting_outside = sheeting_outside

    def generate_elements(self, slab_populator):
        """Populates the slab with elements and joints according to the detail set.

        Parameters
        ----------
        slab_populator : :class:`compas_timber.populators.SlabPopulator`
            The slab populator to populate.
        """
        return create_plates(self, slab_populator)

    def join_elements(self, slab_populator, element_group=None):
        """Join the elements for WindowDetailB."""
        intersecting_groups = slab_populator.element_groups
        apply_plate_cuts(element_group, intersecting_groups)
        return []
