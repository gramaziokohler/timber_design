from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING
from typing import List

from compas.geometry import Box
from compas.geometry import Frame
from compas.geometry import Point
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
# Module-level helper functions (backward-compatible API)
# =============================================================================


def get_frame_panel(panel, config):
    """Return the structural frame panel trimmed by the sheeting layers.

    Parameters
    ----------
    panel : :class:`compas_timber.elements.Panel`
        The source panel (any coordinate space).
    config : object
        Must expose ``sheeting_inside`` and ``sheeting_outside`` attributes
        (floats, zero when no sheeting).

    Returns
    -------
    :class:`compas_timber.elements.Panel`
    """
    return get_layers(panel, config)["frame"].panel


def get_layers(panel, config):
    """Build the standard layer dict for *panel* from sheeting parameters.

    Always returns ``"local"`` (full panel) and ``"frame"`` (structural frame).
    Adds ``"interior"`` when ``config.sheeting_inside > 0`` and
    ``"exterior"`` when ``config.sheeting_outside > 0``.

    Parameters
    ----------
    panel : :class:`compas_timber.elements.Panel`
        The source panel (any coordinate space).
    config : object
        Must expose ``sheeting_inside`` and ``sheeting_outside`` float attrs.

    Returns
    -------
    dict[str, :class:`~timber_design.populators.Layer`]
    """
    si = getattr(config, "sheeting_inside", 0.0) or 0.0
    so = getattr(config, "sheeting_outside", 0.0) or 0.0

    layers = {}
    layers["local"] = Layer(panel, "local")
    layers["frame"] = Layer.from_panel_and_range(panel, si, panel.thickness - so, name="frame")
    if si:
        layers["interior"] = Layer.from_panel_and_range(panel, 0.0, si, name="interior")
    if so:
        layers["exterior"] = Layer.from_panel_and_range(panel, panel.thickness - so, panel.thickness, name="exterior")
    return layers


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
        :class:`~timber_design.populators.PopulatorAgentConfig` (without
        ``feature`` set).  Applied to every framing layer via MRO-based
        lookup.
    instance_feature_configs : list, optional
        Per-feature config overrides.  Each entry must have ``feature`` set.
        These take precedence over ``default_feature_configs``.
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
        """Build an ordered dict of :class:`~timber_design.populators.Layer` objects.

        Iterates the flat leaf-level :class:`~timber_design.populators.LayerDefinition`
        tree, resolves any fill-remaining (``thickness=None``) entries, and
        creates each layer via
        :meth:`~timber_design.populators.Layer.from_panel_and_range`.

        Always includes a ``"local"`` entry covering the full panel.

        Parameters
        ----------
        populator_panel : :class:`compas_timber.elements.Panel`
            The panel in populator space (used to resolve fill-remaining
            thicknesses and to compute layer geometry).

        Returns
        -------
        dict[str, :class:`~timber_design.populators.Layer`]
        """
        flat_defs = list(self._flat_layer_defs(self.layer_defs))

        if not flat_defs:
            # No definitions — create a single framing layer for the full panel.
            frame_def = LayerDefinition(populator_panel.thickness, name="frame", is_framing_layer=True)
            return {
                "local": Layer(populator_panel, "local"),
                "frame": Layer(populator_panel, "frame", layer_def=frame_def, layer_index=0),
            }

        # Resolve fill-remaining ("thickness=None") entries.
        fixed_total = sum(ld.thickness for ld in flat_defs if ld.thickness is not None)
        fill_count = sum(1 for ld in flat_defs if ld.thickness is None)
        fill_thickness = (populator_panel.thickness - fixed_total) / fill_count if fill_count else 0.0

        layers = {"local": Layer(populator_panel, "local")}
        range_start = 0.0
        for i, ld in enumerate(flat_defs):
            thickness = ld.thickness if ld.thickness is not None else fill_thickness
            range_end = range_start + thickness
            name = ld.name or str(i)
            layer = Layer.from_panel_and_range(
                populator_panel,
                range_start,
                range_end,
                name=name,
                layer_def=ld,
                layer_index=i,
            )
            layers[name] = layer
            range_start = range_end

        return layers

    def create_populator_agents(self, layers):
        """Create all populator agents from the layer dict.

        Iterates every layer, calling
        :meth:`~timber_design.populators.PopulatorAgentConfig.get_agent_from_layer`
        for each config stored in ``layer.layer_def.agent_configs``.
        Then applies ``default_feature_configs`` and ``instance_feature_configs``
        to all framing layers.

        Parameters
        ----------
        layers : dict[str, :class:`~timber_design.populators.Layer`]
            As returned by :meth:`create_layers`.

        Returns
        -------
        list[:class:`~timber_design.populators.PopulatorAgent`]
        """
        if self._agents_factory is not None:
            return self._agents_factory(self, layers)

        agents = []

        # Agents defined on each layer via LayerDefinition.agent_configs
        for layer in layers.values():
            if layer.layer_def is None:
                continue
            for agent_config in layer.layer_def.agent_configs:
                agents.append(agent_config.get_agent_from_layer(layer))

        if not self.panel:
            return agents

        framing_layers = [l for l in layers.values() if l.is_framing_layer]
        explicitly_defined = {fc.feature for fc in self.instance_feature_configs}

        # Default feature agents applied to all framing layers
        for feature in self.panel.features:
            if feature in explicitly_defined:
                continue
            agent_config = self._find_definition_for_feature(feature, self.default_feature_configs)
            if agent_config is None:
                continue
            transformed_feature = feature.transformed(self.transformation_to_populator)
            for layer in framing_layers:
                agents.append(agent_config.get_agent_from_feature(transformed_feature, layer))

        # Instance feature agents applied to all framing layers
        for agent_config in self.instance_feature_configs:
            transformed_feature = agent_config.feature.transformed(self.transformation_to_populator)
            for layer in framing_layers:
                agents.append(agent_config.get_agent_from_feature(transformed_feature, layer))

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
        agents = self.create_populator_agents(layers)
        self.resolve_beam_dimensions(agents)

        return PanelPopulator(
            self.populator_panel,
            agents,
            original_panel=self.panel,
            transformation_to_populator=self.transformation_to_populator,
        )

    # ------------------------------------------------------------------
    # Alternate constructors
    # ------------------------------------------------------------------

    @classmethod
    def stud_panel(
        cls,
        panel=None,
        standard_beam_width=None,
        stud_spacing=None,
        standard_beam_width_increment=None,
        edge_beam_min_width=None,
        orientation=None,
        sheeting_outside=0,
        sheeting_inside=0,
        lintel_posts=False,
        split_bottom_plate_beam=False,
        beam_width_overrides=None,
        joint_rule_overrides=None,
        default_feature_configs=None,
    ):
        """Create a config for a standard stud-framed wall panel.

        Parameters
        ----------
        standard_beam_width : float, optional
            Default width for all framing beams.
        stud_spacing : float, optional
            On-centre spacing between studs.  When ``None`` (or ``0``), no stud
            agent is created (edge-only panel).
        standard_beam_width_increment : float, optional
            Rounding increment for edge-beam widths.
        edge_beam_min_width : float, optional
            Minimum width for edge beams.
        orientation : :class:`compas.geometry.Vector`, optional
            Desired stud orientation in world space.
        sheeting_outside : float, optional
            Thickness of the external sheathing plate.
        sheeting_inside : float, optional
            Thickness of the internal sheathing plate.
        lintel_posts : bool, optional
            When ``True``, jack studs are added inside the king studs at openings.
        split_bottom_plate_beam : bool, optional
            When ``True``, the bottom plate beam is split at the door opening.
        beam_width_overrides : dict, optional
            Per-category width overrides.
        joint_rule_overrides : list, optional
            Rules that replace matching entries in any agent's ``INTERNAL_RULES`` list.
        default_feature_configs : dict, optional
            Mapping from panel feature class to a ``PopulatorAgentConfig`` instance.
        """
        from timber_design.populators.populator_agents.edge_populator_agent import EdgePopulatorAgentConfig
        from timber_design.populators.populator_agents.plate_populator_agent import PlatePopulatorAgentConfig
        from timber_design.populators.populator_agents.stud_populator_agent import StudPopulatorAgentConfig

        standard_beam_width = standard_beam_width or (panel.thickness / 2 if panel else None)
        stud_spacing = stud_spacing or (panel.thickness * 2 if panel else None)

        frame_agent_configs = [
            EdgePopulatorAgentConfig(
                standard_beam_width_increment=standard_beam_width_increment,
                edge_beam_min_width=edge_beam_min_width or standard_beam_width,
                beam_width_overrides=beam_width_overrides,
                joint_rule_overrides=joint_rule_overrides,
            ),
        ]
        if stud_spacing:
            frame_agent_configs.append(
                StudPopulatorAgentConfig(
                    stud_spacing=stud_spacing,
                    beam_width_overrides=beam_width_overrides,
                    joint_rule_overrides=joint_rule_overrides,
                )
            )

        layer_defs = []
        if sheeting_inside:
            layer_defs.append(LayerDefinition(sheeting_inside, name="interior", agent_configs=[PlatePopulatorAgentConfig(thickness=sheeting_inside)]))
        layer_defs.append(LayerDefinition(None, name="frame", is_framing_layer=True, agent_configs=frame_agent_configs))
        if sheeting_outside:
            layer_defs.append(LayerDefinition(sheeting_outside, name="exterior", agent_configs=[PlatePopulatorAgentConfig(thickness=sheeting_outside)]))

        config = cls(panel=panel, layer_defs=layer_defs, default_feature_configs=default_feature_configs, orientation=orientation)
        config.standard_beam_width = standard_beam_width
        config.stud_spacing = stud_spacing
        config.standard_beam_width_increment = standard_beam_width_increment
        config.edge_beam_min_width = edge_beam_min_width
        config.lintel_posts = lintel_posts
        config.split_bottom_plate_beam = split_bottom_plate_beam
        config.beam_width_overrides = beam_width_overrides
        config.joint_rule_overrides = joint_rule_overrides
        config.sheeting_inside = sheeting_inside
        config.sheeting_outside = sheeting_outside
        return config

    @classmethod
    def recess_panel(
        cls,
        panel=None,
        standard_beam_width=None,
        recess_beam_width=None,
        recess_beam_height=None,
        edge_beam_min_width=None,
        standard_beam_width_increment=None,
        sheeting_outside=0,
        sheeting_inside=0,
        sheeting_recess=0,
        beam_width_overrides=None,
        joint_rule_overrides=None,
        default_feature_configs=None,
    ):
        """Create a config for a recess panel populator.

        Parameters
        ----------
        standard_beam_width : float, optional
            Default beam width.
        recess_beam_width : float, optional
            Width of the recess beam.
        recess_beam_height : float, optional
            Height of the recess beam.
        edge_beam_min_width : float, optional
            Minimum width for edge beams.
        standard_beam_width_increment : float, optional
            Rounding increment for edge-beam widths.
        sheeting_outside : float, optional
            Thickness of external sheathing plate.
        sheeting_inside : float, optional
            Thickness of internal sheathing plate.
        sheeting_recess : float, optional
            Thickness of the sheeting plate in the recess.
        beam_width_overrides : dict, optional
            Per-category width overrides.
        joint_rule_overrides : list, optional
            Rules that replace matching entries in any agent's ``INTERNAL_RULES`` list.
        default_feature_configs : dict, optional
            Mapping from panel feature class to a ``PopulatorAgentConfig`` instance.
        """
        layer_defs = []
        if sheeting_inside:
            layer_defs.append(LayerDefinition(sheeting_inside, name="interior"))
        layer_defs.append(LayerDefinition(None, name="frame", is_framing_layer=True))
        if sheeting_outside:
            layer_defs.append(LayerDefinition(sheeting_outside, name="exterior"))

        config = cls(panel=panel, layer_defs=layer_defs, default_feature_configs=default_feature_configs)
        config.standard_beam_width = standard_beam_width or (panel.thickness / 2 if panel else None)
        config.recess_beam_width = recess_beam_width or standard_beam_width
        config.recess_beam_height = recess_beam_height or standard_beam_width
        config.edge_beam_min_width = edge_beam_min_width
        config.standard_beam_width_increment = standard_beam_width_increment
        config.sheeting_recess = sheeting_recess
        config.sheeting_inside = sheeting_inside
        config.sheeting_outside = sheeting_outside
        config.beam_width_overrides = beam_width_overrides or {}
        config.joint_rule_overrides = joint_rule_overrides or []
        config._agents_factory = _recess_agents_factory
        return config

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _flat_layer_defs(self, layer_defs):
        """Yield leaf-level :class:`LayerDefinition` objects (depth-first)."""
        for ld in layer_defs:
            if ld.sublayers:
                yield from self._flat_layer_defs(ld.sublayers)
            else:
                yield ld

    def _get_inside_sheeting_thickness(self):
        """Return the total thickness of non-framing layers before the first framing layer."""
        si = 0.0
        for ld in self._flat_layer_defs(self.layer_defs):
            if ld.is_framing_layer:
                break
            if ld.thickness is not None:
                si += ld.thickness
        return si

    def _get_outside_sheeting_thickness(self):
        """Return the total thickness of non-framing layers after the last framing layer."""
        so = 0.0
        in_frame = False
        for ld in self._flat_layer_defs(self.layer_defs):
            if ld.is_framing_layer:
                in_frame = True
                so = 0.0  # reset; layers after the frame zone count as outside
            elif in_frame:
                if ld.thickness is not None:
                    so += ld.thickness
        return so

    def resolve_beam_dimensions(self, agents):
        """Populate :attr:`~timber_design.populators.PopulatorAgent.beam_dimensions` on every agent.

        Uses ``agent.layer.thickness`` as the beam height when available,
        falling back to ``agent.panel.thickness``.
        """
        for agent in agents:
            if agent.layer is not None:
                thickness = agent.layer.thickness
            elif agent.panel is not None:
                thickness = agent.panel.thickness
            else:
                thickness = 0.0
            agent.resolve_beam_dimensions(self.standard_beam_width, thickness)

    @staticmethod
    def _find_definition_for_feature(feature, definitions):
        """Return the most specific config for *feature* using MRO-based lookup.

        Walks ``type(feature).__mro__`` from most to least specific, returning
        the first entry found in *definitions*.

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
        # translation_to_frame_center = self._get_translation_to_frame_center(panel)
        return  transformation_to_populator_panel

    def _get_transformation_to_populator_panel(self, panel, orientation):
        """Return the transformation that aligns *panel* to the XY plane."""
        stud_dir_frame = Frame(Point(0, 0, 0), cross_vectors(orientation, Vector(0, 0, 1)), orientation)
        transform_to_stud_dir_frame = Transformation.from_frame(stud_dir_frame).inverse()
        pts = [pt.transformed(transform_to_stud_dir_frame) for pt in panel.plate_geometry.outline_a.points + panel.plate_geometry.outline_b.points]
        min_pt = Box.from_points(pts).points[0]
        obb_frame = Frame(min_pt, Vector(1, 0, 0), Vector(0, 1, 0)).transformed(transform_to_stud_dir_frame.inverse())
        return Transformation.from_frame(obb_frame).inverse()

    def _get_translation_to_frame_center(self, panel):
        """Return a Z-translation that centers the coordinate origin on the frame layer.

        Reads ``layer_defs`` to determine the inside/outside sheeting thicknesses.
        Falls back to ``sheeting_inside`` / ``sheeting_outside`` attrs when
        ``layer_defs`` is empty (backward-compat path for plain configs).
        """
        if self.layer_defs:
            si = self._get_inside_sheeting_thickness()
            so = self._get_outside_sheeting_thickness()
        else:
            si = getattr(self, "sheeting_inside", 0.0) or 0.0
            so = getattr(self, "sheeting_outside", 0.0) or 0.0
        frame_thickness = panel.thickness - si - so
        return Translation.from_vector(-Vector(0, 0, si + frame_thickness / 2))


# =============================================================================
# Agent factories for alternate constructors
# =============================================================================


def _recess_agents_factory(config, layers):
    """Agent factory used by :meth:`PanelPopulatorConfig.recess_panel`.

    Instantiates an :class:`~timber_design.populators.EdgePopulatorAgent` and
    passes it directly to :class:`~timber_design.populators.RecessPopulatorAgent`
    so the recess beams share the same outline as the edge beams.
    """
    from timber_design.populators.populator_agents.edge_populator_agent import EdgePopulatorAgent
    from timber_design.populators.populator_agents.edge_populator_agent import EdgePopulatorAgentConfig
    from timber_design.populators.populator_agents.recess_populator_agent import RecessPopulatorAgent
    from timber_design.populators.populator_agents.recess_populator_agent import RecessPopulatorAgentConfig

    frame_layer = layers["frame"]
    frame_panel = frame_layer.panel
    edge_agent = EdgePopulatorAgent(
        frame_panel,
        EdgePopulatorAgentConfig(
            standard_beam_width_increment=config.standard_beam_width_increment,
            edge_beam_min_width=config.edge_beam_min_width or config.standard_beam_width,
            beam_width_overrides=config.beam_width_overrides,
            joint_rule_overrides=config.joint_rule_overrides,
            layer=frame_layer,
        ),
    )
    agents: List["PopulatorAgent"] = [edge_agent]
    agents.append(
        RecessPopulatorAgent(
            frame_panel,
            edge_agent,
            RecessPopulatorAgentConfig(
                recess_beam_width=config.recess_beam_width,
                recess_beam_height=config.recess_beam_height,
                sheeting_recess=config.sheeting_inside,
                beam_width_overrides=config.beam_width_overrides,
                joint_rule_overrides=config.joint_rule_overrides,
                layer=frame_layer,
            ),
        )
    )

    if "interior" in layers or "exterior" in layers:
        from timber_design.populators.populator_agents.plate_populator_agent import PlatePopulatorAgent
        from timber_design.populators.populator_agents.plate_populator_agent import PlatePopulatorAgentConfig

        if "interior" in layers:
            agents.append(PlatePopulatorAgent(layers["interior"], PlatePopulatorAgentConfig(thickness=config.sheeting_inside)))
        if "exterior" in layers:
            agents.append(PlatePopulatorAgent(layers["exterior"], PlatePopulatorAgentConfig(thickness=config.sheeting_outside)))

    return agents
