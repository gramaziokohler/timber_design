from timber_design.element_generators import ElementGenerator


class SlabElementGenerator(ElementGenerator):
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

    def __init__(
        self, stud_direction=None, standard_beam_width=None, edge_generator=None, stud_generator=None, plate_generator=None, beam_width_overrides=None, joint_rule_overrides=None
    ):
        super(SlabElementGenerator, self).__init__(standard_beam_width, beam_width_overrides, joint_rule_overrides)
        self.stud_direction = stud_direction
        self.standard_beam_width = standard_beam_width
        self.edge_generator = edge_generator
        self.stud_generator = stud_generator
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
        stud_spacing=None,
        standard_beam_width_increment=None,
        edge_beam_min_width=None,
        stud_direction=None,
        sheeting_outside=0,
        sheeting_inside=0,
        beam_width_overrides=None,
        joint_rule_overrides=None,
    ):
        if edge_beam_min_width:
            from timber_design.element_generators import SlabEdgeElementGeneratorParametersA

            edge_generator = SlabEdgeElementGeneratorParametersA(
                standard_beam_width_increment=standard_beam_width_increment,
                edge_beam_min_width=edge_beam_min_width or standard_beam_width,
                joint_rule_overrides=joint_rule_overrides,
            )

        if stud_spacing:
            from timber_design.element_generators import SlabStudElementGeneratorParametersA

            stud_generator = SlabStudElementGeneratorParametersA(
                stud_spacing=stud_spacing, standard_beam_width=standard_beam_width, beam_width_overrides=beam_width_overrides, joint_rule_overrides=joint_rule_overrides
            )

        if sheeting_inside or sheeting_outside:
            from timber_design.element_generators import SlabPlateElementGeneratorParametersA

            plate_generator = SlabPlateElementGeneratorParametersA(sheeting_outside=sheeting_outside, sheeting_inside=sheeting_inside)
        return cls(stud_direction, standard_beam_width, edge_generator, stud_generator, plate_generator)

    def generate_elements(self, slab_populator):
        """Populates the slab with elements and joints according to the detail set.

        Parameters
        ----------
        slab_populator : :class:`compas_timber.populators.SlabPopulator`
            The slab populator to populate.
        """
        for generator in [self.edge_generator, self.stud_generator, self.plate_generator]:
            fd = generator.generate_elements(slab_populator)
            slab_populator.element_groups.append(fd)

    def update_rules(self, joint_rule_overrides):
        """Update the rules with any overrides provided."""
        for generator in [self.edge_generator, self.stud_generator, self.plate_generator]:
            generator.update_rules(joint_rule_overrides)

    def update_beam_dimensions(self, slab_populator):
        """Get the beam dimensions for the detail set."""
        for generator in [self.edge_generator, self.stud_generator, self.plate_generator]:
            generator.update_beam_dimensions(slab_populator)
