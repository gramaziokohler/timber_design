from __future__ import annotations

from compas_timber.elements import Plate

from timber_design.populators.populator_agents.layer_agent import LayerAgent


class PlatePopulatorAgent(LayerAgent):
    """Generates a flat sheathing plate for one cross-section layer of a panel.

    The agent operates on a single :class:`~compas_timber.elements.Layer`.
    The layer already has its ``outline_a`` and ``outline_b`` set to the
    exact boundaries of that layer, so element creation is identical regardless
    of which layer is used:

    - ``"interior"`` layer: ``outline_a`` = innermost panel face,
      ``outline_b`` = inner face of the structural frame.
    - ``"exterior"`` layer: ``outline_a`` = outer face of the structural frame,
      ``outline_b`` = outermost panel face.

    No boundary outline is set, so this agent never trims its peers.  Its own
    plate is cut by the agents that do — an opening cuts its contour into the
    plate through :meth:`~OpeningPopulatorAgent.trim_plate`.

    Parameters
    ----------
    layer : :class:`~compas_timber.elements.Layer` or str, optional
        The sheathing layer to generate the plate for, or its path.  Typically
        ``"interior"`` or ``"exterior"``.
    internal_joint_overrides, external_joint_overrides : list, optional
        Per-agent joint-rule overrides, see :class:`PopulatorAgent`.
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
