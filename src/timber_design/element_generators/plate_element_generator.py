from compas_timber.elements import Plate

from timber_design.element_generators import ElementGenerator
from timber_design.populators import ElementGroup


def create_plates(parameters, slab_populator):
    # type: (ElementGeneratorParameters, SlabPopulator) -> ElementGroup
    elements = []
    if parameters.sheeting_inside:
        plate = Plate.from_outlines(slab_populator.outline_a, slab_populator.frame_outline_a, name="inside_plate")
        elements.append(plate)
    if parameters.sheeting_outside:
        plate = Plate.from_outlines(slab_populator.outline_b, slab_populator.frame_outline_b, name="outside_plate")
        elements.append(plate)
    return ElementGroup(slab_populator, parameters, elements=elements)


class SlabPlateElementGeneratorA(ElementGenerator):
    """A slab detail set that uses the default edge beams, studs, and plates."""

    BEAM_CATEGORY_NAMES = ["inside_plate", "outside_plate"]
    NAME = "SlabPlateElementGenerator"
    RULES = []

    def __init__(self, sheeting_inside=None, sheeting_outside=None, beam_width_overrides=None, joint_rule_overrides=None):
        # type: (float | None, Float | None, dict | None, list[CategoryRule] | None) -> None
        super(SlabPlateElementGeneratorA, self).__init__(
            beam_width_overrides=beam_width_overrides,
            joint_rule_overrides=joint_rule_overrides,
        )
        self.sheeting_inside = sheeting_inside
        self.sheeting_outside = sheeting_outside

    def generate_elements(self, slab_populator):
        # type: (SlabPopulator) -> ElementGroup
        """Populates the slab with elements and joints according to the detail set.

        Parameters
        ----------
        slab_populator : :class:`compas_timber.populators.SlabPopulator`
            The slab populator to populate.
        """
        return create_plates(self, slab_populator)

    def join_elements(self, slab_populator, element_group=None):
        # type: (SlabPopulator, ElementGroup | None) -> list[DirectRule]
        """Join the elements for WindowDetailB."""
        intersecting_groups = [g for g in slab_populator.element_groups if g is not element_group]
        slab_populator.test.extend([e.modelgeometry for e in element_group.elements])

        for plate in element_group.elements:
            for intersecting_group in intersecting_groups:
                intersecting_group.parameters.apply_to_plate(plate, intersecting_group)
        return []
