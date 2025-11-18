from timber_design.element_generators import SlabElementGeneratorParameters
from timber_design.element_generators.element_generator_parameters import ElementGeneratorParameters
from timber_design.populators import FeatureDefinition
from compas_timber.elements import Plate


def create_plates(parameters, slab_populator):
    elements = {}
    if parameters.sheeting_inside:
        plate = Plate.from_outlines(slab_populator.outline_a, slab_populator.frame_outline_a)            
        elements["inside_plate"] = plate
    if parameters.sheeting_outside:
        plate = Plate.from_outlines(slab_populator.outline_b, slab_populator.frame_outline_b)
        elements["outside_plate"] = plate
    return FeatureDefinition(slab_populator, parameters, elements=elements)

    
def apply_plate_cuts(feature_def, intersecting_features):
    for plate in feature_def.elements.values():
        for feature_definition in intersecting_features:
                feature_definition.parameters.apply_to_plate(plate, feature_definition)


class SlabPlateElementGeneratorParametersA(ElementGeneratorParameters):
    """A slab detail set that uses the default edge beams, studs, and plates."""

    BEAM_CATEGORY_NAMES = ["inside_plate", "outside_plate"]
    RULES = []

    def __init__(self, sheeting_inside=None, sheeting_outside=None, beam_width_overrides=None, joint_rule_overrides=None):
        super(SlabPlateElementGeneratorParametersA, self).__init__(
            beam_width_overrides=beam_width_overrides,
            joint_rule_overrides=joint_rule_overrides,
        )
        self.sheeting_inside = sheeting_inside
        self.sheeting_outside = sheeting_outside


    def generate_elements(self, slab_populator):
        """Populates the slab with elements and joints according to the detail set.

        Parameters
        ----------
        slab_populator : :class:`compas_timber.populators.SlabPopulator`
            The slab populator to populate.
        """
        return create_plates(self, slab_populator)


        
    def join_elements(self, slab_populator, feature_definition=None):
        """Join the elements for WindowDetailB."""
        intersecting_features = slab_populator.feature_definitions
        apply_plate_cuts(feature_definition, intersecting_features)
        return []
    