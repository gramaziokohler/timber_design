from abc import ABC
from abc import abstractmethod
from typing import Optional
from typing import Union

from compas.geometry import Line
from compas.geometry import Vector
from compas.geometry import dot_vectors
from compas.geometry import intersection_line_line
from compas_timber.connections import JointTopology
from compas_timber.elements import Plate
from compas_timber.elements import TimberElement
from compas_timber.utils import is_point_in_polyline

from timber_design.populators.beam2d import Beam2D
from timber_design.workflow import CategoryRule
from timber_design.workflow import DirectRule


class FeatureBoundaryType(object):
    """Defines the boundary type for a feature definition.
    Attributes
    ----------
    EXCLUSIVE : str
        The feature defines an exclusive boundary, i.e. an area where elements should not be placed.
    INCLUSIVE : str
        The feature defines an inclusive boundary, i.e. an area where elements are allowed.
    """

    EXCLUSIVE = "exclusive"
    INCLUSIVE = "inclusive"
    NONE = "none"


class ElementGeneratorParams(object):
    def __init__(
        self,
        beam_width_overrides: Optional[dict] = None,
        joint_rule_overrides: Optional[list[CategoryRule]] = None,
    ):
        self.beam_width_overrides = beam_width_overrides
        self.joint_rule_overrides = joint_rule_overrides

    @property
    def __data__(self):
        return {
            "beam_width_overrides": self.beam_width_overrides,
            "joint_rule_overrides": self.joint_rule_overrides,
        }


