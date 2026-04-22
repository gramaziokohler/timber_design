from __future__ import annotations

import copy
import dataclasses
from typing import TYPE_CHECKING

from compas.geometry import Box
from compas.geometry import Frame
from compas.geometry import Point
from compas.geometry import Polyline
from compas.geometry import Transformation
from compas.geometry import Translation
from compas.geometry import Vector
from compas.geometry import cross_vectors
from compas.tolerance import TOL
from compas_timber.elements import Panel

from timber_design.populators.layer import Layer
from timber_design.populators.layer import LayerDefinition
from timber_design.populators.populator import PanelPopulator

if TYPE_CHECKING:
    pass

# =============================================================================
# PanelPopulatorConfig
# =============================================================================


class PanelPopulatorConfig:
    """Orchestrates the construction of a :class:`~timber_design.populators.PanelPopulator`.

    Can be used directly (by supplying ``layer_defs`` and ``default_feature_configs``)
    or subclassed for specific framing systems (stud walls, recess panels, …).

    Parameters
    ----------
    panel : :class:`compas_timber.elements.Panel`, optional
        The panel to populate.  Required for :meth:`create_populator`.
    layer_defs : list[:class:`~timber_design.populators.LayerDefinition`], optional
        Ordered list of layer definitions that describe the panel cross-section
        from ``outline_a`` to ``outline_b``.  Each definition may contain
        nested ``sublayers``.  A definition with ``thickness=None`` will receive
        the remaining panel thickness after all fixed-thickness siblings are
        allocated.
    default_feature_configs : dict, optional
        Mapping from panel-feature *class* to a
        :class:`~timber_design.populators.LayerAgentConfig` (without
        ``feature`` set).  Applied to every framing layer via MRO-based
        lookup.
    instance_feature_configs : list[:class:`~timber_design.populators.FeaturePopulatorAgentConfig`], optional
        Per-instance feature overrides.  Each entry is a
        :class:`~timber_design.populators.FeaturePopulatorAgentConfig` with
        its ``feature`` attribute set to the specific feature instance.
        These take precedence over ``default_feature_configs`` for that feature.
    """

    def __init__(
        self,
        panel=None,
        orientation=None,
        standard_beam_width=None,
        layer_defs=None,
        default_feature_configs=None,
        instance_feature_configs=None,
    ):
        self.panel = panel
        self.layer_defs = layer_defs or []
        self.default_feature_configs = default_feature_configs or {}
        self.instance_feature_configs = instance_feature_configs or []
        self.orientation = orientation
        self.standard_beam_width = standard_beam_width


        # Set by _prepare_panels / create_populator
        self.transformation_to_populator = None
        # Set by alternate constructors that need a custom agent-creation strategy
        self._agents_factory = None

    # ------------------------------------------------------------------
    # Public pipeline methods
    # ------------------------------------------------------------------

    def get_populator_panel(self):
        """Transform *panel* to populator space and build the layer dict.

        Returns
        -------
        class:`compas_timber.elements.Panel`
        """
        orientation = self._get_projected_orientation()
        self.transformation_to_populator = self._get_transformation_to_populator_space(self.panel, orientation)

        polylines = self.panel.plate_geometry.outline_a, self.panel.plate_geometry.outline_b
        local_polylines = [pl.transformed(self.transformation_to_populator) for pl in polylines]
        populator_panel = Panel.from_outlines(*local_polylines)

        return populator_panel

    def create_layers(self, populator_panel):
        """Build an ordered list of :class:`~timber_design.populators.Layer` objects.

        Resolves fill-remaining thicknesses, then delegates geometry creation
        to :meth:`layers_from_panel_and_thicknesses`.

        The user-supplied :attr:`layer_defs` are **never mutated**.  A
        deep copy of the definition tree is made before thickness resolution
        so that calling :meth:`create_populator` multiple times on the same
        config instance (e.g. in a Rhino live-update loop) always re-resolves
        from the original ``None`` values.

        Parameters
        ----------
        populator_panel : :class:`compas_timber.elements.Panel`
            The panel in populator space.

        Returns
        -------
        list[:class:`~timber_design.populators.Layer`]
            Ordered from the interior face (``outline_a``) to the exterior
            face (``outline_b``).
        """
        if not self.layer_defs:
            # No definitions — single framing layer spanning the full panel.
            return [Layer(populator_panel, "frame", layer_index=0, is_framing_layer=True)]

        # Deep-copy so _resolve_thicknesses never mutates the user's defs.
        # A synthetic root node lets the resolver handle fill-remaining at
        # the top level without special-casing.
        root = LayerDefinition(populator_panel.thickness, sublayers=[copy.deepcopy(ld) for ld in self.layer_defs])
        self._resolve_thicknesses(root)

        flat_defs = list(self._flat_layer_defs(root))

        return self.layers_from_panel_and_layer_defs(populator_panel, flat_defs)

    @staticmethod
    def layers_from_panel_and_layer_defs(panel, layer_defs):
        """Build :class:`~timber_design.populators.Layer` objects from resolved thicknesses.

        Uses *outline chaining*: the ``outline_b`` Polyline produced for each
        layer panel is reused directly as the ``outline_a`` of the next.  This
        guarantees that adjacent layers share an identical geometric boundary
        — no floating-point discrepancy from re-interpolating the same offset
        twice.

        Parameters
        ----------
        panel : :class:`compas_timber.elements.Panel`
            The source panel whose outline geometry is sliced.
        thicknesses : list[float]
            Resolved thickness for each entry in *layer_defs*.  Must have the
            same length.  Entries that are ``<= 0`` are skipped (but still
            consume their corresponding *layer_defs* entry).
        layer_defs : list[:class:`~timber_design.populators.LayerDefinition`]
            Leaf-level definitions — each without sublayers — providing
            ``name``, ``is_framing_layer``, and ``agent_configs``.

        Returns
        -------
        list[:class:`~timber_design.populators.Layer`]
        """
        layers = []
        outline_a = panel.outline_a
        total_thickness = panel.thickness
        cumulative = 0.0
        layer_index = 0
        thicknesses = [ld.thickness or 0.0 for ld in layer_defs]

        for ld, thickness in zip(layer_defs, thicknesses):
            if thickness <= 0:
                continue
            cumulative += thickness
            t = cumulative / total_thickness
            outline_b = Polyline(
                [pt_a * (1.0 - t) + pt_b * t for pt_a, pt_b in zip(panel.outline_a.points, panel.outline_b.points)]
            )
            layer_panel = Panel.from_outlines(outline_a, outline_b)
            layer = Layer(
                layer_panel,
                ld.name or str(layer_index),
                layer_index=layer_index,
                is_framing_layer=ld.is_framing_layer,
            )
            for agent_config in ld.agent_configs:
                layer.agents.append(agent_config.get_agent_from_layer(layer))
            layers.append(layer)
            # Chain: this layer's end boundary is the next layer's start boundary.
            outline_a = outline_b
            layer_index += 1

        return layers

    def _resolve_thicknesses(self, layer_def):
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
        self._infer_from_children(layer_def)
        self._distribute_to_children(layer_def)

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
            raise ValueError(
                "Cannot resolve fill-remaining sublayer(s) [{}] of layer {!r} "
                "because its own thickness is unknown.".format(
                    ", ".join(fill_names), layer_def.name
                )
            )

        if not fill:
            if not TOL.is_close(known_sum, layer_def.thickness):
                breakdown = ", ".join(
                    "{!r}={}".format(sl.name, sl.thickness) for sl in layer_def.sublayers
                )
                raise ValueError(
                    "Sublayers of layer {!r} sum to {} but layer thickness is {}. "
                    "Sublayers: [{}].".format(
                        layer_def.name, known_sum, layer_def.thickness, breakdown
                    )
                )
        else:
            if len(fill) > 1:
                fill_names = [repr(sl.name) for sl in fill]
                raise ValueError(
                    "At most one sublayer of layer {!r} may have thickness=None; "
                    "got {} ({}).".format(
                        layer_def.name, len(fill), ", ".join(fill_names)
                    )
                )
            remaining = layer_def.thickness - known_sum
            if remaining < 0 and not TOL.is_zero(remaining):
                breakdown = ", ".join(
                    "{!r}={}".format(sl.name, sl.thickness)
                    for sl in layer_def.sublayers
                    if sl.thickness is not None
                )
                raise ValueError(
                    "Fixed sublayers of layer {!r} ({}) exceed its thickness ({}); "
                    "no room left for fill-remaining sublayer {!r}. "
                    "Fixed sublayers: [{}].".format(
                        layer_def.name, known_sum, layer_def.thickness, fill[0].name, breakdown
                    )
                )
            fill[0].thickness = remaining

        for sl in layer_def.sublayers:
            self._distribute_to_children(sl)

    def create_feature_agents(self, layers):
        """Create all populator agents from the layer list.

        Iterates every layer, calling
        :meth:`~timber_design.populators.LayerAgentConfig.get_agent_from_layer`
        for each config stored in ``layer.layer_def.agent_configs``.
        Then applies ``default_feature_configs`` and ``instance_feature_configs``
        to all framing layers.

        Parameters
        ----------
        layers : list[:class:`~timber_design.populators.Layer`]
            As returned by :meth:`create_layers`.

        Returns
        -------
        list[:class:`~timber_design.populators.LayerAgent`]
        """

        agents = []

        explicitly_defined = {agent_config.feature for agent_config in self.instance_feature_configs}

        # Default feature agents applied to all framing layers
        for feature in self.panel.features:
            if feature in explicitly_defined:
                continue
            agent_config = self._find_definition_for_feature(feature, self.default_feature_configs)
            if agent_config is None:
                continue
            transformed_feature = feature.transformed(self.transformation_to_populator)
            agents.append(agent_config.get_agent_from_feature(transformed_feature))

        # Instance feature agents — each config carries its own .feature reference
        for agent_config in self.instance_feature_configs:
            transformed_feature = agent_config.feature.transformed(self.transformation_to_populator)
            agents.append(agent_config.get_agent_from_feature(transformed_feature))

        return agents

    def create_populator(self):
        """Build and return a fully-configured :class:`~timber_design.populators.PanelPopulator`.

        Runs the full pipeline: transform panel → create layers → create agents
        → resolve beam dimensions → construct populator.

        Returns
        -------
        :class:`~timber_design.populators.PanelPopulator`

        Raises
        ------
        ValueError
            If no panel has been set.
        """
        if self.panel is None:
            raise ValueError("No panel provided.")

        self.populator_panel = self.get_populator_panel()
        layers = self.create_layers(self.populator_panel)
        feature_agents = self.create_feature_agents(layers)
        self.resolve_beam_dimensions(layers, feature_agents)

        return PanelPopulator(
            self.populator_panel,
            layers,
            feature_agents,
            original_panel=self.panel,
            transformation_to_populator=self.transformation_to_populator,
        )


    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _flat_layer_defs(self, layer_def):
        """Yield leaf-level :class:`LayerDefinition` objects (depth-first).

        Assumes thicknesses have already been resolved by
        :meth:`_resolve_thicknesses`.
        """
        for ld in layer_def.sublayers:
            if ld.sublayers:
                yield from self._flat_layer_defs(ld)
            else:
                yield ld


    def resolve_beam_dimensions(self, layers, feature_agents):
        """Populate :attr:`~timber_design.populators.LayerAgent.beam_dimensions` on every agent.

        For :class:`~timber_design.populators.LayerAgent` instances bound to a
        specific layer, the beam height is taken from ``layer.thickness``.
        For :class:`~timber_design.populators.FeatureAgent` instances (which
        may act across multiple layers), a sentinel height of ``0.0`` is
        stored — the per-layer height is supplied when needed via the
        ``layer`` kwarg of
        :meth:`~timber_design.populators.LayerAgent.beam_from_category`.

        Parameters
        ----------
        layers : list[:class:`~timber_design.populators.Layer`]
            All resolved layers (as returned by :meth:`create_layers`).
        feature_agents : list[:class:`~timber_design.populators.FeatureAgent`]
            Feature agents produced by :meth:`create_feature_agents`.
        """
        seen = set()
        for layer in layers:
            for agent in layer.agents:
                if id(agent) in seen:
                    continue
                seen.add(id(agent))
                thickness = agent.layer.thickness if agent.layer is not None else 0.0
                agent.resolve_beam_dimensions(self.standard_beam_width, thickness)
        for agent in feature_agents:
            if id(agent) in seen:
                continue
            seen.add(id(agent))
            agent.resolve_beam_dimensions(self.standard_beam_width, 0.0)

    @staticmethod
    def _find_definition_for_feature(feature, definitions):
        """Return the most specific config for *feature* using MRO-based lookup.

        Walks ``type(feature).__mro__`` from most to least specific, returning
        the first entry found in *definitions*.

        Parameters
        ----------
        feature : object
        definitions : dict[type, LayerAgentConfig]

        Returns
        -------
        LayerAgentConfig or None
        """
        for t in type(feature).__mro__:
            if t in definitions:
                return definitions[t]
        return None

    def _get_projected_orientation(self):
        """Project ``self.orientation`` (if set) onto the panel plane.

        Returns ``Vector(0, 1, 0)`` when no ``orientation`` is set or when
        it is perpendicular to the panel normal.
        """
        if not self.orientation:
            return Vector(0, 1, 0)
        if self.panel is None:
            return Vector(0, 1, 0)
        perp = cross_vectors(self.panel.normal, self.orientation)
        if all(TOL.is_zero(perp[i]) for i in range(3)):
            return Vector(0, 1, 0)
        return Vector(*cross_vectors(perp, self.panel.normal)).transformed(self.panel.transformation_to_local())

    def _get_transformation_to_populator_space(self, panel, orientation):
        """Return the transformation from world/panel space into populator space."""
        transformation_to_populator_panel = self._get_transformation_to_populator_panel(panel, orientation)
        return  transformation_to_populator_panel

    def _get_transformation_to_populator_panel(self, panel, orientation):
        """Return the transformation that aligns *panel* to the XY plane."""
        stud_dir_frame = Frame(Point(0, 0, 0), cross_vectors(orientation, Vector(0, 0, 1)), orientation)
        transform_to_stud_dir_frame = Transformation.from_frame(stud_dir_frame).inverse()
        pts = [pt.transformed(transform_to_stud_dir_frame) for pt in panel.plate_geometry.outline_a.points + panel.plate_geometry.outline_b.points]
        min_pt = Box.from_points(pts).points[0]
        obb_frame = Frame(min_pt, Vector(1, 0, 0), Vector(0, 1, 0)).transformed(transform_to_stud_dir_frame.inverse())
        return Transformation.from_frame(obb_frame).inverse()
