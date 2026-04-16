from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Optional

from compas.geometry import Polyline
from compas.tolerance import TOL
from compas_timber.elements import Panel

if TYPE_CHECKING:
    pass


class LayerDefinition:
    """Definition of a layer within a panel.

    Parameters
    ----------
    thickness : float, optional
        Thickness of this layer.  Pass ``None`` to use fill-remaining logic:
        the layer will receive the panel thickness that remains after all
        fixed-thickness siblings have been allocated.
    name : str, optional
        Layer identifier string (e.g. ``"frame"``, ``"interior"``).
    agent_configs : list, optional
        :class:`~timber_design.populators.PopulatorAgentConfig` instances that
        will be instantiated when this layer is created.  Mutually exclusive
        with ``sublayers``.
    sublayers : list[LayerDefinition], optional
        Nested child layer definitions for composite layers (e.g. multiple
        insulation sheets).  Mutually exclusive with ``agent_configs``.
    is_framing_layer : bool, optional
        When ``True``, default feature agents and generic panel agents are
        applied to this layer.  Defaults to ``False``.
    """

    def __init__(
        self,
        thickness: Optional[float] = None,
        name: Optional[str] = None,
        agent_configs: Optional[list] = None,
        sublayers: Optional[list] = None,
        is_framing_layer: bool = False,
    ):
        if agent_configs and sublayers:
            raise ValueError(
                "A layer cannot have both agent_configs and sublayers. "
                "Agents should be placed on the leaf sublayers."
            )
        if thickness is not None and sublayers:
            known = [sl.thickness for sl in sublayers if sl.thickness is not None]
            if len(known) == len(sublayers) and not TOL.is_close(sum(known), thickness):
                raise ValueError(
                    "Total sublayer thickness ({}) must equal layer thickness ({}).".format(
                        sum(known), thickness
                    )
                )
        self.thickness = thickness
        self.name = name
        self.agent_configs = agent_configs or []
        self.sublayers = sublayers or []
        self.is_framing_layer = is_framing_layer


class Layer:
    """A named cross-section layer within a panel.

    Each ``Layer`` carries its own :class:`~compas_timber.elements.Panel` whose
    ``outline_a`` and ``outline_b`` define the exact geometric boundaries of
    that layer in populator space.

    The four standard layer names produced by
    :func:`~timber_design.populators.get_layers` are:

    ``"local"``
        The full panel in populator space (including all sheeting).
    ``"frame"``
        The structural frame panel — the full panel trimmed by
        ``sheeting_inside`` / ``sheeting_outside`` on each side.
    ``"interior"``
        The inside sheathing layer (only present when ``sheeting_inside > 0``).
    ``"exterior"``
        The outside sheathing layer (only present when ``sheeting_outside > 0``).

    Parameters
    ----------
    panel : :class:`compas_timber.elements.Panel`
        The panel geometry for this layer.
    name : str, optional
        The layer identifier.
    agents : list, optional
        Agent instances created for this layer.
    layer_def : :class:`LayerDefinition`, optional
        The definition object that produced this layer.
    layer_index : int, optional
        Position of this layer in the overall layer stack.

    Attributes
    ----------
    thickness : float
        Convenience shortcut to ``layer.panel.thickness``.
    is_framing_layer : bool
        Delegated to ``layer_def.is_framing_layer`` when present,
        otherwise ``False``.
    """

    def __init__(
        self,
        panel: Optional[Panel] = None,
        name: Optional[str] = None,
        agents: Optional[list] = None,
        layer_def: Optional[LayerDefinition] = None,
        layer_index: Optional[int] = None,
    ):
        self.panel = panel
        self.name = name
        self.agents = agents if agents is not None else []
        self.layer_def = layer_def
        self.layer_index = layer_index

    @classmethod
    def from_panel_and_range(
        cls,
        panel: Panel,
        range_a: float,
        range_b: float,
        name: Optional[str] = None,
        layer_def: Optional[LayerDefinition] = None,
        layer_index: Optional[int] = None,
    ) -> "Layer":
        """Create a layer by trimming a panel to a given range along its local Z axis.

        Parameters
        ----------
        panel : :class:`compas_timber.elements.Panel`
            The source panel to trim.
        range_a : float
            Start of the layer range (distance from the ``outline_a`` face).
        range_b : float
            End of the layer range (distance from the ``outline_a`` face).
        name : str, optional
            Name for this layer.
        layer_def : :class:`LayerDefinition`, optional
            The definition that produced this layer.
        layer_index : int, optional
            Ordinal index in the layer stack.

        Returns
        -------
        :class:`Layer`
        """
        if range_a:
            offset = range_a / panel.thickness
            frame_outline_a = Polyline(
                [pt_a * (1.0 - offset) + pt_b * offset for pt_a, pt_b in zip(panel.outline_a.points, panel.outline_b.points)]
            )
        else:
            frame_outline_a = panel.outline_a

        offset = range_b / panel.thickness
        frame_outline_b = Polyline(
            [pt_a * (1.0 - offset) + pt_b * offset for pt_a, pt_b in zip(panel.outline_a.points, panel.outline_b.points)]
        )

        layer_panel = Panel.from_outlines(frame_outline_a, frame_outline_b)
        return cls(layer_panel, name, layer_def=layer_def, layer_index=layer_index)

    @property
    def thickness(self) -> float:
        """Thickness of this layer's panel."""
        return self.panel.thickness

    @property
    def center_height(self) -> float:
        """Z coordinate of the layer's mid-thickness in populator space."""
        return self.panel.outline_a[0][2] + self.panel.thickness / 2

    @property
    def is_framing_layer(self) -> bool:
        """Whether this layer is a framing layer (from its :class:`LayerDefinition`)."""
        if self.layer_def is not None:
            return self.layer_def.is_framing_layer
        return False
