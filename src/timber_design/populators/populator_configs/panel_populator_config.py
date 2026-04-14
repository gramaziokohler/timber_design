from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from typing import TYPE_CHECKING
from typing import Dict

from compas.geometry import Box
from compas.geometry import Line
from compas.geometry import Frame
from compas.geometry import Point
from compas.geometry import Polyline
from compas.geometry import Transformation
from compas.geometry import Translation
from compas.geometry import Vector
from compas.geometry import cross_vectors
from compas.tolerance import TOL
from compas_timber.elements import Panel

from timber_design.populators.layer import Layer, LayerDefinition
from timber_design.populators.populator import PanelPopulator

if TYPE_CHECKING:
    pass


class PanelPopulatorConfig:
    """Abstract base config for creating panel populator agents.

    Combines configuration data (previously in ``PopulatorFactoryParams``) and
    factory behaviour (previously in ``PanelPopulatorFactory``) into a single class.

    Parameters
    ----------
    panel : :class:`compas_timber.elements.Panel`, optional
        The panel to populate.  Stored for use with :meth:`create_populator`.
    default_feature_configs : list[PopulatorAgentConfig], optional
        List of agent configs (with ``FEATURE_TYPE`` set) for default feature handling.
        Applied using MRO-based lookup: the most specific matching key wins.
        Instance-level definitions passed directly to :meth:`create_populator_from_panel`
        always take precedence.
    instance_feature_configs : list[PopulatorAgentConfig], optional
        List of agent configs with ``feature`` set.  These take precedence over
        ``default_feature_configs`` for the specific feature instances referenced.
    """

    def __init__(self, panel=None, layer_defs=None, default_feature_configs=None, instance_feature_configs=None):
        self.panel = panel

        self.layer_defs = layer_defs or [LayerDefinition(self.panel.thickness - self.inside_layer_def.thickness - self.outside_layer_def.thickness, is_framing_layer=True)]

        self.default_feature_configs = default_feature_configs or {}
        self.instance_feature_configs = instance_feature_configs or []


    def create_populator_agents(self, layers) -> list:
        """Create populator agents for the given panel.

        Parameters
        ----------
        layers : dict[str, :class:`~timber_design.populators.Layer`]
            All layers for the panel, keyed by name.  Always contains
            ``"local"`` and ``"frame"`` entries; ``"interior"`` and
            ``"exterior"`` are present only when the corresponding sheeting
            thickness is non-zero.

        Returns
        -------
        list[:class:`~timber_design.populators.PopulatorAgent`]
            The list of agents.  ``resolve_beam_dimensions`` must NOT be called
            here; :meth:`create_populator_from_panel` calls it on every agent
            after all agents are assembled.
        """
        return self._get_default_agents(layers) + self._get_instance_agents(layers)

    def create_populator(self):
        """Create a fully-configured :class:`~timber_design.populators.PanelPopulator`.

        Parameters
        ----------
        panel : :class:`compas_timber.elements.Panel`
            The source panel to populate.
        feature_configs : list[PopulatorAgentConfig], optional
            Per-instance overrides.  A list of
            :class:`~timber_design.populators.PopulatorAgentConfig` instances
            with ``feature`` set on each entry.  Features referenced here are
            excluded from ``default_feature_configs`` type-level processing
            so that explicit definitions always take precedence.

        Returns
        -------
        :class:`~timber_design.populators.PanelPopulator`
        """
        if self.panel is None:
            raise ValueError("No panel provided.")

        populator_panel = self.get_populator_panel()

        layers = self.create_layers(populator_panel)
        agents = self.create_populator_agents(layers)
        self._resolve_beam_dimensions(agents)

        return PanelPopulator(
            agents,
            original_panel=self.panel,
            transformation_to_populator=self.transformation_to_populator,
        )

    def _get_layer_agents(self, layers):
        explicitly_defined_features = {f.feature for f in (self.instance_feature_configs)}
        for layer in layers:
            if layer.agent_defs:
                for agent_def in layer.agent_defs:
                    layer.agents.append(agent_def.get_agent_from_panel(layer))

    def _set_default_agents(self, layers):
        explicitly_defined_features = {f.feature for f in (self.instance_feature_configs)}
        for feature in self.panel.features:
            if feature in explicitly_defined_features:
                continue
            agent_config = self._find_definition_for_feature(feature, self.default_feature_configs)
            if agent_config is not None:
                transformed_feature = feature.transformed(self.transformation_to_populator)
                for layer in self.framing_layers:
                    layer.agents.append(agent_config.get_agent_from_feature(transformed_feature))

    def _set_instance_agents(self):
        for agent_config in self.instance_feature_configs:
            transformed_feature = agent_config.feature.transformed(self.transformation_to_populator)
            for layer in self.framing_layers:
                layer.agents.append(agent_config.get_agent_from_feature(transformed_feature))

    def get_populator_panel(self):
        orientation = self._get_projected_orientation(self.panel)
        self.transformation_to_populator = self._get_transformation_to_populator_space(self.panel, orientation, self)
        polylines = self.panel.plate_geometry.outline_a, self.panel.plate_geometry.outline_b
        local_polylines = [pl.transformed(self.transformation_to_populator) for pl in polylines]
        return Panel.from_outlines(*local_polylines)

    def create_layers(self) -> tuple:
        """Build all layers, including sublayer, as a sandwich of yummy Layer objects.
        """

        def get_leaf_layer_defs(layer_defs, location=None):
            """Return a flat list of all layers, including sublayers."""
            flat = []
            for ld in layer_defs:
                location = ld.location or location
                if ld.sublayers:
                    flat.extend(get_leaf_layer_defs(ld.sublayers, location))
                else:
                    flat.append(ld)
            return flat

        all_layer_defs = get_leaf_layer_defs([self.inside_layer, self.frame_layer, self.outside_layer])

        layers = []
        lines = [Line(a,b) for a, b in zip(self.populator_panel.outline_a.points, self.populator_panel.outline_b.points)]
        range_start = 0.0
        for i, ld in enumerate(all_layer_defs):
            range_end = range_start + ld.thickness
            layers.append(Layer.from_panel_and_range(self.populator_panel, range_start, range_end, ld.name, agent_defs=ld.agent_defs, layer_index=i))
            range_start = range_end
        return layers


