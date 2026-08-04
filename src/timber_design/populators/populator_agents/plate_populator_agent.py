from __future__ import annotations

from compas_timber.elements import Plate

from timber_design.populators.populator_agents.layer_agent import LayerAgent


class PlatePopulatorAgent(LayerAgent):
    """Generates a flat sheathing plate for one cross-section layer of a panel.

    Parameters
    ----------
    layer : :class:`~compas_timber.elements.Layer` or str, optional
        The sheathing layer to generate the plate for, or its path. 
    """

    BEAM_CATEGORY_NAMES = ["plate"]
    NAME = "PlatePopulatorAgent"

    def generate_layer_elements(self):
        """Create a :class:`~compas_timber.elements.Plate` spanning this layer.

        Returns
        -------
        tuple[list[:class:`compas_timber.elements.Plate`], None]
            The plate and this agent's boundary outline — always ``None``.
        """
        category = "plate"
        plate = Plate.from_outlines(
            self.layer.outline_a,
            self.layer.outline_b,
            name=category,
            category=category,
        )
        return [plate], None