class ElementGenerator(ABC):
    """Abstract class for an element generator.
    An ElementGenerator creates a specific set of elements to populate a panel, for example studs, edge beams, plates, or elements necessary for a SlabFeature.
    It also creates the necessary joint definitions between the generated elements and other elements in the same panel.

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
    BOUNDARY_TYPE = FeatureBoundaryType.NONE

    def __init__(
        self,
        feature,
        standard_beam_width=None,
        beam_width_overrides=None,
        joint_rule_overrides=None,
    ):
        self.feature = feature
        self.standard_beam_width = standard_beam_width or 0.0
        self.beam_width_overrides = beam_width_overrides or {}  # actual dimensions need a PanelPopulator instance
        if joint_rule_overrides:
            self.rules = self.update_rules(joint_rule_overrides)
        else:
            self.rules = self.RULES
        self.beam_dimensions: dict[str, tuple[float, float]] = {}  # to be populated with update_beam_dimensions

        self.elements = []
        self.outline = None
        self.test = []

    def update_rules(self, joint_rule_overrides: list[CategoryRule]) -> list[CategoryRule]:
        """Update the rules with any overrides provided."""
        rules = [r for r in self.RULES]

        for override in joint_rule_overrides:
            # NOTE: this is a bit of a breach of encapsulation, but necessary to allow for rule overrides
            # TODO: if we're only working with category rules here then make it explicit, if not, find a way to use the public interface of JointRule
            for rule in rules:
                if rule.category_a not in self.BEAM_CATEGORY_NAMES or rule.category_b not in self.BEAM_CATEGORY_NAMES:
                    # rule does not apply to this generator
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

    def resolve_beam_dimensions(self, frame_thickness: float) -> None:
        # TODO: consider renaming to `resolve_beam_dimensions`
        """updates the beam dimensions map based on the standard beam width, frame thickness, and any overrides provided."""
        for category in self.BEAM_CATEGORY_NAMES:
            if category in self.beam_width_overrides:
                self.beam_dimensions[category] = (self.beam_width_overrides[category], frame_thickness)
            else:
                self.beam_dimensions[category] = (self.standard_beam_width, frame_thickness)

    def beam_from_category(self, centerline: Line, category: str, **kwargs) -> Beam2D:
        """Creates a :class:`~timber_design.populators.Beam2D` from a centerline and a category.

        Parameters
        ----------
        centerline : :class:`compas.geometry.Line`
            The centerline to create the beam from.
        category : str
            The category of the beam, which determines its dimensions.
        kwargs : dict, optional
            Additional attributes to set on the beam.

        Returns
        -------
        :class:`~timber_design.populators.Beam2D`
            The created beam with the specified category and attributes.
        """
        if category not in self.beam_dimensions:
            raise ValueError("Unknown beam category: {}".format(category))
        width = self.beam_dimensions[category][0]
        height = self.beam_dimensions[category][1]
        beam = Beam2D.from_centerline(centerline, width=width, height=height, z_vector=Vector(0, 0, 1))
        for key, value in kwargs.items():
            beam.attributes[key] = value
        beam.attributes["category"] = category
        if beam is None:
            raise ValueError("Failed to create beam from centerline: {}".format(centerline))
        return beam

    def get_direct_rule_from_elements(self, element_a: TimberElement, element_b: TimberElement, **kwargs) -> Union[DirectRule, None]:
        """Get the joint type for the given elements."""
        matching_rules = [r for r in self.rules if set([r.category_a, r.category_b]) == set([element_a.attributes["category"], element_b.attributes["category"]])]
        if not matching_rules:
            raise ValueError("No joint definition found for {} and {}".format(element_a.attributes["category"], element_b.attributes["category"]))

        direct_rule = None
        for rule in matching_rules:
            if rule.category_a == element_a.attributes["category"]:
                # perfect match
                rule_kwargs = rule.kwargs.copy()
                rule_kwargs.update(kwargs)
                direct_rule = DirectRule(rule.joint_type, [element_a, element_b], **rule_kwargs)
                break
        else:
            # match set but wrong order
            rule_kwargs = rule.kwargs.copy()
            rule_kwargs.update(kwargs)
            direct_rule = DirectRule(rule.joint_type, [element_b, element_a], **rule_kwargs)

        # set the 'dot' attribute for future parsing of joints when splitting beams.
        kwargs.update(rule.kwargs)
        if all([isinstance(el, Beam2D) for el in [element_a, element_b]]):
            point = direct_rule.kwargs.get("location", intersection_line_line(element_a.centerline, element_b.centerline)[0])
            if not point:
                return None
            for element in [element_a, element_b]:
                if element.attributes.get("joint_defs", None) is None:
                    element.attributes["joint_defs"] = {}
                element_dot = dot_vectors(Vector.from_start_end(element.centerline.start, point), element.centerline.direction)
                element.attributes["joint_defs"][element_dot] = direct_rule
        return direct_rule

    def cull_beam_segment(self, beam: Beam2D) -> bool:
        """Determines whether the beam segment should be culled by the element generator."""
        return False

    def cull_element_at_point(self, point) -> bool:
        """Determines whether an element at the given point should be culled by the element generator."""
        if self.BOUNDARY_TYPE == FeatureBoundaryType.NONE:
            return False
        if self.outline is None:
            return False
        if self.BOUNDARY_TYPE == FeatureBoundaryType.EXCLUSIVE and is_point_in_polyline(point, self.outline, in_plane=False):
            return True
        if self.BOUNDARY_TYPE == FeatureBoundaryType.INCLUSIVE and not None and not is_point_in_polyline(point, self.outline, in_plane=False):
            return True

    def apply_to_plate(self, plate: Plate) -> None:
        """Apply the element group's feature definition to the plate based on the element generator."""
        pass

    @abstractmethod
    def generate_elements(self):
        """Generates elements for the panel based on the panel populator and optional feature definition."""
        raise NotImplementedError("generate_elements method must be implemented in subclasses of ElementGenerator")

    @abstractmethod
    def join_elements(self, populator_joint_defs, element_generators) -> list[DirectRule]:
        """Generates DirectRule joint definitions for the panel based on the panel populator and optional feature definition."""
        raise NotImplementedError("generate_elements method must be implemented in subclasses of ElementGenerator")
