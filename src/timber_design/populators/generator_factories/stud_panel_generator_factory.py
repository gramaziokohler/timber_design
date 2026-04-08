from __future__ import annotations

from typing import TYPE_CHECKING
from typing import List
from typing import Union

from compas.geometry import Vector
from compas_timber.elements import Panel
from compas_timber.panel_features import Opening

# avoid package-level imports that can create circular imports; import generators locally in functions
from timber_design.workflow import CategoryRule

from .panel_generator_factory import GeneratorFactoryParams
from .panel_generator_factory import PanelGeneratorFactory
from .panel_generator_factory import get_frame_panel

if TYPE_CHECKING:
    from timber_design.populators import ElementGenerator


class StudPanelGeneratorFactoryParams(GeneratorFactoryParams):
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
        stud_spacing: Union[float, None] = None,
        standard_beam_width_increment: Union[float, None] = None,
        edge_beam_min_width: Union[float, None] = None,
        stud_direction: Union[Vector, None] = None,
        sheeting_outside: float = 0,
        sheeting_inside: float = 0,
        lintel_posts: bool = False,
        split_bottom_plate_beam: bool = False,
        beam_width_overrides: Union[dict, None] = None,
        joint_rule_overrides: Union[List[CategoryRule], None] = None,
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


class StudPanelGeneratorFactory(PanelGeneratorFactory):
    """Factory for creating stud panel element generators."""

    @classmethod
    def create_generators(cls, populator_panel: Panel, params: StudPanelGeneratorFactoryParams, feature_definitions=None) -> List["ElementGenerator"]:
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

        frame_panel = get_frame_panel(populator_panel, params)
        generators: List["ElementGenerator"] = []

        from timber_design.populators import EdgeElementGenerator
        from timber_design.populators.element_generators.edge_element_generator import EdgeElementGeneratorParams

        generators.append(
            EdgeElementGenerator(
                frame_panel,
                EdgeElementGeneratorParams(
                    standard_beam_width_increment=params.standard_beam_width_increment,
                    edge_beam_min_width=params.edge_beam_min_width or params.standard_beam_width,
                    beam_width_overrides=params.beam_width_overrides,
                    joint_rule_overrides=params.joint_rule_overrides,
                ),
            )
        )

        if params.stud_spacing:
            from timber_design.populators import StudElementGenerator
            from timber_design.populators.element_generators.stud_element_generator import StudElementGeneratorParams

            generators.append(
                StudElementGenerator(
                    frame_panel,
                    StudElementGeneratorParams(
                        stud_spacing=params.stud_spacing,
                        beam_width_overrides=params.beam_width_overrides,
                        joint_rule_overrides=params.joint_rule_overrides,
                    ),
                )
            )

        if params.sheeting_inside or params.sheeting_outside:
            from timber_design.populators import PlateElementGenerator
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

        for feature in populator_panel.features:
            if isinstance(feature, Opening):
                from timber_design.populators import OpeningElementGenerator
                from timber_design.populators.element_generators.opening_element_generator import OpeningElementGeneratorParams

                generators.append(
                    OpeningElementGenerator(
                        feature,
                        OpeningElementGeneratorParams(
                            lintel_posts=params.lintel_posts,
                            split_bottom_plate_beam=params.split_bottom_plate_beam,
                            beam_width_overrides=params.beam_width_overrides,
                            joint_rule_overrides=params.joint_rule_overrides,
                        ),
                    )
                )

        for feature_def in feature_definitions or []:
            generators.append(feature_def.generator_type(feature_def.feature, feature_def.params))

        for generator in generators:
            generator.resolve_beam_dimensions(frame_panel.thickness, params.standard_beam_width)

        return generators
