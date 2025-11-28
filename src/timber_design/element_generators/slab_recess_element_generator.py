from timber_design.element_generators import ElementGeneratorParameters


class SlabRecessElementGeneratorParameters(ElementGeneratorParameters):
    """Base class for opening detail sets.

    Parameters
    ----------
    beam_width_overrides : dict, optional
        A dictionary of beam width overrides for specific beam categories.
        key = beam category name, value = beam width.
    joint_rule_overrides : list[:class:`compas_timber.design.CategoryRule`], optional
        A list of category rules to override the default ones.
    """

    BEAM_CATEGORY_NAMES = []

    def __init__(self, edge_generator=None, recess_generator=None, plate_generator=None, standard_beam_width=None, beam_width_overrides=None, joint_rule_overrides=None):
        #type: (ElementGeneratorParameters, ElementGeneratorParameters, ElementGeneratorParameters, float | None, dict | None, list[CategoryRule] | None) -> None
        super(SlabRecessElementGeneratorParameters, self).__init__(standard_beam_width, beam_width_overrides, joint_rule_overrides)
        self.edge_generator = edge_generator
        self.recess_generator = recess_generator
        self.plate_generator = plate_generator

    @property
    def sheeting_inside(self):
        if self.plate_generator:
            return self.plate_generator.sheeting_inside
        return None

    @property
    def sheeting_outside(self):
        if self.plate_generator:
            return self.plate_generator.sheeting_outside
        return None

    @classmethod
    def from_basic_parameters(
        cls,
        standard_beam_width,
        recess_beam_width,
        recess_beam_height,
        edge_beam_min_width,
        standard_beam_width_increment=None,
        sheeting_outside=0,
        sheeting_inside=0,
        beam_width_overrides=None,
        joint_rule_overrides=None,
    ):

        from timber_design.element_generators import SlabEdgeElementGeneratorParametersA
        from timber_design.element_generators.recess_element_generator import RecessElementGeneratorParameters
        from timber_design.element_generators import SlabPlateElementGeneratorParametersA

        edge_generator = SlabEdgeElementGeneratorParametersA(
            standard_beam_width_increment=standard_beam_width_increment,
            edge_beam_min_width=edge_beam_min_width or standard_beam_width,
            beam_width_overrides=beam_width_overrides or {},
            joint_rule_overrides=joint_rule_overrides,
            )

        recess_generator = RecessElementGeneratorParameters(recess_beam_width, recess_beam_height, sheeting_inside,)

        if sheeting_inside or sheeting_outside:
            plate_generator = SlabPlateElementGeneratorParametersA(sheeting_outside=sheeting_outside, sheeting_inside=sheeting_inside)

        return cls(edge_generator, recess_generator, plate_generator, standard_beam_width, beam_width_overrides, joint_rule_overrides)

    def generate_elements(self, slab_populator):
        """Populates the slab with elements and joints according to the detail set.

        Parameters
        ----------
        slab_populator : :class:`compas_timber.populators.SlabPopulator`
            The slab populator to populate.
        """
        edge_group = self.edge_generator.generate_elements(slab_populator)
        slab_populator.element_groups.append(edge_group)
        slab_populator.element_groups.append(self.recess_generator.generate_elements(slab_populator, edge_group))
        slab_populator.element_groups.append(self.plate_generator.generate_elements(slab_populator))


    def update_rules(self, joint_rule_overrides):
        """Update the rules with any overrides provided."""
        for generator in [self.edge_generator, self.recess_generator, self.plate_generator]:
            generator.update_rules(joint_rule_overrides)

    def update_beam_dimensions(self, slab_populator):
        """Get the beam dimensions for the detail set."""
        for generator in [self.edge_generator, self.recess_generator, self.plate_generator]:
            generator.update_beam_dimensions(slab_populator)
