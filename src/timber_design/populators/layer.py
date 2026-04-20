from __future__ import annotations

from typing import Optional

from compas.geometry import Polyline
from compas.tolerance import TOL
from compas_timber.elements import Panel


class LayerDefinition:
    """Declarative description of one cross-section layer within a panel.

    A ``LayerDefinition`` is a *blueprint* — it does not carry any geometry.
    Geometry is only created when
    :meth:`~timber_design.populators.PanelPopulatorConfig.create_layers`
    resolves the full layer stack and instantiates :class:`Layer` objects from
    these definitions.

    Parameters
    ----------
    thickness : float, optional
        Thickness of this layer in model units.  Pass ``None`` to use
        fill-remaining logic: the layer receives whatever panel thickness is
        left after all fixed-thickness siblings have been allocated.  At most
        one sibling per parent may have ``thickness=None``.
    name : str, optional
        Human-readable layer identifier (e.g. ``"frame"``, ``"interior"``).
        Used as the layer key in the dict returned by
        :meth:`~timber_design.populators.PanelPopulatorConfig.create_layers`
        and as a prefix for plate categories (e.g. ``"interior_plate"``).
    agent_configs : list[:class:`~timber_design.populators.PopulatorAgentConfig`], optional
        Configuration objects for the agents that should be instantiated on
        this layer.  Mutually exclusive with ``sublayers``.
    sublayers : list[:class:`LayerDefinition`], optional
        Nested child layer definitions for composite layers (e.g. multiple
        insulation sheets that share a parent thickness).  Mutually exclusive
        with ``agent_configs``.
    is_framing_layer : bool, optional
        When ``True``, the default feature agents (from
        :attr:`~timber_design.populators.PanelPopulatorConfig.default_feature_configs`)
        and instance feature agents are applied to this layer.  Defaults to
        ``False``.

    Raises
    ------
    ValueError
        If both ``agent_configs`` and ``sublayers`` are provided.
    ValueError
        If ``thickness`` is given *and* all sublayer thicknesses are known but
        their sum does not equal ``thickness``.

    Examples
    --------
    A structural frame layer with an edge agent and a stud agent::

        from timber_design.populators import LayerDefinition
        from timber_design.populators import EdgePopulatorAgentConfig, StudPopulatorAgentConfig

        frame = LayerDefinition(
            thickness=None,          # fill remaining
            name="frame",
            is_framing_layer=True,
            agent_configs=[
                EdgePopulatorAgentConfig(),
                StudPopulatorAgentConfig(stud_spacing=625.0),
            ],
        )
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

        self.thickness = thickness
        self.name = name
        self.agent_configs = agent_configs or []
        self.sublayers = sublayers or []
        self.is_framing_layer = is_framing_layer
        self.parse_thickness()

    def parse_thickness(self) -> Optional[float]:
        """Calculate the thickness of this layer based on its own thickness and its sublayers."""

        if self.sublayers and all([sl.thickness for sl in self.sublayers]):
            if self.thickness:
               if not TOL.is_close(sum([sl.thickness for sl in self.sublayers]), self.thickness):
                    raise ValueError(
                        "Total sublayer thickness ({}) must equal layer thickness ({}).".format(
                            sum([sl.thickness for sl in self.sublayers]), self.thickness
                        )
                    )
            else:
                self.thickness = sum([sl.thickness for sl in self.sublayers])

        if self.thickness is not None and self.sublayers:
            known = [sl.thickness for sl in self.sublayers if sl.thickness is not None]
            if len(known) != len(self.sublayers)-1:
                raise ValueError(
                    "If layer thickness is given, all but one sublayer must have known thickness. "
                    "Known sublayer thicknesses: {}".format(known)
                )   
            else:
                remaining = self.thickness - sum(known)
                for sl in self.sublayers:
                    if sl.thickness is None:
                        sl.thickness = remaining
                        break
                        
class Layer:
    """A resolved cross-section layer within a panel, carrying geometry and agents.

    Each ``Layer`` is created by
    :meth:`~timber_design.populators.PanelPopulatorConfig.create_layers` from
    a :class:`LayerDefinition`.  It holds a :class:`~compas_timber.elements.Panel`
    whose ``outline_a`` and ``outline_b`` define the exact geometric boundaries
    of that layer in populator space.

    All :class:`~timber_design.populators.PopulatorAgent` subclasses receive a
    ``Layer`` as their first constructor argument.  They access the underlying
    panel geometry via the
    :attr:`~timber_design.populators.PopulatorAgent.panel` property, which
    always returns ``self.layer.panel``.

    Parameters
    ----------
    panel : :class:`compas_timber.elements.Panel`
        The panel geometry for this layer.  Its ``outline_a`` / ``outline_b``
        span exactly the Z-extent of the layer in populator space.
    name : str, optional
        The layer identifier (e.g. ``"frame"``, ``"interior"``).
    agents : list[:class:`~timber_design.populators.PopulatorAgent`], optional
        Agent instances created for this layer.  Populated after construction.
    layer_def : :class:`LayerDefinition`, optional
        The definition object that produced this layer.  Used to read
        :attr:`~LayerDefinition.agent_configs` and
        :attr:`~LayerDefinition.is_framing_layer`.
    layer_index : int, optional
        Zero-based ordinal position of this layer in the flat layer stack.
        Used by agents for cross-layer trimming decisions via
        :meth:`~timber_design.populators.PopulatorAgent.affects_layer`.
        ``None`` for the ``"local"`` pseudo-layer that spans the entire panel.

    Attributes
    ----------
    panel : :class:`compas_timber.elements.Panel`
        The panel geometry for this layer.
    name : str or None
        The layer identifier.
    agents : list[:class:`~timber_design.populators.PopulatorAgent`]
        Agent instances on this layer.
    layer_def : :class:`LayerDefinition` or None
        The definition that produced this layer.
    layer_index : int or None
        Zero-based position in the layer stack.
    thickness : float
        Convenience shortcut to ``layer.panel.thickness``.
    center_height : float
        Z coordinate of the layer's mid-thickness in populator space.
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
        """Create a layer by trimming a panel to a given Z range.

        Interpolates ``outline_a`` and ``outline_b`` between the source
        panel's faces at the specified offsets so that the resulting layer
        panel spans exactly ``[range_a, range_b]`` along the panel's local
        Z axis.

        Parameters
        ----------
        panel : :class:`compas_timber.elements.Panel`
            The source panel to trim.
        range_a : float
            Start of the layer in model units, measured from ``outline_a``
            (the ``0`` face).
        range_b : float
            End of the layer in model units, measured from ``outline_a``.
        name : str, optional
            Name for this layer.
        layer_def : :class:`LayerDefinition`, optional
            The definition that produced this layer.
        layer_index : int, optional
            Zero-based ordinal index in the layer stack.

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
