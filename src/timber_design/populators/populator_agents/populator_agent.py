from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from typing import List
from typing import Optional
from typing import Union

from compas.geometry import Line
from compas.geometry import Vector
from compas.itertools import pairwise
from compas_timber.base import TimberElement
from compas_timber.connections import JointCandidate
from compas_timber.connections import JointTopology
from compas_timber.elements import Plate
from compas_timber.utils import is_point_in_polyline

from timber_design.populators import Beam2D
from timber_design.populators import BeamOutlineIntersectionData
from timber_design.populators import find_beam_outline_crossings
from timber_design.populators.beam2d import AABB2D
from timber_design.populators.connection_solver_2d import ConnectionSolver2D
from timber_design.workflow import CategoryRule
from timber_design.workflow import DirectRule


class FeatureBoundaryType(object):
    """Controls how an agent's outline is used to include or exclude beam segments.

    Each concrete :class:`PopulatorAgent` declares a ``BOUNDARY_TYPE`` class
    attribute that governs what :meth:`~PopulatorAgent.trim_beam` does with
    segments whose midpoints fall inside or outside the agent's
    :attr:`~PopulatorAgent.outline` polyline.

    Attributes
    ----------
    NONE : str
        No boundary culling — all segments are kept regardless of the outline.
        Used by agents whose elements span the full panel (studs, edge beams).
    EXCLUSIVE : str
        The outline defines a *no-go zone*.  Segments whose midpoints are inside
        the outline are discarded.  Used by :class:`~timber_design.populators.OpeningPopulatorAgent`
        so that studs passing through a door or window opening are removed.
    INCLUSIVE : str
        The outline defines an *allowed zone*.  Segments whose midpoints fall
        *outside* the outline are discarded.  Used by
        :class:`~timber_design.populators.EdgePopulatorAgent` and
        :class:`~timber_design.populators.RecessPopulatorAgent`.
    """

    EXCLUSIVE = "exclusive"
    INCLUSIVE = "inclusive"
    NONE = "none"


@dataclass
class PopulatorAgentConfig:
    """Base dataclass for populator agent configuration.

    All concrete config classes (e.g. :class:`~timber_design.populators.StudPopulatorAgentConfig`,
    :class:`~timber_design.populators.EdgePopulatorAgentConfig`) extend this
    class and add their own fields.

    Parameters
    ----------
    beam_width_overrides : dict, optional
        Per-category beam width overrides.  Keys are category name strings
        (e.g. ``"stud"``, ``"header"``); values are floats in model units.
        Overrides are applied by :meth:`~PopulatorAgent.resolve_beam_dimensions`.
    joint_rule_overrides : list[:class:`~timber_design.workflow.CategoryRule`], optional
        Rules that replace matching entries in the agent's ``RULES`` list.
        Non-matching overrides are appended.
    feature : object, optional
        The specific feature instance this config is bound to.  ``None`` when
        used as a type-level default (not yet bound to a feature).

    Class Attributes
    ----------------
    AGENT_TYPE : type or None
        The :class:`PopulatorAgent` subclass this config instantiates.
        Set on each concrete subclass after both classes are defined.
    """

    AGENT_TYPE = None

    beam_width_overrides: Optional[dict] = None
    joint_rule_overrides: Optional[List[CategoryRule]] = None
    feature: Optional[object] = None

    @property
    def __data__(self):
        return {
            "beam_width_overrides": self.beam_width_overrides,
            "joint_rule_overrides": self.joint_rule_overrides,
        }

    def get_agent_from_feature(self, feature):
        """Instantiate the agent for the given feature.

        Parameters
        ----------
        feature : object
            The (possibly transformed) feature to pass to the agent constructor.

        Returns
        -------
        :class:`PopulatorAgent`

        Raises
        ------
        NotImplementedError
            If ``AGENT_TYPE`` has not been set on this config class.
        """
        if self.AGENT_TYPE is None:
            raise NotImplementedError("{} does not define AGENT_TYPE".format(type(self).__name__))
        return self.AGENT_TYPE(feature, self)


