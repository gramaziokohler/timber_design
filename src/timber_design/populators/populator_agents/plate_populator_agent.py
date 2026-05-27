from dataclasses import dataclass

from compas_timber.elements import Plate

from timber_design.populators.populator_agents.layer_agent import LayerAgent
from timber_design.populators.populator_agents.layer_agent import LayerAgentConfig


@dataclass
class PlatePopulatorAgentConfig(LayerAgentConfig):
    """Configuration for a single sheathing plate agent."""
    IS_ABSTRACT = False

    @property
    def __data__(self):
        data = super().__data__
        return data


class PlatePopulatorAgent(LayerAgent):
    """Generates a flat sheathing plate for one cross-section layer of a panel.

    The agent operates on a single :class:`~timber_design.populators.Layer`.
    The layer's panel already has its ``outline_a`` and ``outline_b`` set to the
    exact boundaries of that layer, so element creation is identical regardless
    of which layer is used:

    - ``"interior"`` layer: ``outline_a`` = innermost panel face,
      ``outline_b`` = inner face of the structural frame.
    - ``"exterior"`` layer: ``outline_a`` = outer face of the structural frame,
      ``outline_b`` = outermost panel face.

    The beam category is derived from the layer name as
    ``"{layer.name}_plate"`` (e.g. ``"interior_plate"`` or
    ``"exterior_plate"``).

    No :attr:`~LayerAgent.outline` is set; this agent does not participate
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
    NAME = "PlatePopulatorAgent"

    def __init__(self, layer, beam_widths=None, internal_joint_overrides=None, external_joint_overrides=None):
        # type: (Layer, Optional[dict], Optional[list], Optional[list]) -> None
        super(PlatePopulatorAgent, self).__init__(layer, beam_widths, internal_joint_overrides, external_joint_overrides)
        self.BEAM_CATEGORY_NAMES = ["{}_plate".format(layer.name)]

    def generate_elements(self) -> None:
        """Create a :class:`~compas_timber.elements.Plate` spanning this layer."""
        category = "{}_plate".format(self.layer.name)
        plate = Plate.from_outlines(
            self.layer.outline_a,
            self.layer.outline_b,
            name=category,
            category=category,
        )
        self.elements.append(plate)


# Set after both classes are defined so forward reference is resolved
PlatePopulatorAgentConfig.AGENT_TYPE = PlatePopulatorAgent
