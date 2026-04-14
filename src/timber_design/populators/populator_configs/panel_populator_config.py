from __future__ import annotations

from abc import ABC
from abc import abstractmethod
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

from timber_design.populators.populator import PanelPopulator

if TYPE_CHECKING:
    pass


class PanelPopulatorConfig(ABC):
    """Abstract base config for creating panel populator agents.

    Combines configuration data (previously in ``PopulatorFactoryParams``) and
    factory behaviour (previously in ``PanelPopulatorFactory``) into a single class.

    Parameters
    ----------
    default_feature_configs : dict[type, PopulatorAgentConfig], optional
        Mapping from feature type to a :class:`~timber_design.populators.PopulatorAgentConfig`
        instance (without feature set).  Applied using MRO-based lookup: the most specific
        matching key wins.  Instance-level definitions passed directly to
        :meth:`create_populator` always take precedence.
    """

    def __init__(self, panel=None, default_feature_configs=None):
        self.panel = panel
        self.default_feature_configs = {c.FEATURE_TYPE: c for c in default_feature_configs} if default_feature_configs else {}

    @abstractmethod
    def create_populator_agents(self, panel) -> tuple:
        """Create populator agents for the given panel.

        Parameters
        ----------
        panel : :class:`compas_timber.elements.Panel`
            The local (populator-space) panel to create agents for.

        Returns
        -------
        tuple[list, :class:`compas_timber.elements.Panel`]
            The list of agents and the frame panel (panel minus sheeting offsets).
            ``resolve_beam_dimensions`` must NOT be called here; :meth:`create_populator`
            calls it on every agent after all agents are assembled.
        """
        pass

    def create_populator_from_panel(self, panel, feature_configs=None):
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
        if panel is None:
            raise ValueError("No panel provided.")
        transformation_to_populator, local_panel = self._create_local_panel(panel)
        agents, frame_panel = self.create_populator_agents(local_panel)

        # Collect IDs of features that have explicit instance-level definitions
        feature_configs = feature_configs or []
        explicitly_defined_features = set(f.feature for f in feature_configs)

        for feature in panel.features:
            if feature in explicitly_defined_features:
                continue
            agent_config = _find_definition_for_feature(feature, self.default_feature_configs)
            if agent_config is not None:
                transformed_feature = feature.transformed(transformation_to_populator)
                agents.append(agent_config.get_agent_from_feature(transformed_feature))

        for f_def in feature_configs:
            transformed_feature = f_def.feature.transformed(transformation_to_populator)
            agents.append(f_def.get_agent_from_feature(transformed_feature))

        standard_beam_width = getattr(self, "standard_beam_width", 0.0)
        for agent in agents:
            agent.resolve_beam_dimensions(frame_panel.thickness, standard_beam_width)

        return PanelPopulator(
            local_panel,
            agents,
            original_panel=panel,
            transformation_to_populator=transformation_to_populator,
        )

    def create_populator(self, feature_configs=None):
        """Create a populator for the given panel.

        Parameters
        ----------
        panel : :class:`compas_timber.elements.Panel`, optional
            The panel to populate.  Falls back to ``self.panel`` if not given.
        feature_configs : list[PopulatorAgentConfig], optional
            Per-instance agent configs with ``feature`` set.
        """
        return self.create_populator_from_panel(self.panel, feature_configs=feature_configs)

    def _create_local_panel(self, panel) -> tuple:
        """Transform the panel into the populator's local coordinate space.

        Returns
        -------
        tuple[:class:`compas.geometry.Transformation`, :class:`compas_timber.elements.Panel`]
            The transformation to populator space and the transformed local panel.
        """
        orientation = self._get_projected_orientation(panel)
        transformation_to_populator = _get_transformation_to_populator_space(panel, orientation, self)
        polylines = panel.plate_geometry.outline_a, panel.plate_geometry.outline_b
        local_polylines = [pl.transformed(transformation_to_populator) for pl in polylines]
        box = Box.from_points([pt for pl in local_polylines for pt in pl.points])
        local_panel = Panel(Frame.worldXY(), box.xsize, box.ysize, box.zsize, local_polylines[0], local_polylines[1])
        return transformation_to_populator, local_panel

    def _get_projected_orientation(self, panel) -> Vector:
        """Project ``self.stud_direction`` onto the panel plane.

        Returns ``Vector(0, 1, 0)`` if no stud_direction is set or if it is
        perpendicular to the panel normal.
        """
        stud_direction = getattr(self, "stud_direction", None)
        if not stud_direction:
            return Vector(0, 1, 0)
        perp = cross_vectors(panel.normal, stud_direction)
        if all(TOL.is_zero(perp[i]) for i in range(3)):
            return Vector(0, 1, 0)
        return Vector(*cross_vectors(perp, panel.normal)).transformed(panel.transformation_to_local())


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


