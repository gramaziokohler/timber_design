from __future__ import annotations
from abc import ABC, abstractmethod

from compas.data import Data
from compas.geometry import Frame
from compas.geometry import Point
from compas.geometry import Transformation
from compas.geometry import Vector
from compas.geometry import Polyline
from compas.geometry import angle_vectors
from compas.geometry import bounding_box_xy
from compas.geometry import cross_vectors

from compas_timber.elements import Panel

from timber_design.populators import ElementGenerator
from timber_design.workflow import CategoryRule


class PanelGeneratorFactory(ABC):
    """Abstract factory class for creating element generators."""
    @classmethod
    @abstractmethod
    def create_generators(cls, panel:Panel, params: GeneratorFactoryParams, feature_generators:list[ElementGenerator]|None=None) ->  list[ElementGenerator]:
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
    def create_local_data(cls, panel:Panel, params: GeneratorFactoryParams, feature_generators:list[ElementGenerator]|None = None) -> tuple[Panel, Transformation, list[ElementGenerator]]:
        """Create a local panel for the generator.
        Parameters
        ----------
        params
            Keyword arguments for the generator.
        Returns
        -------
        :class:`compas_timber.elements.Panel`
            The created local panel.
        """
        transformation_panel_to_populator = get_transformation_to_populator_space(panel, params)

        outline_a = panel.local_outlines[0].transformed(transformation_panel_to_populator)
        outline_b = panel.local_outlines[1].transformed(transformation_panel_to_populator)
        local_panel = Panel.from_outlines(outline_a, outline_b)

        generator_features= [f.feature for f in feature_generators] if feature_generators else [] 
        unmatched_features=[]
        for feature in panel.features:
            if feature not in generator_features:
                local_panel.add_feature(feature.transformed(transformation_panel_to_populator))
        for generator in feature_generators or []:
            generator.feature = generator.feature.transformed(transformation_panel_to_populator)
        return local_panel, transformation_panel_to_populator, feature_generators or []


class GeneratorFactoryParams(ABC):
    """Base class for generator factory parameters."""
    pass


def get_transformation_to_populator_space(panel:Panel, params:GeneratorFactoryParams)->Transformation:
    """The panel_populator frame in global space."""
    stud_dir = getattr(params, "stud_direction", Vector(0, 1, 0))

    stud_dir.transform(panel.transformation.inverse())  # bring stud direction into local panel space
    if angle_vectors(stud_dir, Vector(0, 0, 1)) < 1e-3 or angle_vectors(stud_dir, Vector(0, 0, -1)) < 1e-3:
        stud_dir = Vector(0, 1, 0)
    else:
        stud_dir[2] = 0.0 # project stud direction onto XY plane

    frame = Frame(Point(0, 0, 0), cross_vectors(stud_dir, Vector(0, 0, 1)), stud_dir)  # get frame with stud direction as y axis
    transform_to_sp = Transformation.from_frame(frame).inverse()
    rebased_pts = [pt.transformed(transform_to_sp) for pt in panel.local_outlines[0].points + panel.local_outlines[1].points]  # rebase panel points into stud direction frame
    min_pt = bounding_box_xy(rebased_pts)[0]
    frame = Frame(min_pt, Vector(1, 0, 0), Vector(0, 1, 0)).transformed(transform_to_sp.inverse())

    si = getattr(params, "sheeting_inside", 0)
    so = getattr(params, "sheeting_outside", 0)
    frame_thickness = panel.thickness - si - so 
    frame.point[2] = si + frame_thickness / 2  # offset to make frame center plane at world XY
    return Transformation.from_frame(frame).inverse()

def get_frame_panel(panel, params):
    """Handles the sheeting offsets for the panel outlines."""
    """This method creates new outlines for the beam frame based on the sheeting thicknesses."""

    if not params.sheeting_inside:
        frame_outline_a = panel.outline_a
    else:
        offset_inside = params.sheeting_inside / panel.thickness
        pts_inside = []
        for pt_a, pt_b in zip(panel.outline_a.points, panel.outline_b.points):
            pt = pt_a * (1 - offset_inside) + pt_b * offset_inside
            pts_inside.append(pt)
        frame_outline_a = Polyline(pts_inside)

    if not params.sheeting_outside:
        frame_outline_b = panel.outline_b
    else:
        offset_outside = params.sheeting_outside / panel.thickness
        pts_outside = []
        for pt_a, pt_b in zip(panel.outline_a.points, panel.outline_b.points):
            pts_outside.append(pt_a * offset_outside + pt_b * (1 - offset_outside))

        frame_outline_b = Polyline(pts_outside)
    return Panel.from_outlines(frame_outline_a, frame_outline_b)
