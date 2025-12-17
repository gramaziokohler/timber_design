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
from compas_timber.elements import Opening

from timber_design.populators import ElementGenerator
from timber_design.populators import OpeningElementGenerator
from timber_design.populators import SlabEdgeElementGeneratorA
from timber_design.populators import SlabStudElementGeneratorA
from timber_design.populators import SlabPlateElementGeneratorA


from timber_design.workflow import CategoryRule
from .slab_generator_factory import SlabGeneratorFactory
from .slab_generator_factory import GeneratorFactoryParams
from .slab_generator_factory import get_transformation_to_populator_space
from .slab_generator_factory import get_frame_slab



class StudSlabGeneratorFactoryParams(GeneratorFactoryParams):
    """Parameters for creating a slab element generator.
    Parameters
    ----------
    stud_direction : :class:`compas.geometry.Vector`, optional
        The direction of the studs in the slab.
    standard_beam_width : float, optional
        The standard beam width for the slab elements.
    edge_generator : :class:`timber_design.element_generators.ElementGenerator`, optional
        The edge element generator.
    stud_generator : :class:`timber_design.element_generators.ElementGenerator`, optional
        The stud element generator.
    plate_generator : :class:`timber_design.element_generators.ElementGenerator`, optional
        The plate element generator.
    beam_width_overrides : dict, optional
        A dictionary of beam width overrides for specific beam categories.
        key = beam category name, value = beam width.
    joint_rule_overrides : list[:class:`compas_timber.design.CategoryRule`], optional
        A list of category rules to override the default ones.
    """
    def __init__(
        self,
        standard_beam_width: float,
        stud_spacing:float|None=None,
        standard_beam_width_increment:float|None=None,
        edge_beam_min_width:float|None=None,
        stud_direction:Vector|None=None,
        sheeting_outside:float=0,
        sheeting_inside:float=0,
        lintel_posts: bool = False,
        split_bottom_plate_beam: bool = False,
        beam_width_overrides:dict|None=None,
        joint_rule_overrides:list[CategoryRule]|None=None,
    ):
        self.standard_beam_width = standard_beam_width
        self.stud_spacing = stud_spacing
        self.standard_beam_width_increment = standard_beam_width_increment
        self.edge_beam_min_width = edge_beam_min_width
        self.stud_direction = stud_direction
        self.sheeting_outside = sheeting_outside
        self.sheeting_inside = sheeting_inside
        self.lintel_posts = lintel_posts
        self.split_bottom_plate_beam = split_bottom_plate_beam
        self.beam_width_overrides = beam_width_overrides
        self.joint_rule_overrides = joint_rule_overrides


class StudSlabGeneratorFactory(SlabGeneratorFactory):
    """Factory for creating stud slab element generators."""
    @classmethod
    def create_generators(cls, populator_slab:Slab, params: StudSlabGeneratorFactoryParams, feature_generators:list[ElementGenerator]|None=None) ->  list[ElementGenerator]:
        """Create a stud slab element generator.
        Parameters
        ----------
        params : :class:`SlabGeneratorParams`
            Parameters for the generator.
        Returns
        -------
        list[:class:`timber_design.element_generators.ElementGenerator`]
            The created element generators.
        """

        frame_slab= get_frame_slab(populator_slab, params)

        generators = []
        generators.append(SlabEdgeElementGeneratorA(
            frame_slab,
            standard_beam_width=params.standard_beam_width,
            standard_beam_width_increment=params.standard_beam_width_increment,
            edge_beam_min_width=params.edge_beam_min_width,
            beam_width_overrides=params.beam_width_overrides,
            joint_rule_overrides=params.joint_rule_overrides,
            ))

        if params.stud_spacing:
            generators.append(SlabStudElementGeneratorA(
                frame_slab, stud_spacing=params.stud_spacing, standard_beam_width=params.standard_beam_width, beam_width_overrides=params.beam_width_overrides, joint_rule_overrides=params.joint_rule_overrides
                ))

        if params.sheeting_inside or params.sheeting_outside:
            generators.append(SlabPlateElementGeneratorA(populator_slab, frame_slab, sheeting_outside=params.sheeting_outside, sheeting_inside=params.sheeting_inside))

        for feature in populator_slab.features:
            if isinstance(feature, Opening):
                generators.append(OpeningElementGenerator(feature, params.standard_beam_width, params.lintel_posts, params.beam_width_overrides, params.joint_rule_overrides, params.split_bottom_plate_beam))

        if feature_generators:
            generators.extend(feature_generators)

        for generator in generators:
            generator.update_beam_dimensions(frame_slab.thickness)


        return generators

