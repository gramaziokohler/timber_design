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

from compas_timber.elements import Slab

from timber_design.populators import ElementGenerator
from timber_design.workflow import CategoryRule


class SlabGeneratorFactory(ABC):
    """Abstract factory class for creating element generators."""
    @classmethod
    @abstractmethod
    def create_generators(cls, slab:Slab, params: GeneratorFactoryParams, feature_generators:list[ElementGenerator]|None=None) ->  list[ElementGenerator]:
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
    def create_local_data(cls, slab:Slab, params: GeneratorFactoryParams, feature_generators:list[ElementGenerator]|None = None) -> tuple[Slab, Transformation, list[ElementGenerator]]:
        """Create a local slab for the generator.
        Parameters
        ----------
        params
            Keyword arguments for the generator.
        Returns
        -------
        :class:`compas_timber.elements.Slab`
            The created local slab.
        """
        transformation_slab_to_populator = get_transformation_to_populator_space(slab, params)

        outline_a = slab.local_outlines[0].transformed(transformation_slab_to_populator)
        outline_b = slab.local_outlines[1].transformed(transformation_slab_to_populator)
        local_slab = Slab.from_outlines(outline_a, outline_b)

        generator_features= [f.feature for f in feature_generators] if feature_generators else [] 
        unmatched_features=[]
        for feature in slab.features:
            if feature not in generator_features:
                local_slab.add_feature(feature.transformed(transformation_slab_to_populator))
        for generator in feature_generators or []:
            generator.feature = generator.feature.transformed(transformation_slab_to_populator)
        return local_slab, transformation_slab_to_populator, feature_generators or []


class GeneratorFactoryParams(ABC):
    """Base class for generator factory parameters."""
    pass


def get_transformation_to_populator_space(slab:Slab, params:GeneratorFactoryParams)->Transformation:
    """The slab_populator frame in global space."""
    stud_dir = getattr(params, "stud_direction", Vector(0, 1, 0))

    stud_dir.transform(slab.transformation.inverse())  # bring stud direction into local slab space
    if angle_vectors(stud_dir, Vector(0, 0, 1)) < 1e-3 or angle_vectors(stud_dir, Vector(0, 0, -1)) < 1e-3:
        stud_dir = Vector(0, 1, 0)
    else:
        stud_dir[2] = 0.0 # project stud direction onto XY plane

    frame = Frame(Point(0, 0, 0), cross_vectors(stud_dir, Vector(0, 0, 1)), stud_dir)  # get frame with stud direction as y axis
    transform_to_sp = Transformation.from_frame(frame).inverse()
    rebased_pts = [pt.transformed(transform_to_sp) for pt in slab.local_outlines[0].points + slab.local_outlines[1].points]  # rebase slab points into stud direction frame
    min_pt = bounding_box_xy(rebased_pts)[0]
    frame = Frame(min_pt, Vector(1, 0, 0), Vector(0, 1, 0)).transformed(transform_to_sp.inverse())

    si = getattr(params, "sheeting_inside", 0)
    so = getattr(params, "sheeting_outside", 0)
    frame_thickness = slab.thickness - si - so 
    frame.point[2] = si + frame_thickness / 2  # offset to make frame center plane at world XY
    return Transformation.from_frame(frame).inverse()

def get_frame_slab(slab, params):
    """Handles the sheeting offsets for the slab outlines."""
    """This method creates new outlines for the beam frame based on the sheeting thicknesses."""

    if not params.sheeting_inside:
        frame_outline_a = slab.outline_a
    else:
        offset_inside = params.sheeting_inside / slab.thickness
        pts_inside = []
        for pt_a, pt_b in zip(slab.outline_a.points, slab.outline_b.points):
            pt = pt_a * (1 - offset_inside) + pt_b * offset_inside
            pts_inside.append(pt)
        frame_outline_a = Polyline(pts_inside)

    if not params.sheeting_outside:
        frame_outline_b = slab.outline_b
    else:
        offset_outside = params.sheeting_outside / slab.thickness
        pts_outside = []
        for pt_a, pt_b in zip(slab.outline_a.points, slab.outline_b.points):
            pts_outside.append(pt_a * offset_outside + pt_b * (1 - offset_outside))

        frame_outline_b = Polyline(pts_outside)
    return Slab.from_outlines(frame_outline_a, frame_outline_b)
