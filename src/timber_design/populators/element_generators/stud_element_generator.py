from dataclasses import dataclass
from typing import List
from typing import Optional
from typing import Union

from compas.geometry import Line
from compas_timber.connections import TButtJoint
from compas_timber.elements import Panel

from timber_design.populators import ElementGenerator
from timber_design.populators import ElementGeneratorParams
from timber_design.workflow import CategoryRule


@dataclass
class StudElementGeneratorParams(ElementGeneratorParams):
    stud_spacing: float = 0.0

    @property
    def __data__(self):
        data = super().__data__
        data["stud_spacing"] = self.stud_spacing
        return data


class StudElementGenerator(ElementGenerator):
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
        params: StudElementGeneratorParams,
    ):
        super(StudElementGenerator, self).__init__(panel, params)
        self.stud_spacing = params.stud_spacing

    def generate_elements(self):
        """Populates the panel with stud beams."""
        self._create_studs()

    def _create_studs(self):
        """Generates the stud beams."""
        x_position = self.stud_spacing
        studs = []
        while x_position < self.panel.length - self.beam_dimensions["stud"][0]:
            studs.append(self.beam_from_category(Line.from_point_and_vector((x_position, 0, 0), (0, self.panel.width, 0)), "stud"))
            x_position += self.stud_spacing
        self.elements = studs

  
