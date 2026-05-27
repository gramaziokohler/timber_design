from __future__ import annotations

from typing import TYPE_CHECKING

from compas.geometry import Box
from compas.geometry import Frame
from compas.geometry import Point
from compas.geometry import Transformation
from compas.geometry import Vector
from compas.geometry import cross_vectors
from compas.tolerance import TOL
from compas_timber.elements import Panel

from timber_design.populators.layer import LayerConfig
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
    layer_defs : list[:class:`~timber_design.populators.LayerConfig`], optional
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
        self.root_layer_def = LayerConfig(panel.thickness if panel else None, sublayers=list(layer_defs) if layer_defs else None)
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

    def _iter_agent_configs(self):
        """Yield every agent config in the panel: layer agents then feature agents.

        Walks the :class:`LayerConfig` tree (depth-first) collecting each layer's
        ``agent_configs``, then yields the ``default_feature_configs`` values and
        ``instance_feature_configs``.
        """

        def walk(layer_def):
            for agent_config in layer_def.agent_configs:
                yield agent_config
            for sublayer in layer_def.sublayers:
                yield from walk(sublayer)

        yield from walk(self.root_layer_def)
        for agent_config in self.default_feature_configs.values():
            yield agent_config
        for agent_config in self.instance_feature_configs:
            yield agent_config

    def resolve_beam_widths(self):
        """Fill every agent config's ``beam_widths`` with :attr:`standard_beam_width`.

        This is the single place where the panel-wide default beam width is
        pushed into the agent configs.  Each config keeps any explicit
        per-category widths it was given and only the unset categories are
        filled (see :meth:`~PopulatorAgentConfig.fill_beam_widths`).
        """
        for agent_config in self._iter_agent_configs():
            agent_config.fill_beam_widths(self.standard_beam_width)

    def create_populator_model(self):
        """Resolve beam widths and build the :class:`Layer` model from the panel.

        Resolves :attr:`standard_beam_width` (defaulting to half the panel
        thickness), fills every agent config's beam widths, then delegates the
        actual layer slicing and agent attachment to
        :meth:`~timber_design.populators.LayerConfig.model_from_panel`.

        Returns
        -------
        :class:`~compas_timber.model.TimberModel`
        """
        if not self.standard_beam_width:
            ref = getattr(self, "populator_panel", None) or self.panel
            if ref:
                self.standard_beam_width = ref.thickness / 2.0
        if not self.root_layer_def.thickness:
            ref = getattr(self, "populator_panel", None) or self.panel
            if ref:
                self.root_layer_def.thickness = ref.thickness
        self.resolve_beam_widths()
        return self.root_layer_def.model_from_panel(self.populator_panel)

    def create_feature_agents(self):
        """Create all feature populator agents.

        Iterates panel features and applies ``default_feature_configs`` via
        MRO-based lookup, then adds any ``instance_feature_configs``.

        For each config that declares :attr:`~FeatureAgentConfig.framing_layer_defs`
        or :attr:`~FeatureAgentConfig.trimming_layer_defs`, the
        :class:`LayerConfig` references are resolved to concrete
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
            framing_layers = [ld.resulting_layer for ld in (agent_config.framing_layer_defs or [])]
            trimming_layers = [ld.resulting_layer for ld in (agent_config.trimming_layer_defs or [])]
            agents.append(agent_config.get_agent_from_feature(transformed_feature, framing_layers, trimming_layers))

        # Instance feature agents — each config carries its own .feature reference.
        for agent_config in self.instance_feature_configs:
            transformed_feature = agent_config.feature.transformed(self.transformation_to_populator)
            framing_layers = [ld.resulting_layer for ld in (agent_config.framing_layer_defs or [])]
            trimming_layers = [ld.resulting_layer for ld in (agent_config.trimming_layer_defs or [])]
            agents.append(agent_config.get_agent_from_feature(transformed_feature, framing_layers, trimming_layers))

        return agents

    def create_populator(self):
        """Build and return a fully-configured :class:`~timber_design.populators.PanelPopulator`.

        Runs the full pipeline: transform panel → resolve standard_beam_width
        → create layers (agents receive beam widths at construction time)
        → create feature agents → construct populator.

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
        if not self.standard_beam_width:
            self.standard_beam_width = self.populator_panel.thickness / 2.0
        if not self.root_layer_def.thickness:
            self.root_layer_def.thickness = self.populator_panel.thickness

        populator_model = self.create_populator_model()
        feature_agents = self.create_feature_agents()

        return PanelPopulator(
            self.populator_panel,
            populator_model,
            feature_agents,
            original_panel=self.panel,
            transformation_to_populator=self.transformation_to_populator,
        )

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
