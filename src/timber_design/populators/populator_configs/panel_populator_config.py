from __future__ import annotations

import copy
from typing import TYPE_CHECKING

from compas.geometry import Box
from compas.geometry import Frame
from compas.geometry import Point
from compas.geometry import Polyline
from compas.geometry import Transformation
from compas.geometry import Vector
from compas.geometry import cross_vectors
from compas.tolerance import TOL
from compas_timber.elements import Panel

from timber_design.populators import populator
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
        self._layer_def_stack = None

    @property
    def layer_def_stack(self):
        if not self._layer_def_stack:
            if not self.panel:
                raise AttributeError("layer_definition requires a panel be defined")
            if not self.layer_defs:
                return LayerDefinition(self.panel.thickness, is_framing_layer=True)
            self._layer_def_stack = LayerDefinition(self.panel.thickness, sublayers=[copy.deepcopy(ld) for ld in self.layer_defs]).get_leaf_layer_defs()
        return self._layer_def_stack

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

        #this needs the mutated outlines to properly handle panel joints
        polylines = self.panel.plate_geometry.outline_a, self.panel.plate_geometry.outline_b 
        local_polylines = [pl.transformed(self.transformation_to_populator) for pl in polylines]
        populator_panel = Panel.from_outlines(*local_polylines)
        return populator_panel




    def create_layers(self):
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
        outline_a = self.populator_panel.outline_a
        total_thickness = self.populator_panel.thickness
        cumulative = 0.0
        layer_index = 0

        for ld in self.layer_def_stack:
            if ld.thickness <= 0:
                continue
            cumulative += ld.thickness
            t = cumulative / total_thickness
            outline_b = Polyline([pt_a * (1.0 - t) + pt_b * t for pt_a, pt_b in zip(self.populator_panel.outline_a.points, self.populator_panel.outline_b.points)])
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
        self.resolve_beam_dimensions()
        layers = self.create_layers() #contains LayerAgents
        feature_agents = self.create_feature_agents(layers)

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



    def resolve_beam_dimensions(self):
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
        for ld in self.layer_def_stack:
            for ad in ld.agent_configs:
                if id(ad) in seen:
                    continue
                seen.add(id(ad))
                ad.resolve_beam_dimensions(self.standard_beam_width, ld.thickness)
        for ad in self.instance_feature_configs + list(self.default_feature_configs.values()):
            if id(ad) in seen:
                continue
            seen.add(id(ad))
            ad.resolve_beam_dimensions(self.standard_beam_width, 0.0) 

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
        return transformation_to_populator_panel

    def _get_transformation_to_populator_panel(self, panel, orientation):
        """Return the transformation that aligns *panel* to the XY plane."""
        stud_dir_frame = Frame(Point(0, 0, 0), cross_vectors(orientation, Vector(0, 0, 1)), orientation)
        transform_to_stud_dir_frame = Transformation.from_frame(stud_dir_frame).inverse()
        pts = [pt.transformed(transform_to_stud_dir_frame) for pt in panel.plate_geometry.outline_a.points + panel.plate_geometry.outline_b.points]
        min_pt = Box.from_points(pts).points[0]
        obb_frame = Frame(min_pt, Vector(1, 0, 0), Vector(0, 1, 0)).transformed(transform_to_stud_dir_frame.inverse())
        return Transformation.from_frame(obb_frame).inverse()
