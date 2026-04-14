from dataclasses import dataclass
from typing import Optional

from compas_timber.elements import Panel
from compas_timber.elements import Plate

from timber_design.populators import PopulatorAgent
from timber_design.populators import PopulatorAgentConfig


@dataclass
class PlatePopulatorAgentConfig(PopulatorAgentConfig):
    sheeting_inside: Optional[float] = None
    sheeting_outside: Optional[float] = None

    @property
    def __data__(self):
        data = super().__data__
        data["sheeting_inside"] = self.sheeting_inside
        data["sheeting_outside"] = self.sheeting_outside
        return data


class PlatePopulatorAgent(PopulatorAgent):
    """Generates flat sheathing plates on the inner and/or outer face of a panel.

    Creates :class:`~compas_timber.elements.Plate` elements spanning from the
    outer panel outline to the frame panel outline (i.e. the sheathing layer
    thickness equals the gap between the two outlines).

    - An **inside plate** (``sheeting_inside`` > 0) is placed between the
      inner face of the full panel (``panel.outline_a``) and the inner face
      of the frame (``frame_panel.outline_a``).
    - An **outside plate** (``sheeting_outside`` > 0) is placed between the
      outer face of the full panel (``panel.outline_b``) and the outer face
      of the frame (``frame_panel.outline_b``).

    No :attr:`~PopulatorAgent.outline` is set; this agent does not
    participate in boundary trimming.

    Parameters
    ----------
    panel : :class:`compas_timber.elements.Panel`
        The full panel (including sheathing layers).
    frame_panel : :class:`compas_timber.elements.Panel`
        The structural frame panel (sheathing layers removed).
    params : :class:`PlatePopulatorAgentParams`
        Sheathing thicknesses.

    Attributes
    ----------
    sheeting_inside : float or None
        Thickness of the interior sheathing layer.
    sheeting_outside : float or None
        Thickness of the exterior sheathing layer.
    """

    BEAM_CATEGORY_NAMES = ["inside_plate", "outside_plate"]
    NAME = "PanelPlatePopulatorAgent"
    RULES = []

    def __init__(
        self,
        panel: Panel,
        frame_panel: Panel,
        params: PlatePopulatorAgentConfig,
    ) -> None:
        super(PlatePopulatorAgent, self).__init__(panel, params)
        self.frame_panel = frame_panel
        self.sheeting_inside = params.sheeting_inside
        self.sheeting_outside = params.sheeting_outside

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


# Set after both classes are defined so forward reference is resolved
PlatePopulatorAgentConfig.AGENT_TYPE = PlatePopulatorAgent
