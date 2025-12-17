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
from timber_design.populators import PanelEdgeElementGeneratorA
from timber_design.populators import RecessElementGenerator
from timber_design.populators import PanelPlateElementGeneratorA

from .panel_generator_factory import PanelGeneratorFactory
from .panel_generator_factory import GeneratorFactoryParams
from .panel_generator_factory import get_transformation_to_populator_space
from .panel_generator_factory import get_frame_panel
from timber_design.workflow import CategoryRule



class RecessPanelGeneratorFactoryParams(GeneratorFactoryParams):
    """Parameters for creating a panel element generator.
    Parameters
    ----------
    stud_direction : :class:`compas.geometry.Vector`, optional
        The direction of the studs in the panel.
    standard_beam_width : float, optional
        The standard beam width for the panel elements.
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


class RecessPanelGeneratorFactory(PanelGeneratorFactory):
    """Factory for creating stud panel element generators."""
    @classmethod
    def create_generators(cls, populator_panel:Panel, params: RecessPanelGeneratorFactoryParams,  feature_generators: list[ElementGenerator]|None=None) -> list[ElementGenerator]:
        """Create a stud panel element generator.
        Parameters
        ----------
        params : :class:`PanelGeneratorParams`
            Parameters for the generator.
        Returns
        -------
        list[:class:`timber_design.element_generators.ElementGenerator`]
            The created element generators.
        """


        frame_panel= get_frame_panel(populator_panel, params)

        generators = []
        generators.append(PanelEdgeElementGeneratorA(
            frame_panel,
            standard_beam_width=params.standard_beam_width,
            standard_beam_width_increment=params.standard_beam_width_increment,
            edge_beam_min_width=params.edge_beam_min_width,
            beam_width_overrides=params.beam_width_overrides,
            joint_rule_overrides=params.joint_rule_overrides,
            ))
        generators.append(RecessElementGenerator(
            frame_panel,
            edge_generator=generators[0],
            recess_beam_width=params.recess_beam_width,
            recess_beam_height=params.recess_beam_height,
            sheeting_inside=params.sheeting_inside,
            standard_beam_width=params.standard_beam_width,
            beam_width_overrides=params.beam_width_overrides,
            joint_rule_overrides=params.joint_rule_overrides,
            ))

        if params.sheeting_inside or params.sheeting_outside:
            generators.append(PanelPlateElementGeneratorA(populator_panel, frame_panel, sheeting_outside=params.sheeting_outside, sheeting_inside=params.sheeting_inside))

        if feature_generators:
            generators.extend(feature_generators)

        for generator in generators:
            generator.update_beam_dimensions(frame_panel.thickness)

        return generators
