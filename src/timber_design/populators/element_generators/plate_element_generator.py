from dataclasses import dataclass
from typing import List
from typing import Optional

from compas_timber.elements import Panel
from compas_timber.elements import Plate

from timber_design.populators import ElementGenerator
from timber_design.populators import ElementGeneratorParams
from timber_design.workflow import CategoryRule


@dataclass
class PlateElementGeneratorParams(ElementGeneratorParams):
    sheeting_inside: Optional[float] = None
    sheeting_outside: Optional[float] = None

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
        params: PlateElementGeneratorParams,
    ) -> None:
        super(PlateElementGenerator, self).__init__(panel, params)
        self.frame_panel = frame_panel
        self.sheeting_inside = params.sheeting_inside
        self.sheeting_outside = params.sheeting_outside

    @property
    def panel(self) -> Panel:
        """The panel feature."""
        return self.feature

    def generate_elements(self) -> None:
        """Populates the panel with plate elements."""
        self._create_plates()

    def _create_plates(self) -> None:
        if self.sheeting_inside:
            plate = Plate.from_outlines(self.panel.outline_a, self.frame_panel.outline_a, name="inside_plate", category="inside_plate")
            self.elements.append(plate)
        if self.sheeting_outside:
            plate = Plate.from_outlines(self.panel.outline_b, self.frame_panel.outline_b, name="outside_plate", category="outside_plate")
            self.elements.append(plate)
