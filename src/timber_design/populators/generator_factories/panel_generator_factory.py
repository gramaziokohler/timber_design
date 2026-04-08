from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from typing import TYPE_CHECKING
from typing import List
from typing import Optional
from typing import Union

from compas.geometry import Box
from compas.geometry import Frame
from compas.geometry import Point
from compas.geometry import Polyline
from compas.geometry import Transformation
from compas.geometry import Translation
from compas.geometry import Vector
from compas.geometry import cross_vectors
from compas_timber.elements import Panel
from compas_timber.panel_features import PanelFeature

# type-only import to avoid circular imports
if TYPE_CHECKING:
    from timber_design.populators import ElementGenerator
    from timber_design.populators import PanelPopulatorDefinition


class PanelGeneratorFactory(ABC):
    """Abstract factory class for creating element generators.
    The factory takes a panel, a generator parameters object, and an optional list of feature element generators as input and produces one or more
    element generators to populate the panel. Different types of panel element generator factories can be implemented by subclassing this class and
    implementing the `create_generator` method. These subclasses would be used to create specific sets of element generators that populate a specific wall type.
    """

    @classmethod
    @abstractmethod
    def create_generators(cls, element: Union[Panel, PanelFeature], params: "GeneratorFactoryParams", feature_definitions: Optional[List] = None) -> List["ElementGenerator"]:
        """Create element generators for the given panel.

        Parameters
        ----------
        element : :class:`compas_timber.elements.Panel`
            The panel to populate.
        params : :class:`~timber_design.populators.GeneratorFactoryParams`
            Factory-level parameters (includes ``standard_beam_width`` etc.).
        feature_definitions : list[:class:`~timber_design.populators.FeaturePopulatorDefinition`], optional
            Additional feature generators to append. Their features must already be
            transformed into the populator's local coordinate space by the caller.

        Returns
        -------
        list[:class:`~timber_design.populators.ElementGenerator`]
        """
        pass

    @staticmethod
    def create_local_panel(panel_definition: "PanelPopulatorDefinition") -> tuple:
        """Transform the panel into the populator's local coordinate space.

        Returns
        -------
        tuple[:class:`compas.geometry.Transformation`, :class:`compas_timber.elements.Panel`]
            The transformation to populator space and the transformed local panel.
        """
        transformation_to_populator = _get_transformation_to_populator_space(panel_definition)
        polylines = panel_definition.panel.plate_geometry.outline_a, panel_definition.panel.plate_geometry.outline_b
        local_polylines = [pl.transformed(transformation_to_populator) for pl in polylines]
        box = Box.from_points([pt for pl in local_polylines for pt in pl.points])
        local_panel = Panel(Frame.worldXY(), box.xsize, box.ysize, box.zsize, local_polylines[0], local_polylines[1])
        return transformation_to_populator, local_panel


class GeneratorFactoryParams(ABC):
    """Base class for generator factory parameters."""

    pass


def get_frame_panel(panel: Panel, params: GeneratorFactoryParams) -> Panel:
    """Handles the sheeting offsets for the panel outlines."""
    """This method creates a panel that represents the original panel frame without sheeting."""

    si = getattr(params, "sheeting_inside", 0)
    if not si:
        frame_outline_a = panel.outline_a
    else:
        offset_inside = si / panel.thickness
        pts_inside = []
        for pt_a, pt_b in zip(panel.outline_a.points, panel.outline_b.points):
            pt = pt_a * (1 - offset_inside) + pt_b * offset_inside
            pts_inside.append(pt)
        frame_outline_a = Polyline(pts_inside)

    so = getattr(params, "sheeting_outside", 0)
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


# =============================================================================
# Populator-space helpers (used by PanelGeneratorFactory.create_local_panel)
# =============================================================================


def _get_transformation_to_populator_space(panel_definition):
    # type: (PanelPopulatorDefinition) -> Transformation
    """Return the transformation from world/panel space into the populator's local XY space."""
    transformation_to_populator_panel = _get_transformation_to_populator_panel(panel_definition.panel, panel_definition.orientation)
    translation_to_frame_center = _get_translation_to_frame_center(panel_definition.panel, panel_definition.params)
    return translation_to_frame_center * transformation_to_populator_panel


def _get_transformation_to_populator_panel(panel, stud_direction):
    # type: (Panel, Vector) -> Transformation
    stud_dir_frame = Frame(Point(0, 0, 0), cross_vectors(stud_direction, Vector(0, 0, 1)), stud_direction)
    transform_to_stud_dir_frame = Transformation.from_frame(stud_dir_frame).inverse()
    pts = [pt.transformed(transform_to_stud_dir_frame) for pt in panel.plate_geometry.outline_a.points + panel.plate_geometry.outline_b.points]
    min_pt = Box.from_points(pts).points[0]
    obb_frame = Frame(min_pt, Vector(1, 0, 0), Vector(0, 1, 0)).transformed(transform_to_stud_dir_frame.inverse())
    return Transformation.from_frame(obb_frame).inverse()


def _get_translation_to_frame_center(panel, params):
    # type: (Panel, GeneratorFactoryParams) -> Translation
    si = getattr(params, "sheeting_inside", 0) or 0.0
    so = getattr(params, "sheeting_outside", 0) or 0.0
    frame_thickness = panel.thickness - si - so
    return Translation.from_vector(-Vector(0, 0, si + frame_thickness / 2))
