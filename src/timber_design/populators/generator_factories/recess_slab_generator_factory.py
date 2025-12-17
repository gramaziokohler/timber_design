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
from timber_design.populators import SlabEdgeElementGeneratorA
from timber_design.populators import RecessElementGenerator
from timber_design.populators import SlabPlateElementGeneratorA

from .slab_generator_factory import SlabGeneratorFactory
from .slab_generator_factory import GeneratorFactoryParams
from .slab_generator_factory import get_transformation_to_populator_space
from .slab_generator_factory import get_frame_slab
from timber_design.workflow import CategoryRule



class RecessSlabGeneratorFactoryParams(GeneratorFactoryParams):
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
        standard_beam_width:float,
        recess_beam_width:float,
        recess_beam_height:float,
        edge_beam_min_width:float,
        standard_beam_width_increment:float|None=None,
        sheeting_outside:float=0,
        sheeting_inside:float=0,
        beam_width_overrides:dict|None=None,
        joint_rule_overrides:list[CategoryRule]|None=None,
    ):
        self.standard_beam_width = standard_beam_width
        self.recess_beam_width = recess_beam_width
        self.recess_beam_height = recess_beam_height
        self.edge_beam_min_width = edge_beam_min_width
        self.standard_beam_width_increment = standard_beam_width_increment
        self.sheeting_outside = sheeting_outside
        self.sheeting_inside = sheeting_inside
        self.beam_width_overrides = beam_width_overrides or {}
        self.joint_rule_overrides = joint_rule_overrides or []


class RecessSlabGeneratorFactory(SlabGeneratorFactory):
    """Factory for creating stud slab element generators."""
    @classmethod
    def create_generators(cls, populator_slab:Slab, params: RecessSlabGeneratorFactoryParams,  feature_generators: list[ElementGenerator]|None=None) -> list[ElementGenerator]:
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
        generators.append(RecessElementGenerator(
            frame_slab,
            edge_generator=generators[0],
            recess_beam_width=params.recess_beam_width,
            recess_beam_height=params.recess_beam_height,
            sheeting_inside=params.sheeting_inside,
            standard_beam_width=params.standard_beam_width,
            beam_width_overrides=params.beam_width_overrides,
            joint_rule_overrides=params.joint_rule_overrides,
            ))

        if params.sheeting_inside or params.sheeting_outside:
            generators.append(SlabPlateElementGeneratorA(populator_slab, frame_slab, sheeting_outside=params.sheeting_outside, sheeting_inside=params.sheeting_inside))

        if feature_generators:
            generators.extend(feature_generators)

        for generator in generators:
            generator.update_beam_dimensions(frame_slab.thickness)

        return generators
