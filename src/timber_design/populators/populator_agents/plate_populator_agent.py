from dataclasses import dataclass

from compas_timber.elements import Plate

from timber_design.populators import PopulatorAgent
from timber_design.populators import PopulatorAgentConfig
from timber_design.populators.layer import Layer


@dataclass
class PlatePopulatorAgentConfig(PopulatorAgentConfig):
    """Configuration for a single sheathing plate agent.

    Parameters
    ----------
    thickness : float, optional
        Thickness of the sheathing layer in model units.  Informational — the
        plate geometry is fully defined by the :class:`~timber_design.populators.Layer`
        passed to :class:`PlatePopulatorAgent`.
    """

    thickness: float = 0.0

    @property
    def __data__(self):
        data = super().__data__
        data["thickness"] = self.thickness
        return data


class PlatePopulatorAgent(PopulatorAgent):
    """Generates a flat sheathing plate for one cross-section layer of a panel.

    The agent operates on a single :class:`~timber_design.populators.Layer`.
    The layer's panel already has its ``outline_a`` and ``outline_b`` set to the
    exact boundaries of that layer, so element creation is symmetric regardless
    of which layer is used:

    - ``"interior"`` layer: ``outline_a`` = innermost panel face,
      ``outline_b`` = inner face of the structural frame.
    - ``"exterior"`` layer: ``outline_a`` = outer face of the structural frame,
      ``outline_b`` = outermost panel face.

    The beam category is derived from the layer name as
    ``f"{layer.name}_plate"`` (e.g. ``"interior_plate"`` or
    ``"exterior_plate"``).

    No :attr:`~PopulatorAgent.outline` is set; this agent does not participate
    in boundary trimming.

    Parameters
    ----------
    layer : :class:`~timber_design.populators.Layer`
        The sheathing layer to generate the plate for.  Typically
        ``"interior"`` or ``"exterior"``.
    params : :class:`PlatePopulatorAgentConfig`
        Configuration carrying the sheeting thickness (informational).
    """

    BEAM_CATEGORY_NAMES = []  # set per-instance in __init__
    NAME = "PanelPlatePopulatorAgent"
    RULES = []

    def __init__(self, layer: Layer, params: PlatePopulatorAgentConfig) -> None:
        super(PlatePopulatorAgent, self).__init__(layer.panel, params)
        # Override the layer set by the base class (params.layer is None for plate agents;
        # the layer is passed explicitly as the first constructor argument instead).
        self.layer = layer
        self.thickness = params.thickness
        # Category is driven by the layer name.  Set BEAM_CATEGORY_NAMES as an
        # instance attribute so resolve_beam_dimensions registers it correctly.
        self.BEAM_CATEGORY_NAMES = ["{}_plate".format(layer.name)]

    def generate_elements(self) -> None:
        """Create a :class:`~compas_timber.elements.Plate` spanning this layer."""
        category = "{}_plate".format(self.layer.name)
        plate = Plate.from_outlines(
            self.panel.outline_a,
            self.panel.outline_b,
            name=category,
            category=category,
        )
        self.elements.append(plate)


# Set after both classes are defined so forward reference is resolved
PlatePopulatorAgentConfig.AGENT_TYPE = PlatePopulatorAgent
