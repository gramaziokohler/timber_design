from compas_timber.elements import Plate
from compas_timber.elements import Slab

from timber_design.populators import ElementGenerator
from timber_design.populators import SlabPopulator
from timber_design.workflow import DirectRule
from timber_design.workflow import CategoryRule


class SlabPlateElementGeneratorA(ElementGenerator):
    """A slab detail set that uses the default edge beams, studs, and plates."""

    BEAM_CATEGORY_NAMES = ["inside_plate", "outside_plate"]
    NAME = "SlabPlateElementGenerator"
    RULES = []

    def __init__(self, slab:Slab, frame_slab: Slab, sheeting_inside: float|None = None, sheeting_outside: float|None = None, beam_width_overrides: dict|None = None, joint_rule_overrides: list[CategoryRule]|None = None) -> None:
        super(SlabPlateElementGeneratorA, self).__init__(
            slab,
            standard_beam_width=0.0,
            beam_width_overrides=beam_width_overrides,
            joint_rule_overrides=joint_rule_overrides,
            )
        self.frame_slab = frame_slab
        self.sheeting_inside = sheeting_inside
        self.sheeting_outside = sheeting_outside

    @property
    def slab(self) -> Slab:
        """The slab feature."""
        return self.feature

    def generate_elements(self) -> None:
        """Populates the slab with elements and joints according to the detail set.

        Parameters
        ----------
        slab_populator : :class:`compas_timber.populators.SlabPopulator`
            The slab populator to populate.
        """
        self._create_plates()

    def join_elements(self, slab_populator: SlabPopulator) -> list[DirectRule]:
        """Join the elements for WindowDetailB."""
        intersecting_generators = [g for g in slab_populator.element_generators if g is not self]
        slab_populator.test.extend([e.modelgeometry for e in self.elements])
        for plate in self.elements:
            for intersecting_generator in intersecting_generators:
                intersecting_generator.apply_to_plate(plate, intersecting_generator)
        return []

    def _create_plates(self) -> None:
        if self.sheeting_inside:
            plate = Plate.from_outlines(self.slab.outline_a, self.frame_slab.outline_a, name="inside_plate")
            self.elements.append(plate)
        if self.sheeting_outside:
            plate = Plate.from_outlines(self.slab.outline_b, self.slab.outline_b, name="outside_plate")
            self.elements.append(plate)
