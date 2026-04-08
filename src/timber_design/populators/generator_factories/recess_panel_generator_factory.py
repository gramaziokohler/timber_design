from __future__ import annotations

from typing import TYPE_CHECKING
from typing import List
from typing import Union

from compas_timber.elements import Panel

# avoid package-level imports that can create circular imports; import generators locally in functions
from timber_design.workflow import CategoryRule

from .panel_generator_factory import GeneratorFactoryParams
from .panel_generator_factory import PanelGeneratorFactory
from .panel_generator_factory import get_frame_panel

if TYPE_CHECKING:
    from timber_design.populators import ElementGenerator


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
        standard_beam_width: float,
        recess_beam_width: float,
        recess_beam_height: float,
        edge_beam_min_width: float,
        standard_beam_width_increment: Union[float, None] = None,
        sheeting_outside: float = 0,
        sheeting_inside: float = 0,
        sheeting_recess: float = 0,
        beam_width_overrides: Union[dict, None] = None,
        joint_rule_overrides: Union[List[CategoryRule], None] = None,
    ):
        self.standard_beam_width = standard_beam_width
        self.recess_beam_width = recess_beam_width
        self.recess_beam_height = recess_beam_height
        self.edge_beam_min_width = edge_beam_min_width
        self.standard_beam_width_increment = standard_beam_width_increment
        self.sheeting_outside = sheeting_outside
        self.sheeting_inside = sheeting_inside
        self.sheeting_recess = sheeting_recess
        self.beam_width_overrides = beam_width_overrides or {}
        self.joint_rule_overrides = joint_rule_overrides or []


class RecessPanelGeneratorFactory(PanelGeneratorFactory):
    """Factory for creating stud panel element generators."""

    @classmethod
    def create_generators(cls, populator_panel: Panel, params: RecessPanelGeneratorFactoryParams, feature_definitions=None) -> List["ElementGenerator"]:
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

        # local imports to avoid circular imports at module import time
        from timber_design.populators.element_generators.edge_element_generator import EdgeElementGenerator
        from timber_design.populators.element_generators.edge_element_generator import EdgeElementGeneratorParams
        from timber_design.populators.element_generators.recess_element_generator import RecessElementGenerator
        from timber_design.populators.element_generators.recess_element_generator import RecessElementGeneratorParams

        frame_panel = get_frame_panel(populator_panel, params)
        edge_generator = EdgeElementGenerator(
            frame_panel,
            EdgeElementGeneratorParams(
                standard_beam_width_increment=params.standard_beam_width_increment,
                edge_beam_min_width=params.edge_beam_min_width or params.standard_beam_width,
                beam_width_overrides=params.beam_width_overrides,
                joint_rule_overrides=params.joint_rule_overrides,
            ),
        )
        generators: List["ElementGenerator"] = [edge_generator]
        generators.append(
            RecessElementGenerator(
                frame_panel,
                edge_generator,
                RecessElementGeneratorParams(
                    recess_beam_width=params.recess_beam_width,
                    recess_beam_height=params.recess_beam_height,
                    sheeting_recess=params.sheeting_inside,
                    beam_width_overrides=params.beam_width_overrides,
                    joint_rule_overrides=params.joint_rule_overrides,
                ),
            )
        )

        if params.sheeting_inside or params.sheeting_outside:
            from timber_design.populators.element_generators.plate_element_generator import PlateElementGenerator
            from timber_design.populators.element_generators.plate_element_generator import PlateElementGeneratorParams

            generators.append(
                PlateElementGenerator(
                    populator_panel,
                    frame_panel,
                    PlateElementGeneratorParams(
                        sheeting_inside=params.sheeting_inside,
                        sheeting_outside=params.sheeting_outside,
                    ),
                )
            )

        for feature_def in feature_definitions or []:
            generators.append(feature_def.generator_type(feature_def.feature, feature_def.params))

        for generator in generators:
            generator.resolve_beam_dimensions(frame_panel.thickness, params.standard_beam_width)

        return generators