# =============================================================================
# Private helpers
# =============================================================================

    def _resolve_beam_dimensions(self, agents, frame_panel):
        standard_beam_width = getattr(self, "standard_beam_width", 0.0)
        for agent in agents:
            agent.resolve_beam_dimensions(frame_panel.thickness, standard_beam_width)

    def _find_definition_for_feature(feature, definitions):
        """Return the most specific config for *feature* using MRO-based lookup.

        Walks ``type(feature).__mro__`` from most to least specific, returning the
        first entry found in *definitions*.

        Parameters
        ----------
        feature : object
        definitions : dict[type, PopulatorAgentConfig]

        Returns
        -------
        PopulatorAgentConfig or None
        """
        for t in type(feature).__mro__:
            if t in definitions:
                return definitions[t]
        return None

    def _get_projected_orientation(self) -> Vector:
        """Project ``self.stud_direction`` onto the panel plane.

        Returns ``Vector(0, 1, 0)`` if no stud_direction is set or if it is
        perpendicular to the panel normal.
        """
        orientation = getattr(self, "stud_direction", None)
        if not orientation:
            return Vector(0, 1, 0)
        perp = cross_vectors(self.panel.normal, orientation)
        if all(TOL.is_zero(perp[i]) for i in range(3)):
            return Vector(0, 1, 0)
        return Vector(*cross_vectors(perp, self.panel.normal)).transformed(self.panel.transformation_to_local())

    def _get_transformation_to_populator_space(self, panel, orientation, config):
        # type: (Panel, Vector, object) -> Transformation
        """Return the transformation from world/panel space into the populator's local XY space."""
        transformation_to_populator_panel = self._get_transformation_to_populator_panel(panel, orientation)
        translation_to_frame_center = self._get_translation_to_frame_center(panel, config)
        return translation_to_frame_center * transformation_to_populator_panel


    def _get_transformation_to_populator_panel(self, panel, stud_direction):
        # type: (Panel, Vector) -> Transformation
        stud_dir_frame = Frame(Point(0, 0, 0), cross_vectors(stud_direction, Vector(0, 0, 1)), stud_direction)
        transform_to_stud_dir_frame = Transformation.from_frame(stud_dir_frame).inverse()
        pts = [pt.transformed(transform_to_stud_dir_frame) for pt in panel.plate_geometry.outline_a.points + panel.plate_geometry.outline_b.points]
        min_pt = Box.from_points(pts).points[0]
        obb_frame = Frame(min_pt, Vector(1, 0, 0), Vector(0, 1, 0)).transformed(transform_to_stud_dir_frame.inverse())
        return Transformation.from_frame(obb_frame).inverse()


    def _get_translation_to_frame_center(self, panel, config):
        # type: (Panel, object) -> Translation
        si = self.inside_layer.thickness
        so = self.outside_layer.thickness
        frame_thickness = panel.thickness - si - so
        return Translation.from_vector(-Vector(0, 0, si + frame_thickness / 2))
