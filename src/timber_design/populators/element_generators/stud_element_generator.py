from typing import Dict
from typing import List
from typing import Union

from compas.geometry import Line
from compas_timber.connections import TButtJoint
from compas_timber.elements import Panel

from timber_design.populators import ElementGenerator
from timber_design.workflow import CategoryRule
from timber_design.workflow import DirectRule

from .generator_functions import split_beam_with_element_generators


class PanelStudElementGeneratorA(ElementGenerator):
    """A panel detail set that uses the default edge beams, studs, and plates."""

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
        panel: Panel,
        stud_spacing: float,
        standard_beam_width: float,
        beam_width_overrides: Union[Dict, None] = None,
        joint_rule_overrides: Union[List[CategoryRule], None] = None,
    ):
        super(PanelStudElementGeneratorA, self).__init__(
            panel,
            standard_beam_width,
            beam_width_overrides,
            joint_rule_overrides,
        )
        self.stud_spacing = stud_spacing

    @property
    def panel(self) -> Panel:
        """The panel feature."""
        return self.feature

    def generate_elements(self):
        """Populates the panel with stud beams."""
        self._create_studs()

    def join_elements(self, populator_direct_rules: Union[List[DirectRule], None], element_generators: List[ElementGenerator]) -> Union[List[DirectRule], None]:
        """Join the stud beams to neighboring ElementGenerator elements."""
        intersecting_generators = [g for g in element_generators if g is not self]
        return self._join_studs(populator_direct_rules, intersecting_generators)

    def _create_studs(self):
        """Generates the stud beams."""
        x_position = self.stud_spacing
        studs = []
        while x_position < self.panel.length - self.beam_dimensions["stud"][0]:
            studs.append(self.beam_from_category(Line.from_point_and_vector((x_position, 0, 0), (0, self.panel.width, 0)), "stud"))
            x_position += self.stud_spacing
        self.elements = studs

    def _join_studs(self, populator_direct_rules: Union[List[DirectRule], None], element_generators: List[ElementGenerator]) -> List[DirectRule]:
        """Joins the stud beams."""
        intersecting_generators = element_generators
        elements = []
        min_length = self.beam_dimensions["stud"][0]
        rules = []
        for raw_stud in self.elements:
            beam_tuples, joints_to_cull = split_beam_with_element_generators(raw_stud, intersecting_generators)
            for j in joints_to_cull:
                if j in populator_direct_rules:
                    populator_direct_rules.remove(j)
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