def get_frame_panel(panel: Panel, config) -> Panel:
    """Create a panel representing the original panel frame without sheeting.

    Parameters
    ----------
    panel : :class:`compas_timber.elements.Panel`
        The panel to create the frame panel for.
    config : object
        Config object with optional ``sheeting_inside`` and ``sheeting_outside`` attributes.

    Returns
    -------
    :class:`compas_timber.elements.Panel`
    """
    si = getattr(config, "sheeting_inside", 0)
    if not si:
        frame_outline_a = panel.outline_a
    else:
        offset_inside = si / panel.thickness
        pts_inside = []
        for pt_a, pt_b in zip(panel.outline_a.points, panel.outline_b.points):
            pt = pt_a * (1 - offset_inside) + pt_b * offset_inside
            pts_inside.append(pt)
        frame_outline_a = Polyline(pts_inside)

    so = getattr(config, "sheeting_outside", 0)
    if not so:
        frame_outline_b = panel.outline_b
    else:
        offset_outside = so / panel.thickness
        pts_outside = []
        for pt_a, pt_b in zip(panel.outline_a.points, panel.outline_b.points):
            pts_outside.append(pt_a * offset_outside + pt_b * (1 - offset_outside))
        frame_outline_b = Polyline(pts_outside)

    box = Box.from_points([pt for pt in frame_outline_a.points + frame_outline_b.points])
    frame_panel = Panel(Frame.worldXY(), box.xsize, box.ysize, box.zsize, frame_outline_a, frame_outline_b)
    return frame_panel


def _get_transformation_to_populator_space(panel, orientation, config):
    # type: (Panel, Vector, object) -> Transformation
    """Return the transformation from world/panel space into the populator's local XY space."""
    transformation_to_populator_panel = _get_transformation_to_populator_panel(panel, orientation)
    translation_to_frame_center = _get_translation_to_frame_center(panel, config)
    return translation_to_frame_center * transformation_to_populator_panel


def _get_transformation_to_populator_panel(panel, stud_direction):
    # type: (Panel, Vector) -> Transformation
    stud_dir_frame = Frame(Point(0, 0, 0), cross_vectors(stud_direction, Vector(0, 0, 1)), stud_direction)
    transform_to_stud_dir_frame = Transformation.from_frame(stud_dir_frame).inverse()
    pts = [pt.transformed(transform_to_stud_dir_frame) for pt in panel.plate_geometry.outline_a.points + panel.plate_geometry.outline_b.points]
    min_pt = Box.from_points(pts).points[0]
    obb_frame = Frame(min_pt, Vector(1, 0, 0), Vector(0, 1, 0)).transformed(transform_to_stud_dir_frame.inverse())
    return Transformation.from_frame(obb_frame).inverse()


def _get_translation_to_frame_center(panel, config):
    # type: (Panel, object) -> Translation
    si = getattr(config, "sheeting_inside", 0) or 0.0
    so = getattr(config, "sheeting_outside", 0) or 0.0
    frame_thickness = panel.thickness - si - so
    return Translation.from_vector(-Vector(0, 0, si + frame_thickness / 2))