class PopulatorAgent(ABC):
    """Abstract base class for all panel populator agents.

    A ``PopulatorAgent`` is responsible for one logical group of framing
    elements within a panel (edge beams, studs, plates, opening surround,
    recess frame, …).  Subclasses implement :meth:`generate_elements` and
    optionally override :meth:`extend_elements` and :meth:`cull_beam_segment`.

    Every agent holds:

    - :attr:`elements` — the flat list of :class:`~timber_design.populators.Beam2D`
      and :class:`~compas_timber.elements.Plate` objects it has created.
    - :attr:`outline` — a closed :class:`~compas.geometry.Polyline` that marks
      its spatial boundary in populator space, used for trimming by peer agents.
    - :attr:`rules` — :class:`~timber_design.workflow.CategoryRule` instances
      that specify which joint type to create between specific beam categories.
    - :attr:`beam_dimensions` — ``{category: (width, height)}`` populated by
      :meth:`resolve_beam_dimensions` from factory-level parameters.

    Class-level attributes
    ----------------------
    FEATURE_TYPE : type or None
        The :class:`~compas_timber.panel_features.PanelFeature` subclass this
        agent is designed to handle.  Set on feature-specific agents (e.g.
        :attr:`OpeningPopulatorAgent.FEATURE_TYPE` ``= Opening``); ``None`` for
        panel-level agents.  Used by
        :class:`~timber_design.populators.FeaturePopulatorAgentDefinition` to
        infer the feature type when not supplied explicitly.
    BEAM_CATEGORY_NAMES : list[str]
        The beam categories this agent can create.  Used by
        :meth:`resolve_beam_dimensions`.
    RULES : list[:class:`~timber_design.workflow.CategoryRule`]
        Default joint rules.  May be overridden per instance via
        :class:`PopulatorAgentConfig`.
    BOUNDARY_TYPE : :class:`FeatureBoundaryType`
        Controls how the agent's outline is used during trimming.
        Defaults to :attr:`~FeatureBoundaryType.NONE`.

    Parameters
    ----------
    feature : :class:`compas_timber.elements.Panel` or :class:`compas_timber.panel_features.PanelFeature`
        The panel or feature whose geometry drives element creation.
    params : :class:`PopulatorAgentParams`
        Parameters including beam width overrides and joint rule overrides.

    Attributes
    ----------
    feature : :class:`compas_timber.elements.Panel` or :class:`compas_timber.panel_features.PanelFeature`
    panel : :class:`compas_timber.elements.Panel`
        Alias for :attr:`feature` (convenience property available on all agents).
    elements : list[:class:`~timber_design.populators.Beam2D` | :class:`~compas_timber.elements.Plate`]
        All elements created by this agent.  Populated by :meth:`generate_elements`
        and mutated by :meth:`trim_elements_with_agent`.
    outline : :class:`~compas.geometry.Polyline` or None
        Closed boundary polyline in populator space.  Set by :meth:`generate_elements`.
    rules : list[:class:`~timber_design.workflow.CategoryRule`]
        Active joint rules (defaults merged with any overrides).
    beam_dimensions : dict[str, tuple[float, float]]
        ``{category: (width, height)}`` mapping resolved by
        :meth:`resolve_beam_dimensions`.
    joint_defs : list[:class:`~timber_design.workflow.DirectRule`]
        Accumulated joint definitions, populated by :meth:`create_internal_joint_defs`.
    aabb : :class:`~timber_design.populators.AABB2D` or None
        2D bounding box enclosing all elements in this agent.
    """

    FEATURE_TYPE = None
    BEAM_CATEGORY_NAMES = []
    RULES = []
    BOUNDARY_TYPE = FeatureBoundaryType.NONE

    def __init__(
        self,
        feature,
        params: "PopulatorAgentConfig",
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

    @property
    def aabb(self):
        """The 2D axis-aligned bounding box enclosing all elements in this agent.

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

    @property
    def panel(self):
        """The panel (or feature) associated with this agent.

        For agents whose ``feature`` is the panel itself (edge, plate,
        stud, recess) this is a direct alias.  Subclasses that use a different
        feature type (e.g. ``OpeningPopulatorAgent``) can override this.
        """
        return self.feature

    def update_rules(self, joint_rule_overrides: list[CategoryRule]) -> list[CategoryRule]:
        """Update the rules with any overrides provided."""
        rules = [r for r in self.RULES]

        for override in joint_rule_overrides:
            # NOTE: this is a bit of a breach of encapsulation, but necessary to allow for rule overrides
            # TODO: if we're only working with category rules here then make it explicit, if not, find a way to use the public interface of JointRule
            for rule in rules:
                if rule.category_a not in self.BEAM_CATEGORY_NAMES or rule.category_b not in self.BEAM_CATEGORY_NAMES:
                    # rule does not apply to this agent
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
            return
        # raise ValueError("No joint definition found for {} and {}".format(element_a.attributes["category"], element_b.attributes["category"]))

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
        """Determines whether the beam segment should be culled by the populator agent."""
        return False

    def cull_element_at_point(self, point) -> bool:
        """Determines whether an element at the given point should be culled by the populator agent."""
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
        """Apply the element group's feature definition to the plate based on the populator agent."""
        pass

    def trim_beam(
        self,
        beam: Beam2D,
        skip_notches: Optional[bool] = True,
        skip_laps: Optional[bool] = True,
    ) -> list[Beam2D]:
        """Splits the beam based on the populator agent's feature definition and returns the resulting beam segments."""
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
        """Yield ``(beam_a, beam_b)`` pairs within this agent whose blank AABBs overlap."""
        solver = ConnectionSolver2D()
        beam_elements = [e for e in self.elements if isinstance(e, Beam2D)]
        pairs = solver.find_intersecting_pairs(beam_elements)
        candidates = []
        for element_a, element_b in pairs:
            topo_result = solver.find_topology(element_a, element_b)
            if topo_result is not None:
                candidate = JointCandidate(topo_result.beam_a, topo_result.beam_b, distance=topo_result.distance, topology=topo_result.topology, location=topo_result.location)
                model.add_joint_candidate(candidate)
                candidates.append(candidate)
        return candidates

    def trim_elements_with_agent(self, agent, skip_notches=False, skip_laps=False):
        # type: (PopulatorAgent, bool, bool) -> list[TimberElement]
        """Split this agent's elements at every intersection with *agent*'s outline.
        Parameters
        ----------
        agent : :class:`~timber_design.populators.PopulatorAgent`
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
                new_elements.extend(agent.trim_beam(element))
            elif element.is_plate:
                agent.apply_to_plate(element)
                new_elements.append(element)
        self.elements = new_elements

    @abstractmethod
    def generate_elements(self):
        """Generates elements for the panel based on the panel populator and optional feature definition."""
        raise NotImplementedError("generate_elements method must be implemented in subclasses of PopulatorAgent")

    def extend_elements(self, other_agents: list["PopulatorAgent"]) -> None:
        pass

    def create_internal_joint_defs(self, model) -> list[DirectRule]:
        """Return :class:`~timber_design.workflow.DirectRule` objects for element pairs within this agent."""
        for candidate in self.create_joint_candidates(model):
            rule = self.get_direct_rule_from_elements(candidate.element_a, candidate.element_b)
            if rule is not None:
                self.joint_defs.append(rule)
