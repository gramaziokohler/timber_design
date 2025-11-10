from compas.geometry import Vector
from compas_timber.connections import JointTopology
from compas_timber.design import DirectRule
from compas_timber.elements import Beam

from compas_timber.design import CategoryRule
from compas_timber.connections import LButtJoint
from compas_timber.connections import TButtJoint

class ElementGeneratorParameters(object):
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
        self,
        standard_beam_width,
        beam_width_overrides=None,
        joint_rule_overrides=None,
    ):
        self.beam_width_overrides = beam_width_overrides or {}  # actual dimensions need a SlabPopulator instance
        self.joint_rule_overrides = joint_rule_overrides or []
        self.standard_beam_width = standard_beam_width


    def update_rules(self, standard_rules):
        """Update the rules with any overrides provided."""
        rules = [r for r in standard_rules]

        for override in self.joint_rule_overrides:
            for rule in rules:
                # element order is important TODO: use rule.comply_topology when merged. TOPO_EDGE_EDGE should not occur, but adding for future-proofing.
                if rule.joint_type.supported_topology == JointTopology.TOPO_T or rule.joint_type.supported_topology == JointTopology.TOPO_EDGE_FACE:
                    if override.category_a == rule.category_a and override.category_b == rule.category_b:
                        rule = override
                        break
                else:  # order does not matter
                    if set([override.category_a, override.category_b]) == set([rule.category_a, rule.category_b]):
                        rule = override
                        break
            else:
                rules.append(override)
        return rules

    def update_beam_dimensions(self, slab_populator, beam_category_names):
        """Get the beam dimensions for the detail set."""
        beam_dims = {}
        for category in beam_category_names:
            if category in self.beam_width_overrides:
                beam_dims[category] = (self.beam_width_overrides[category], slab_populator.frame_thickness)
            else:
                beam_dims[category] = (slab_populator.detail_set.beam_width, slab_populator.frame_thickness)
        return beam_dims


    def beam_from_category(self, segment, category, **kwargs):
        """Creates a beam from a segment and a category, using the dimensions from the configuration set.
        Parameters
        ----------
        segment : :class:`compas.geometry.Line`
            The segment to create the beam from.
        category : str
            The category of the beam, which determines its dimensions.
        slab_populator : :class:`compas_timber.populators.SlabPopulator`
            The populator instance that provides the beam dimensions.
        kwargs : dict, optional
            Additional attributes to set on the beam.

        Returns
        -------
        :class:`compas_timber.elements.Beam`
            The created beam with the specified category and attributes.
        """
        if category not in self.beam_dimensions:
            raise ValueError("Unknown beam category: {}".format(category))
        width = self.beam_dimensions[category][0]
        height = self.beam_dimensions[category][1]
        beam = Beam.from_centerline(segment, width=width, height=height, z_vector=Vector(0, 0, 1))
        for key, value in kwargs.items():
            beam.attributes[key] = value
        beam.attributes["category"] = category
        if beam is None:
            raise ValueError("Failed to create beam from segment: {}".format(segment))
        return beam

    def get_direct_rule_from_elements(self, element_a, element_b, **kwargs):
        """Get the joint type for the given elements."""
        for rule in self.rules:
            if rule.category_a == element_a.attributes["category"] and rule.category_b == element_b.attributes["category"]:
                kwargs.update(rule.kwargs)
                return DirectRule(rule.joint_type, [element_a, element_b], **kwargs)
        for rule in self.rules:
            if rule.category_a == element_b.attributes["category"] and rule.category_b == element_a.attributes["category"]:
                kwargs.update(rule.kwargs)
                return DirectRule(rule.joint_type, [element_b, element_a], **kwargs)

        raise ValueError("No joint definition found for {} and {}".format(element_a.attributes["category"], element_b.attributes["category"]))


class SlabElementGeneratorParameters(ElementGeneratorParameters):
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
        self,
        stud_spacing,
        standard_beam_width,
        stud_direction=None,
        sheeting_outside=0,
        sheeting_inside=0,
        beam_width_overrides=None,
        joint_rule_overrides=None,
    ):
        super(SlabElementGeneratorParameters, self).__init__(
            standard_beam_width,
            beam_width_overrides,
            joint_rule_overrides,
        )
        self.stud_spacing = stud_spacing
        self.stud_direction = stud_direction
        self.sheeting_outside = sheeting_outside
        self.sheeting_inside = sheeting_inside



class SlabElementGeneratorParametersA(SlabElementGeneratorParameters):
    """A slab detail set that uses the default edge beams, studs, and plates."""

    BEAM_CATEGORY_NAMES = ["stud", "edge_stud", "top_plate_beam", "bottom_plate_beam"]
    RULES = [
        CategoryRule(TButtJoint, "stud", "top_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(LButtJoint, "edge_stud", "edge_stud", mill_depth=10.0, max_distance=1.0),
        CategoryRule(LButtJoint, "edge_stud", "top_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(LButtJoint, "bottom_plate_beam", "top_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(LButtJoint, "top_plate_beam", "bottom_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(LButtJoint, "top_plate_beam", "top_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(LButtJoint, "bottom_plate_beam", "bottom_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(TButtJoint, "stud", "bottom_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(LButtJoint, "edge_stud", "bottom_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(TButtJoint, "stud", "edge_stud", mill_depth=10.0, max_distance=1.0),
        CategoryRule(TButtJoint, "stud", "detail", mill_depth=10.0, max_distance=1.0),
    ]

    def populate_details(self, slab_populator):
        """Populates the slab with elements and joints according to the detail set.

        Parameters
        ----------
        slab_populator : :class:`compas_timber.populators.SlabPopulator`
            The slab populator to populate.
        """
        self._set_frame_outlines(slab_populator)
        self._create_edge_beams(slab_populator, edge_beam_dim_increment=60.0)
        self._create_edge_joints(slab_populator)
        self._create_and_join_studs(slab_populator)
        self._create_plates(slab_populator)


class SlabElementGeneratorParametersB(SlabElementGeneratorParameters):
    """A slab detail set that uses the edge beams and plates but no studs."""

    BEAM_CATEGORY_NAMES = ["stud", "edge_stud", "top_plate_beam", "bottom_plate_beam"]
    RULES = [
        CategoryRule(LButtJoint, "edge_stud", "top_plate_beam", mill_depth=10.0),
        CategoryRule(LButtJoint, "edge_stud", "bottom_plate_beam", mill_depth=10.0),
    ]

    def populate_details(self, slab_populator):
        """Populates the slab with elements and joints according to the detail set.

        Parameters
        ----------
        slab_populator : :class:`compas_timber.populators.SlabPopulator`
            The slab populator to populate.
        """
        self._set_frame_outlines(slab_populator)
        self._create_edge_beams(slab_populator, edge_beam_dim_increment=60.0)
        self._create_edge_joints(slab_populator)
        self._create_plates(slab_populator)
