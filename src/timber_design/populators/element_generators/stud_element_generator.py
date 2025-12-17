from compas.geometry import Line
from compas_timber.connections import TButtJoint
from compas_timber.elements import Beam
from compas_timber.elements import Slab

from timber_design.populators import ElementGenerator
from timber_design.workflow import CategoryRule

from .generator_functions import split_beam_with_element_generators



class SlabStudElementGeneratorA(ElementGenerator):
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
        slab: Slab,
        stud_spacing:float,
        standard_beam_width:float,
        beam_width_overrides:dict|None=None,
        joint_rule_overrides:list[CategoryRule]|None=None,
    ):
        super(SlabStudElementGeneratorA, self).__init__(
            slab,
            standard_beam_width,
            beam_width_overrides,
            joint_rule_overrides,
        )
        self.stud_spacing = stud_spacing

    @property
    def slab(self) -> Slab:
        """The slab feature."""
        return self.feature

    def generate_elements(self, slab: Slab):
        """Populates the slab with elements and joints according to the detail set.

        Parameters
        ----------
        slab_populator : :class:`compas_timber.populators.SlabPopulator`
            The slab populator to populate.
        """
        self._create_studs(slab)

    def cull_beam_segment(self, beam: Beam) -> bool:
        """Cull and split the studs for door openings."""
        return False

    def join_elements(self, slab_populator):
        """Join the elements for WindowDetailB."""
        self._join_studs(slab_populator)

    def _create_studs(self, slab: Slab):
        """Generates the stud beams."""
        x_position = self.stud_spacing
        studs = []
        while x_position < slab.length - self.beam_dimensions["stud"][0]:
            studs.append(self.beam_from_category(Line.from_point_and_vector((x_position, 0, 0), (0, slab.width, 0)), "stud"))
            x_position += self.stud_spacing
        self.elements = studs

    def _join_studs(self, slab_populator):
        """Joins the stud beams."""
        intersecting_generators = slab_populator.element_generators
        elements = []
        min_length = self.beam_dimensions["stud"][0]
        rules = []
        for raw_stud in self.elements:
            beam_tuples, joints_to_cull = split_beam_with_element_generators(raw_stud, intersecting_generators)
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
                        beams = intersection["element_generator"].edge_elements.get(index, [])
                        for intersecting_beam in beams:
                            rules.append(self.get_direct_rule_from_elements(beam, intersecting_beam))
        self.elements = elements
        return [rule for rule in rules if rule is not None]
