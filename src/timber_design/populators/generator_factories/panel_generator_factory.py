from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from typing import TYPE_CHECKING
from typing import List
from typing import Union

from compas.geometry import Frame
from compas.geometry import Point
from compas.geometry import Polyline
from compas.geometry import Transformation
from compas.geometry import Vector
from compas.geometry import angle_vectors
from compas.geometry import bounding_box_xy
from compas.geometry import cross_vectors
from compas_timber.elements import Panel

# type-only import to avoid circular imports
if TYPE_CHECKING:
    from timber_design.populators import ElementGenerator
    from timber_design.populators import GeneratorFactoryParams


class PanelGeneratorFactory(ABC):
    """Abstract factory class for creating element generators.
    The factory takes a panel, a generator parameters object, and an optional list of feature element generators as input and produces one or more element generators to populate the panel.
    different types of panel element generator factories can be implemented by subclassing this class and implementing the `create_generator` method.
    these subclasses would be used to create specific sets of element generators that populate a specific wall type.
    """

    @classmethod
    @abstractmethod
    def create_generators(cls, panel: Panel, params: GeneratorFactoryParams, feature_generators: Union[List[ElementGenerator], None] = None) -> List[ElementGenerator]:
        """Create an element generator.
        Parameters
        ----------
        params
            Keyword arguments for the generator.
        Returns
        -------
        :class:`timber_design.element_generators.ElementGenerator`
            The created element generator.
        """
        pass

    @classmethod
    def create_local_data(
        cls, panel: Panel, params: GeneratorFactoryParams, feature_generators: Union[List[ElementGenerator], None] = None
    ) -> tuple[Panel, Transformation, List[ElementGenerator]]:
        """Create a local panel for the generator.
        Parameters
        ----------
        panel : :class:`compas_timber.elements.Panel`
            The panel to be populated.
        params : :class:`timber_design.populators.GeneratorFactoryParams`
                Keyword arguments for the generator.
        feature_generators : list[:class:`timber_design.populators.ElementGenerator`], optional
            A list of feature generators to consider when populating the panel.
        Returns
        -------
        tuple[:class:`compas_timber.elements.Panel`, :class:`compas.geometry.Transformation`, list[:class:`timber_design.populators.ElementGenerator`]]
            The local panel, the transformation to the populator space, and the updated feature generators.
        """
        transformation_to_populator = _get_transformation_to_populator_space(panel, params)
        local_panel = panel.copy()
        local_panel.transformation = transformation_to_populator

        return local_panel, transformation_to_populator, feature_generators or []


class GeneratorFactoryParams(ABC):
    """Base class for generator factory parameters."""

    pass


def _get_transformation_to_populator_space(panel: Panel, params: GeneratorFactoryParams) -> Transformation:
    """The Transformation from panel space to slab populator space."""
    stud_dir = getattr(params, "stud_direction", Vector(0, 1, 0))
    if not panel.transformation:
        raise ValueError("Panel transformation is not defined. The panel must belong to a model")
    stud_dir = stud_dir.transformed(panel.transformation_to_local)  # bring stud direction into local panel space
    if angle_vectors(stud_dir, Vector(0, 0, 1)) < 1e-3 or angle_vectors(stud_dir, Vector(0, 0, -1)) < 1e-3:
        stud_dir = Vector(0, 1, 0)
    else:
        stud_dir[2] = 0.0  # project stud direction onto XY plane

    frame = Frame(Point(0, 0, 0), cross_vectors(stud_dir, Vector(0, 0, 1)), stud_dir)  # get frame with stud direction as y axis
    transform_to_sp = Transformation.from_frame(frame).inverse()
    min_pt = panel.plate_geometry.compute_aabb().points[0]
    frame = Frame(min_pt, Vector(1, 0, 0), Vector(0, 1, 0)).transformed(transform_to_sp.inverse())

    si = getattr(params, "sheeting_inside", 0)
    so = getattr(params, "sheeting_outside", 0)
    frame_thickness = panel.thickness - si - so
    frame.point[2] = si + frame_thickness / 2  # offset to make frame center plane at world XY
    return Transformation.from_frame(frame).inverse()


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
    return Panel.from_outlines(frame_outline_a, frame_outline_b)
