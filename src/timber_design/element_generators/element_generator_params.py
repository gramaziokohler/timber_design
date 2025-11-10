from compas_timber.connections import JointTopology
import abc


class ElementGeneratorParams(abc.ABC):
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

    def __init__(self, beam_dimensions=None, joint_rule_overrides=None):
        self.beam_width_overrides = beam_dimensions or {}  # actual dimensions need a SlabPopulator instance
        if not joint_rule_overrides:
            self.rules = self.RULES
        else:
            self.rules = self.update_rules(joint_rule_overrides)

    def update_rules(self, joint_rule_overrides):
        """Update the rules with any overrides provided."""
        rules = [r for r in self.RULES]

        for override in joint_rule_overrides:
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

    def get_beam_dimensions(self, slab_populator):
        """Get the beam dimensions for the detail set."""
        beam_dims = {}
        for category in self.BEAM_CATEGORY_NAMES:
            if category in self.beam_width_overrides:
                beam_dims[category] = (self.beam_width_overrides[category], slab_populator.frame_thickness)
            else:
                beam_dims[category] = (slab_populator.detail_set.beam_width, slab_populator.frame_thickness)
        return beam_dims

