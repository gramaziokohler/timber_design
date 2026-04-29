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
    agent_configs : list[:class:`~timber_design.populators.LayerAgentConfig`], optional
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
            thickness=None,  # fill remaining
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
            raise ValueError("Layer {!r} cannot have both agent_configs and sublayers.".format(name))

        self.thickness = thickness
        self.sublayers = sublayers or []
        self.name = name
        self.agent_configs = agent_configs or []
        self.is_framing_layer = is_framing_layer

    def get_leaf_layer_defs(self):
        """Yield leaf-level :class:`LayerDefinition` objects (depth-first).
        """
        self._resolve_thicknesses()
        for ld in self.sublayers:
            if ld.sublayers:
                yield from self._flat_layer_defs(ld)
            else:
                yield ld


    def _resolve_thicknesses(self):
        """Resolve all ``thickness=None`` entries in the :class:`LayerDefinition` tree.

        .. warning::
            This method **mutates** ``layer_def`` and its descendants in place.
            Always pass a deep copy of the user-supplied definitions — never
            the originals — so that the config object can be reused across
            multiple :meth:`create_layers` calls.

        Uses a two-pass algorithm so that thicknesses can flow both directions:

        **Pass 1 — bottom-up** (:meth:`_infer_from_children`):
            Post-order traversal.  When a node's own thickness is ``None`` but
            every one of its children already has a concrete thickness, the
            node's thickness is set to the sum of its children.  This allows
            composite sub-stacks to omit a total, e.g.
            ``insulation(sublayers=[board_a(30), board_b(20)])`` resolves to
            ``insulation.thickness = 50``.

        **Pass 2 — top-down** (:meth:`_distribute_to_children`):
            Pre-order traversal.  When a node has a known thickness and
            exactly one child with ``thickness=None``, that child receives
            the remainder (``parent − sum(concrete siblings)``).  Fully-
            concrete sibling groups are validated to sum to the parent.

        Raises
        ------
        ValueError
            See :meth:`_infer_from_children` and :meth:`_distribute_to_children`.
        """
        self._infer_from_children(self)
        self._distribute_to_children(self)

    def _infer_from_children(self, layer_def):
        """Post-order pass: infer a node's thickness from its children.

        Recurses into every child first, then — if the current node's
        thickness is still ``None`` and all children are now concrete —
        sets ``node.thickness = sum(children)``.  Nodes whose thickness
        is already set, or that have at least one fill-remaining child
        after recursion, are left for the top-down pass.

        Parameters
        ----------
        layer_def : :class:`~timber_design.populators.LayerDefinition`
        """
        for sl in layer_def.sublayers:
            self._infer_from_children(sl)

        if layer_def.thickness is None and layer_def.sublayers:
            if all(sl.thickness is not None for sl in layer_def.sublayers):
                layer_def.thickness = sum(sl.thickness for sl in layer_def.sublayers)

    def _distribute_to_children(self, layer_def):
        """Pre-order pass: distribute a known parent thickness to fill children.

        Rules applied at each node that has sublayers:

        - **Parent thickness still** ``None``: raises — the bottom-up pass
          could not infer it (some children remain unresolved).
        - **All children concrete**: validates ``sum(children) == parent``.
        - **Exactly one fill child**: assigns it
          ``parent − sum(concrete siblings)``; raises if that remainder is
          negative.
        - **More than one fill child**: raises — at most one ``thickness=None``
          per sibling group is permitted.

        Recurses into all children after resolving the current level.

        Parameters
        ----------
        layer_def : :class:`~timber_design.populators.LayerDefinition`

        Raises
        ------
        ValueError
            On any of the error conditions described above.
        """
        if not layer_def.sublayers:
            return

        fill = [sl for sl in layer_def.sublayers if sl.thickness is None]
        known_sum = sum(sl.thickness for sl in layer_def.sublayers if sl.thickness is not None)

        if layer_def.thickness is None:
            fill_names = [repr(sl.name) for sl in fill]
            raise ValueError("Cannot resolve fill-remaining sublayer(s) [{}] of layer {!r} because its own thickness is unknown.".format(", ".join(fill_names), layer_def.name))

        if not fill:
            if not TOL.is_close(known_sum, layer_def.thickness):
                breakdown = ", ".join("{!r}={}".format(sl.name, sl.thickness) for sl in layer_def.sublayers)
                raise ValueError("Sublayers of layer {!r} sum to {} but layer thickness is {}. Sublayers: [{}].".format(layer_def.name, known_sum, layer_def.thickness, breakdown))
        else:
            if len(fill) > 1:
                fill_names = [repr(sl.name) for sl in fill]
                raise ValueError("At most one sublayer of layer {!r} may have thickness=None; got {} ({}).".format(layer_def.name, len(fill), ", ".join(fill_names)))
            remaining = layer_def.thickness - known_sum
            if remaining < 0 and not TOL.is_zero(remaining):
                breakdown = ", ".join("{!r}={}".format(sl.name, sl.thickness) for sl in layer_def.sublayers if sl.thickness is not None)
                raise ValueError(
                    "Fixed sublayers of layer {!r} ({}) exceed its thickness ({}); no room left for fill-remaining sublayer {!r}. Fixed sublayers: [{}].".format(
                        layer_def.name, known_sum, layer_def.thickness, fill[0].name, breakdown
                    )
                )
            fill[0].thickness = remaining

        for sl in layer_def.sublayers:
            self._distribute_to_children(sl)


