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
from compas_model.models import ElementTree
from compas_timber.model import TimberModel

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
        :class:`~timber_design.populators.FeatureAgentConfig` (without
        ``feature`` set).  Applied to every matching panel feature via
        MRO-based lookup.
    instance_feature_configs : list[:class:`~timber_design.populators.FeatureAgentConfig`], optional
        Per-instance feature overrides.  Each entry has its ``feature``
        attribute set to the specific feature instance.  These take precedence
        over ``default_feature_configs`` for that feature.
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
        self.layer_def = LayerDefinition(panel.thickness if panel else None, sublayers=[copy.deepcopy(ld) for ld in layer_defs] if layer_defs else None)   
        self.default_feature_configs = default_feature_configs or {}
        self.instance_feature_configs = instance_feature_configs or []
        self.orientation = orientation
        self.standard_beam_width = standard_beam_width
        # Set by _prepare_panels / create_populator
        self.transformation_to_populator = None

    # ------------------------------------------------------------------
    # Public pipeline methods
    # ------------------------------------------------------------------

    def get_populator_panel(self):
        """Transform *panel* to populator space and build the layer dict.

        Returns
        -------
        :class:`compas_timber.elements.Panel`
        """
        orientation = self._get_projected_orientation()
        self.transformation_to_populator = self._get_transformation_to_populator_space(self.panel, orientation)

        # Use the mutated outlines so panel joints are accounted for.
        polylines = self.panel.plate_geometry.outline_a, self.panel.plate_geometry.outline_b
        local_polylines = [pl.transformed(self.transformation_to_populator) for pl in polylines]
        populator_panel = Panel.from_outlines(*local_polylines)
        return populator_panel

    def create_populator_model(self):
        """Build :class:`~timber_design.populators.Layer` objects from resolved thicknesses.

        Uses *outline chaining*: the ``outline_b`` produced for each layer
        panel is reused as the ``outline_a`` of the next.  This guarantees
        adjacent layers share an identical geometric boundary with no
        floating-point discrepancy.

        Also builds :attr:`_original_ld_to_layer` — a mapping from the
        identity of each original (user-supplied) :class:`LayerDefinition`
        leaf to its resolved :class:`Layer`.  This is consumed by
        :meth:`_resolve_layer_defs` so that
        :attr:`~FeatureAgentConfig.framing_layer_defs` /
        :attr:`~FeatureAgentConfig.trimming_layer_defs` can be translated to
        concrete :class:`Layer` instances.

        Returns
        -------
        list[:class:`~timber_design.populators.Layer`]
        """
        layer_model = self.layer_def.model_from_panel(self.panel)
        return layer_model

    def create_feature_agents(self):
        """Create all feature populator agents.

        Iterates panel features and applies ``default_feature_configs`` via
        MRO-based lookup, then adds any ``instance_feature_configs``.

        For each config that declares :attr:`~FeatureAgentConfig.framing_layer_defs`
        or :attr:`~FeatureAgentConfig.trimming_layer_defs`, the
        :class:`LayerDefinition` references are resolved to concrete
        :class:`Layer` objects via :meth:`_resolve_layer_defs` before the
        agent is instantiated.

        Parameters
        ----------
        layers : list[:class:`~timber_design.populators.Layer`]
            As returned by :meth:`create_layers`.

        Returns
        -------
        list[:class:`~timber_design.populators.FeatureAgent`]
        """
        agents = []

        explicitly_defined = {agent_config.feature for agent_config in self.instance_feature_configs}

        # Default feature agents applied to all matching panel features.
        for feature in self.panel.features:
            if feature in explicitly_defined:
                continue
            agent_config = self._find_definition_for_feature(feature, self.default_feature_configs)
            if agent_config is None:
                continue
            transformed_feature = feature.transformed(self.transformation_to_populator)
            framing_layers = [ld.resulting_layer for ld in agent_config.framing_layer_defs]
            trimming_layers = [ld.resulting_layer for ld in agent_config.trimming_layer_defs]
            agents.append(agent_config.get_agent_from_feature(transformed_feature, framing_layers, trimming_layers))

        # Instance feature agents — each config carries its own .feature reference.
        for agent_config in self.instance_feature_configs:
            transformed_feature = agent_config.feature.transformed(self.transformation_to_populator)
            framing_layers = [ld.resulting_layer for ld in agent_config.framing_layer_defs]
            trimming_layers = [ld.resulting_layer for ld in agent_config.trimming_layer_defs]
            agents.append(agent_config.get_agent_from_feature(transformed_feature, framing_layers, trimming_layers))

        return agents

    def create_populator(self):
        """Build and return a fully-configured :class:`~timber_design.populators.PanelPopulator`.

        Runs the full pipeline: transform panel → resolve beam dimensions
        → create layers → create feature agents → construct populator.

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

        # Reset the cached leaf-layer-def list so thickness resolution and
        # deep-copying of agent configs always run on the original definitions,
        # even when create_populator() is called multiple times on the same config.
        self._layer_def_stack = None

        self.populator_panel = self.get_populator_panel()
        self.resolve_beam_dimensions()
        layer_model=self.create_populator_model()
        feature_agents = self.create_feature_agents()

        return PanelPopulator(
            self.populator_panel,
            layer_model,
            feature_agents,
            original_panel=self.panel,
            transformation_to_populator=self.transformation_to_populator,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def resolve_beam_dimensions(self):
        """Populate :attr:`~timber_design.populators.LayerAgentConfig.beam_dimensions` on every config.

        For :class:`~timber_design.populators.LayerAgentConfig` instances bound
        to a specific layer, the beam height is taken from ``ld.thickness``.
        For feature agent configs a sentinel height of ``0.0`` is stored —
        the per-layer height is supplied when needed via the ``layer`` kwarg of
        :meth:`~timber_design.populators.LayerAgent.beam_from_category`.
        """
        if not self.standard_beam_width:
            if not self.panel:
                raise AttributeError("cannot resolve standard_beam_width without panel")
            self.standard_beam_width = self.panel.thickness / 2.0
        seen = set()
        self.layer_def.resolve_beam_dimensions(self.standard_beam_width)
        for ad in self.instance_feature_configs + list(self.default_feature_configs.values()):
            ad.resolve_beam_dimensions(self.standard_beam_width, 0.0)

    @staticmethod
    def _find_definition_for_feature(feature, definitions):
        """Return the most specific config for *feature* using MRO-based lookup.

        Walks ``type(feature).__mro__`` from most to least specific, returning
        the first entry found in *definitions*.

        Parameters
        ----------
        feature : object
        definitions : dict[type, FeatureAgentConfig]

        Returns
        -------
        FeatureAgentConfig or None
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
        return self._get_transformation_to_populator_panel(panel, orientation)

    def _get_transformation_to_populator_panel(self, panel, orientation):
        """Return the transformation that aligns *panel* to the XY plane."""
        stud_dir_frame = Frame(Point(0, 0, 0), cross_vectors(orientation, Vector(0, 0, 1)), orientation)
        transform_to_stud_dir_frame = Transformation.from_frame(stud_dir_frame).inverse()
        pts = [pt.transformed(transform_to_stud_dir_frame) for pt in panel.plate_geometry.outline_a.points + panel.plate_geometry.outline_b.points]
        min_pt = Box.from_points(pts).points[0]
        obb_frame = Frame(min_pt, Vector(1, 0, 0), Vector(0, 1, 0)).transformed(transform_to_stud_dir_frame.inverse())
        return Transformation.from_frame(obb_frame).inverse()
