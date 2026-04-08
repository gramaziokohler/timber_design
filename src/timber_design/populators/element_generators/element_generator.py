from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from typing import List
from typing import Optional
from typing import Union
from compas.itertools import pairwise

from compas.geometry import Line
from compas.geometry import Vector
from compas.geometry import dot_vectors
from compas.geometry import intersection_line_line
from timber_design.populators.beam2d import AABB2D
from compas_timber.elements import Plate
from compas_timber.base import TimberElement
from compas_timber.utils import is_point_in_polyline
from compas_timber.connections import JointCandidate

from timber_design.populators import Beam2D
from timber_design.workflow import CategoryRule
from timber_design.workflow import DirectRule
from timber_design.populators import BeamOutlineIntersectionData
from timber_design.populators import find_beam_outline_crossings
from timber_design.populators.connection_solver_2d import ConnectionSolver2D


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


@dataclass
class ElementGeneratorParams:
    beam_width_overrides: Optional[dict] = None
    joint_rule_overrides: Optional[List[CategoryRule]] = None

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
        params: "ElementGeneratorParams",
    ):
        self.feature = feature
        self.beam_width_overrides = params.beam_width_overrides or {}
        if params.joint_rule_overrides:
            self.rules = self.update_rules(params.joint_rule_overrides)
        else:
            self.rules = self.RULES
        self.beam_dimensions: dict[str, tuple[float, float]] = {}
        self.joint_defs = []
        self.elements = []
        self.outline = None
        self.test = []


    @property
    def aabb(self):
        """The 2D axis-aligned bounding box enclosing all elements in this generator.

        Returns an :class:`~timber_design.populators.beam2d.AABB2D` so the
        result is compatible with :func:`~timber_design.populators.connection_solver_2d.aabb_overlap`
        and avoids the ``ZeroDivisionError`` from ``Box.from_points`` on flat
        (z=0) geometry.
        """
        pts = []
        for element in self.elements:
            if element.aabb:
                pts.extend(element.aabb.points)
        if not pts:
            return None
        return AABB2D.from_points(pts)


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

    def resolve_beam_dimensions(self, frame_thickness: float, standard_beam_width: float = 0.0) -> None:
        """Populate ``beam_dimensions`` from *frame_thickness*, *standard_beam_width*, and any per-category overrides."""
        for category in self.BEAM_CATEGORY_NAMES:
            if category in self.beam_width_overrides:
                self.beam_dimensions[category] = (self.beam_width_overrides[category], frame_thickness)
            else:
                self.beam_dimensions[category] = (standard_beam_width, frame_thickness)

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
            return None
        #     raise ValueError("No joint definition found for {} and {}".format(element_a.attributes["category"], element_b.attributes["category"]))

        direct_rule = None
        for rule in matching_rules:
            if rule.category_a == element_a.attributes["category"]:
                # perfect match
                rule_kwargs = rule.kwargs.copy()
                rule_kwargs.update(kwargs)
                return DirectRule(rule.joint_type, [element_a, element_b], **rule_kwargs)
        else:
            # match set but wrong order
            rule_kwargs = rule.kwargs.copy()
            rule_kwargs.update(kwargs)
            return DirectRule(rule.joint_type, [element_b, element_a], **rule_kwargs)


    def cull_beam_segment(self, beam: Beam2D) -> bool:
        """Determines whether the beam segment should be culled by the element generator."""
        return False

    def cull_element_at_point(self, point) -> bool:
        """Determines whether an element at the given point should be culled by the element generator."""
        if self.BOUNDARY_TYPE == FeatureBoundaryType.NONE:
            return False
        if self.outline is None:
            return False
        is_inside = is_point_in_polyline(point, self.outline, in_plane=False)
        if self.BOUNDARY_TYPE == FeatureBoundaryType.EXCLUSIVE and is_inside:
            return True
        if self.BOUNDARY_TYPE == FeatureBoundaryType.INCLUSIVE and not is_inside:
            return True

    def apply_to_plate(self, plate: Plate) -> None:
        """Apply the element group's feature definition to the plate based on the element generator."""
        pass

    def trim_beam(self, beam: Beam2D, skip_notches: Optional[bool]=True, skip_laps: Optional[bool]=True, ) -> list[Beam2D]:
        """Splits the beam based on the element generator's feature definition and returns the resulting beam segments."""
        if self.BOUNDARY_TYPE == FeatureBoundaryType.NONE:
            return [beam]
        if self.outline is None:
            return [beam]

        crossings = find_beam_outline_crossings(beam, self.outline, skip_notches=skip_notches, skip_laps=skip_laps)
        if not crossings:
            # No outline crossings — keep or cull the whole beam, preserving object identity.
            return [] if self.cull_element_at_point(beam.centerline.midpoint) else [beam]

        intersections = [
            BeamOutlineIntersectionData(start_dot=0.0),
            BeamOutlineIntersectionData(end_dot=beam.length),
        ]
        intersections.extend(crossings)

        intersections.sort(key=lambda x: x.average_dot)
        beam_segs = []
        for pair in pairwise(intersections):
            seg_start = min(pair[0].all_dots)
            seg_end = max(pair[1].all_dots)

            # Skip degenerate segments that arise when a crossing lands exactly
            # at the beam start/end or two crossings are at the same position.
            if seg_end - seg_start < 0.000001:
                continue

            beam_seg = beam.get_beam_segment(seg_start, seg_end)
            if self.cull_element_at_point(beam_seg.centerline.midpoint):
                continue
            if self.cull_beam_segment(beam_seg):
                continue
            beam_segs.append(beam_seg)

        return beam_segs

    def create_joint_candidates(self, model):
        """Yield ``(beam_a, beam_b)`` pairs within this generator whose blank AABBs overlap."""
        solver = ConnectionSolver2D()
        beam_elements = [e for e in self.elements if isinstance(e, Beam2D)]
        pairs = solver.find_intersecting_pairs(beam_elements)
        candidates = []
        for element_a, element_b in pairs:
            topo_result = solver.find_topology(element_a, element_b)
            if topo_result is not None:
                candidate = JointCandidate(topo_result.beam_a, topo_result.beam_b, distance = topo_result.distance, topology = topo_result.topology, location = topo_result.location)
                model.add_joint_candidate(candidate)
                candidates.append(candidate)
        return candidates

    def trim_elements_with_generator(self, generator, skip_notches=False, skip_laps=False):
        # type: (ElementGenerator, bool, bool) -> list[TimberElement]
        """Split this generator's elements at every intersection with *generator_b*'s outline.
        Parameters
        ----------
        generator : :class:`~timber_design.populators.ElementGenerator`
        skip_notches : bool
        skip_laps : bool
        Returns
        -------
        new_elements : list[:class:`~timber_design.populators.elements.Element`]
        rules_to_cull : list
        """
        new_elements = []
        for element in self.elements:
            if element.is_beam:
                new_elements.extend(generator.trim_beam(element))
            elif element.is_plate:
                generator.apply_to_plate(element)
                new_elements.append(element)
        self.elements = new_elements


    @abstractmethod
    def generate_elements(self):
        """Generates elements for the panel based on the panel populator and optional feature definition."""
        raise NotImplementedError("generate_elements method must be implemented in subclasses of ElementGenerator")

    def extend_elements(self, other_generators: list["ElementGenerator"]):
        pass

    def create_internal_joint_defs(self, model) -> list[DirectRule]:
        """Return :class:`~timber_design.workflow.DirectRule` objects for element pairs within this generator."""
        for candidate in self.create_joint_candidates(model):
            rule = self.get_direct_rule_from_elements(candidate.element_a, candidate.element_b)
            if rule is not None:
                self.joint_defs.append(rule)
