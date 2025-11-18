from compas.geometry import Vector
from compas.geometry import intersection_line_line
from compas.tolerance import TOL
from compas_timber.connections import JointTopology
from compas_timber.design import DirectRule
from compas_timber.elements import Beam


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
    RULES = []

    def __init__(
        self,
        standard_beam_width = None,
        beam_width_overrides=None,
        joint_rule_overrides=None,
    ):
        self.standard_beam_width = standard_beam_width or 0.0
        self.beam_width_overrides = beam_width_overrides or {}  # actual dimensions need a SlabPopulator instance
        if joint_rule_overrides:
            self.rules = self.update_rules(joint_rule_overrides)
        else:
            self.rules = self.RULES
        self.beam_dimensions = {}  # to be populated with update_beam_dimensions

    def update_rules(self, joint_rule_overrides):
        """Update the rules with any overrides provided."""
        rules = [r for r in self.RULES]

        for override in joint_rule_overrides:
            for rule in rules:
                if not rule.category_a in self.BEAM_CATEGORY_NAMES or not rule.category_b in self.BEAM_CATEGORY_NAMES:
                    #rule does not apply to this generator
                    continue
                # element order is important TODO: use rule.comply_topology when merged. TOPO_EDGE_FACE should not occur, but adding for future-proofing.
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

    def update_beam_dimensions(self, slab_populator):
        """Get the beam dimensions for the detail set."""
        for category in self.BEAM_CATEGORY_NAMES:
            if category in self.beam_width_overrides:
                self.beam_dimensions[category] = (self.beam_width_overrides[category], slab_populator.frame_thickness)
            else:
                self.beam_dimensions[category] = (self.standard_beam_width, slab_populator.frame_thickness)


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
            if (rule.category_a == element_a.attributes["category"] and rule.category_b == element_b.attributes["category"]):
                return DirectRule(rule.joint_type, [element_a, element_b], **kwargs)

        for rule in self.rules:
            if set([rule.category_a, rule.category_b]) == set([element_a.attributes["category"], element_b.attributes["category"]]):
                if not (rule.category_a == element_a.attributes["category"] and rule.category_b == element_b.attributes["category"]):
                    element_a, element_b = element_b, element_a
                kwargs.update(rule.kwargs)
                point = rule.kwargs.get("location", intersection_line_line(element_a.centerline, element_b.centerline)[0])
                return DirectRule(rule.joint_type, [element_a, element_b], location=point, **kwargs)

        else:
            raise ValueError("No joint definition found for {} and {}".format(element_a.attributes["category"], element_b.attributes["category"]))

    def cull_stud(self, stud, feature_def) -> bool:
        """Cull and split the studs for door openings."""
        return False

    def cull_beam_segment(self, stud, feature_def) -> bool:
        """Cull and split the studs for door openings."""
        return False

    def apply_to_plate(self, plate, feature_definition):
        """Apply the feature definition to the plate."""
        pass