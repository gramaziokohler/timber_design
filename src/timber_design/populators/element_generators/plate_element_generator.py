from typing import Optional

from compas_timber.elements import Panel
from compas_timber.elements import Plate

from timber_design.populators import ElementGenerator
from timber_design.populators import ElementGeneratorParams
from timber_design.workflow import CategoryRule
from timber_design.workflow import DirectRule


class PlateElementGeneratorParams(ElementGeneratorParams):
    def __init__(
        self,
        sheeting_inside: Optional[float] = None,
        sheeting_outside: Optional[float] = None,
        beam_width_overrides: Optional[dict] = None,
        joint_rule_overrides: Optional[list[CategoryRule]] = None,
    ):
        super(PlateElementGeneratorParams, self).__init__(beam_width_overrides, joint_rule_overrides)
        self.sheeting_inside = sheeting_inside
        self.sheeting_outside = sheeting_outside

    @property
    def __data__(self):
        data = super().__data__
        data["sheeting_inside"] = self.sheeting_inside
        data["sheeting_outside"] = self.sheeting_outside
        return data


class PlateElementGenerator(ElementGenerator):
    """A panel detail set that uses the default edge beams, studs, and plates."""

    BEAM_CATEGORY_NAMES = ["inside_plate", "outside_plate"]
    NAME = "PanelPlateElementGenerator"
    RULES = []

    def __init__(
        self,
        panel: Panel,
        frame_panel: Panel,
        sheeting_inside: Optional[float] = None,
        sheeting_outside: Optional[float] = None,
        beam_width_overrides: Optional[dict] = None,
        joint_rule_overrides: Optional[list[CategoryRule]] = None,
    ) -> None:
        super(PlateElementGenerator, self).__init__(
            panel,
            standard_beam_width=0.0,
            beam_width_overrides=beam_width_overrides,
            joint_rule_overrides=joint_rule_overrides,
        )
        self.frame_panel = frame_panel
        self.sheeting_inside = sheeting_inside
        self.sheeting_outside = sheeting_outside

    @property
    def panel(self) -> Panel:
        """The panel feature."""
        return self.feature

    def generate_elements(self) -> None:
        """Populates the panel with plate elements."""
        self._create_plates()

    def join_elements(self, populator_joint_defs: list[DirectRule], element_generators: list[ElementGenerator]) -> list[DirectRule]:
        """Join the elements for WindowDetailB."""
        intersecting_generators = [g for g in element_generators if g is not self]
        for plate in self.elements:
            for intersecting_generator in intersecting_generators:
                intersecting_generator.apply_to_plate(plate)
        return []

    def _create_plates(self) -> None:
        if self.sheeting_inside:
            plate = Plate.from_outlines(self.panel.outline_a, self.frame_panel.outline_a, name="inside_plate")
            self.elements.append(plate)
            print("plate xform", plate.transformation)
            self.test.append(plate.modelgeometry)
        if self.sheeting_outside:
            plate = Plate.from_outlines(self.panel.outline_b, self.frame_panel.outline_b, name="outside_plate")
            print("plate xform", plate.transformation)
            self.elements.append(plate)
            self.test.append(plate.modelgeometry)