class Layer:
    """A resolved cross-section layer within a panel, carrying geometry and agents.

    Each ``Layer`` is created by
    :meth:`~timber_design.populators.PanelPopulatorConfig.create_layers` from
    a :class:`LayerDefinition`.  It holds a :class:`~compas_timber.elements.Panel`
    whose ``outline_a`` and ``outline_b`` define the exact geometric boundaries
    of that layer in populator space.

    All :class:`~timber_design.populators.LayerAgent` subclasses receive a
    ``Layer`` as their first constructor argument.  They access the underlying
    panel geometry via the
    :attr:`~timber_design.populators.LayerAgent.panel` property, which
    always returns ``self.layer.panel``.

    Parameters
    ----------
    panel : :class:`compas_timber.elements.Panel`
        The panel geometry for this layer.  Its ``outline_a`` / ``outline_b``
        span exactly the Z-extent of the layer in populator space.
    name : str, optional
        The layer identifier (e.g. ``"frame"``, ``"interior"``).
    agents : list[:class:`~timber_design.populators.LayerAgent`], optional
        Agent instances created for this layer.  Populated after construction.
    layer_def : :class:`LayerDefinition`, optional
        The definition object that produced this layer.  Used to read
        :attr:`~LayerDefinition.agent_configs` and
        :attr:`~LayerDefinition.is_framing_layer`.
    layer_index : int, optional
        Zero-based ordinal position of this layer in the flat layer stack.
    is_framing_layer : bool, optional
        Directly mark this layer as a framing layer.  Takes precedence over
        the value read from ``layer_def.is_framing_layer`` when ``True``.
        Useful when creating layers without a :class:`LayerDefinition`.

    Attributes
    ----------
    panel : :class:`compas_timber.elements.Panel`
        The panel geometry for this layer.
    name : str or None
        The layer identifier.
    agents : list[:class:`~timber_design.populators.LayerAgent`]
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
        ``True`` when this layer carries structural framing agents.
        Reads from ``layer_def.is_framing_layer`` when present; falls back to
        the constructor argument (default ``False``).
    """

    def __init__(
        self,
        panel: Optional[Panel] = None,
        name: Optional[str] = None,
        agents: Optional[list] = None,
        layer_index: Optional[int] = None,
        is_framing_layer: bool = False,
    ):
        self.panel = panel
        self.name = name
        self.agents = agents if agents is not None else []
        self.layer_index = layer_index
        self.is_framing_layer = is_framing_layer

    @property
    def elements(self):
        """All elements placed on this layer, across every registered agent.

        Uses :meth:`~timber_design.populators.LayerAgent.elements_for_layer`
        on every agent so the result is always up-to-date after trimming
        (both :class:`~timber_design.populators.LayerAgent` and
        :class:`~timber_design.populators.FeatureAgent` implement the same
        method).
        """
        result = []
        for agent in self.agents:
            result.extend(agent.elements_for_layer(self))
        return result

    @classmethod
    def from_panel_and_range(
        cls,
        panel: Panel,
        range_a: float,
        range_b: float,
        name: Optional[str] = None,
        layer_index: Optional[int] = None,
        is_framing_layer: bool = False,
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
        layer_index : int, optional
            Zero-based ordinal index in the layer stack.
        is_framing_layer : bool, optional
            When ``True``, marks this layer as a structural framing layer.
            Takes precedence over ``layer_def.is_framing_layer``.

        Returns
        -------
        :class:`Layer`
        """
        if range_a:
            offset = range_a / panel.thickness
            frame_outline_a = Polyline([pt_a * (1.0 - offset) + pt_b * offset for pt_a, pt_b in zip(panel.outline_a.points, panel.outline_b.points)])
        else:
            frame_outline_a = panel.outline_a

        offset = range_b / panel.thickness
        frame_outline_b = Polyline([pt_a * (1.0 - offset) + pt_b * offset for pt_a, pt_b in zip(panel.outline_a.points, panel.outline_b.points)])

        layer_panel = Panel.from_outlines(frame_outline_a, frame_outline_b)
        return cls(layer_panel, name, layer_index=layer_index, is_framing_layer=is_framing_layer)

    @property
    def thickness(self) -> float:
        """Thickness of this layer's panel."""
        return self.panel.thickness

    @property
    def center_height(self) -> float:
        """Z coordinate of the layer's mid-thickness in populator space."""
        return self.panel.outline_a[0][2] + self.panel.thickness / 2
