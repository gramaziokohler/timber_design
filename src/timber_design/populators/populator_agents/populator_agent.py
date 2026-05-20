from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from dataclasses import field
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

from timber_design.populators.agent_intersection import BeamOutlineIntersectionData
from timber_design.populators.agent_intersection import find_beam_outline_crossings
from timber_design.populators.beam2d import AABB2D
from timber_design.populators.beam2d import Beam2D
from timber_design.populators.connection_solver_2d import ConnectionSolver2D
from timber_design.populators.layer import Layer
from timber_design.workflow import CategoryRule
from timber_design.workflow import DirectRule


class AgentBoundaryType(object):
    """Controls how an agent's outline is used to include or exclude beam segments.

    Each concrete :class:`LayerAgent` declares a ``BOUNDARY_TYPE`` class
    attribute that governs what :meth:`~LayerAgent.trim_beam` does with
    segments whose midpoints fall inside or outside the agent's
    :attr:`~LayerAgent.outline` polyline.

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
class PopulatorAgentConfig(ABC):
    """Base dataclass for populator agent configuration.

    All concrete config classes (e.g. :class:`~timber_design.populators.StudPopulatorAgentConfig`,
    :class:`~timber_design.populators.EdgePopulatorAgentConfig`) extend this
    class and add their own fields.

    Parameters
    ----------
    beam_width_overrides : dict, optional
        Per-category beam width overrides.  Keys are category name strings
        (e.g. ``"stud"``, ``"header"``); values are floats in model units.
        Overrides are applied by :meth:`~LayerAgent.resolve_beam_dimensions`.
    joint_rule_overrides : list[:class:`~timber_design.workflow.CategoryRule`], optional
        Rules that replace matching entries in the agent's ``RULES`` list.
        Non-matching overrides are appended.

    Class Attributes
    ----------------
    AGENT_TYPE : type or None
        The :class:`LayerAgent` subclass this config instantiates.
        Set on each concrete subclass after both classes are defined.
    """
    IS_ABSTRACT = True
    AGENT_TYPE = None

    beam_width_overrides: Optional[dict] = None
    joint_rule_overrides: Optional[List[CategoryRule]] = None
    # Populated by resolve_beam_dimensions() before the agent is instantiated.
    # init=False keeps it out of __init__ and repr; default_factory ensures each
    # instance gets its own fresh dict instead of sharing a class-level mutable.
    beam_dimensions: dict = field(default_factory=dict, init=False)


    @property
    def __data__(self):
        return {
            "beam_width_overrides": self.beam_width_overrides,
            "joint_rule_overrides": self.joint_rule_overrides,
        }

    def resolve_beam_dimensions(self, standard_beam_width: float, frame_thickness: float) -> None:
        """Populate :attr:`beam_dimensions` from *standard_beam_width*, *frame_thickness*, and per-category overrides.

        Called by :meth:`~PanelPopulatorConfig.resolve_beam_dimensions` before
        agents are instantiated.  When the agent is later created via
        :meth:`get_agent_from_layer`, it copies this dict so its
        ``beam_dimensions`` are already populated.

        Parameters
        ----------
        standard_beam_width : float
            Default beam width applied to every category that has no override.
        frame_thickness : float
            Layer thickness used as the beam height for all categories.
        """
        if self.AGENT_TYPE is None:
            return
        bwo = self.beam_width_overrides or {}
        for category in self.AGENT_TYPE.BEAM_CATEGORY_NAMES:
            if category in bwo:
                self.beam_dimensions[category] = (bwo[category], frame_thickness)
            else:
                self.beam_dimensions[category] = (standard_beam_width, frame_thickness)



class PopulatorAgent(ABC):
    """Abstract base class for all panel populator agents.

    A ``LayerAgent`` is responsible for one logical group of framing
    elements within a panel (edge beams, studs, plates, opening surround,
    recess frame, …).  Subclasses implement :meth:`generate_elements` and
    optionally override :meth:`extend_elements` and :meth:`cull_beam_segment`.

    Every agent holds:

    - :attr:`layer` — the :class:`~timber_design.populators.Layer` it belongs
      to, which carries the panel geometry (``layer``) and the layer's
      position in the cross-section stack (``layer.layer_index``).
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
    BEAM_CATEGORY_NAMES : list[str]
        The beam categories this agent can create.  Used by
        :meth:`resolve_beam_dimensions`.
    INTERNAL_RULES : list[:class:`~timber_design.workflow.CategoryRule`]
        Default joint rules for **within-agent** pairs — elements that belong
        to this agent and are joined to each other.  Used by
        :meth:`create_joint_defs` / :meth:`get_direct_rule_from_elements`.
        Overridable per-instance via :attr:`LayerAgentConfig.joint_rule_overrides`.
    EXTERNAL_RULES : list[:class:`~timber_design.workflow.CategoryRule`]
        Default joint rules for **cross-agent** pairs — elements from this
        agent that are joined to elements from a different agent.  Used by
        :meth:`~timber_design.populators.PanelPopulator.create_cross_agent_joints`.
        Overridable per-instance via :attr:`LayerAgentConfig.joint_rule_overrides`.
    BOUNDARY_TYPE : :class:`FeatureBoundaryType`
        Controls how the agent's outline is used during trimming.
        Defaults to :attr:`~FeatureBoundaryType.NONE`.

    Parameters
    ----------
    layer : :class:`~timber_design.populators.Layer`
        The layer this agent operates within.  Provides the panel geometry
        (``layer``) and cross-section position (``layer.layer_index``).
    params : :class:`LayerAgentConfig`
        Configuration including beam width overrides, joint rule overrides,
        agent parameters and rule overrides.

    Attributes
    ----------
    layer : :class:`~timber_design.populators.Layer`
        The layer this agent belongs to.
    layer_index : int or None
        Index of this agent's layer in the cross-section stack.
        Taken directly from ``layer.layer_index``.
    panel : :class:`compas_timber.elements.Panel`
        The panel geometry for this layer.  Shortcut for ``self.layer``.
    elements : list[:class:`~timber_design.populators.Beam2D` | :class:`~compas_timber.elements.Plate`]
        All elements created by this agent.  Populated by :meth:`generate_elements`
        and mutated by :meth:`trim_within_layer` / :meth:`trim_agent_elements`.
    outline : :class:`~compas.geometry.Polyline` or None
        Closed boundary polyline in populator space.  Set by :meth:`generate_elements`.
    internal_rules : list[:class:`~timber_design.workflow.CategoryRule`]
        Active within-agent joint rules (``INTERNAL_RULES`` merged with any
        matching :attr:`LayerAgentConfig.joint_rule_overrides`).
    external_rules : list[:class:`~timber_design.workflow.CategoryRule`]
        Active cross-agent joint rules (``EXTERNAL_RULES`` merged with any
        matching :attr:`LayerAgentConfig.joint_rule_overrides`).
    beam_dimensions : dict[str, tuple[float, float]]
        ``{category: (width, height)}`` mapping resolved by
        :meth:`resolve_beam_dimensions`.
    joint_defs : list[:class:`~timber_design.workflow.DirectRule`]
        Accumulated joint definitions, populated by :meth:`create_joint_defs`.
    aabb : :class:`~timber_design.populators.AABB2D` or None
        2D bounding box enclosing all elements in this agent.
    layer_center_height : float
        Z coordinate of the centre of this agent's layer.  Used to place beam
        centrelines at the correct height in populator space.
    """

    BEAM_CATEGORY_NAMES = []
    INTERNAL_RULES = []
    EXTERNAL_RULES = []
    BOUNDARY_TYPE = AgentBoundaryType.NONE

    def __init__(self, params):
        # type: (PopulatorAgentConfig) -> None
        if params.joint_rule_overrides:
            self.internal_rules = self._apply_rule_overrides(self.INTERNAL_RULES, params.joint_rule_overrides)
            self.external_rules = self._apply_rule_overrides(self.EXTERNAL_RULES, params.joint_rule_overrides)
        else:
            self.internal_rules = list(self.INTERNAL_RULES)
            self.external_rules = list(self.EXTERNAL_RULES)
        # Copy so that per-agent overrides in generate_elements (e.g. RecessPopulatorAgent
        # setting beam_dimensions["recess"]) do not mutate the shared config dict.
        self.beam_dimensions: dict[str, tuple[float, float]] = dict(params.beam_dimensions)
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

    @abstractmethod
    def elements_for_layer(self, layer):
        """Return the elements this agent has placed on *layer*.

        Parameters
        ----------
        layer : :class:`~timber_design.populators.Layer`

        Returns
        -------
        list
        """
        raise NotImplementedError

    @abstractmethod
    def set_elements_for_layer(self, layer, elements):
        """Replace this agent's element list for *layer*.

        Parameters
        ----------
        layer : :class:`~timber_design.populators.Layer`
        elements : list
        """
        raise NotImplementedError

    def _apply_rule_overrides(self, base_rules: list[CategoryRule], overrides: list[CategoryRule]) -> list[CategoryRule]:
        """Return a copy of *base_rules* with matching *overrides* applied.

        For each override:

        - If the override's category pair matches an existing rule in
          *base_rules* (respecting order for T/EDGE_FACE topologies), the
          existing rule is replaced.
        - If no match is found, the override is appended.

        Parameters
        ----------
        base_rules : list[:class:`~timber_design.workflow.CategoryRule`]
            Either :attr:`INTERNAL_RULES` or :attr:`EXTERNAL_RULES`.
        overrides : list[:class:`~timber_design.workflow.CategoryRule`]
            The per-instance overrides from
            :attr:`LayerAgentConfig.joint_rule_overrides`.

        Returns
        -------
        list[:class:`~timber_design.workflow.CategoryRule`]
        """
        # NOTE: this is a bit of a breach of encapsulation, but necessary to allow for rule overrides
        # TODO: if we're only working with category rules here then make it explicit, if not, find a way to use the public interface of JointRule
        rules = list(base_rules)
        for override in overrides:
            for i, rule in enumerate(rules):
                if rule.category_a not in self.BEAM_CATEGORY_NAMES or rule.category_b not in self.BEAM_CATEGORY_NAMES:
                    continue
                # element order matters for T and EDGE_FACE topologies
                if rule.joint_type.supported_topology == JointTopology.TOPO_T or rule.joint_type.supported_topology == JointTopology.TOPO_EDGE_FACE:
                    if override.category_a == rule.category_a and override.category_b == rule.category_b:
                        rules[i] = override
                        break
                else:
                    if set([override.category_a, override.category_b]) == set([rule.category_a, rule.category_b]):
                        rules[i] = override
                        break
            else:
                rules.append(override)
        return rules


    def beam_from_category(self, centerline: Line, category: str, layer: Optional[Layer] = None, **kwargs) -> Beam2D:
        """Creates a :class:`~timber_design.populators.Beam2D` from a centerline and a category.

        Parameters
        ----------
        centerline : :class:`compas.geometry.Line`
            The centerline to create the beam from.
        category : str
            The category of the beam, which determines its dimensions.
        layer : :class:`~timber_design.populators.Layer`, optional
            When provided, the beam height is taken from ``layer.thickness``
            instead of ``self.beam_dimensions[category][1]``.  Useful for
            :class:`FeatureAgent` instances that create beams in other layers
            whose thicknesses are not known when :meth:`resolve_beam_dimensions`
            is called.
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
        height = layer.thickness if layer is not None else self.beam_dimensions[category][1]
        beam = Beam2D.from_centerline(centerline, width=width, height=height, z_vector=Vector(0, 0, 1))
        for key, value in kwargs.items():
            beam.attributes[key] = value
        beam.attributes["category"] = category
        if beam is None:
            raise ValueError("Failed to create beam from centerline: {}".format(centerline))
        return beam

    def get_direct_rule_from_elements(self, element_a: TimberElement, element_b: TimberElement, **kwargs) -> Union[DirectRule, None]:
        """Look up the within-agent joint rule for *element_a* / *element_b*.

        Searches :attr:`internal_rules` for a :class:`~timber_design.workflow.CategoryRule`
        whose category pair matches the two elements.  Returns ``None`` when no
        rule applies.
        """
        matching_rules = [r for r in self.internal_rules if set([r.category_a, r.category_b]) == set([element_a.attributes["category"], element_b.attributes["category"]])]
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
        if self.BOUNDARY_TYPE == AgentBoundaryType.NONE:
            return False
        if self.outline is None:
            return False
        is_inside = is_point_in_polyline(point, self.outline, in_plane=False)
        if self.BOUNDARY_TYPE == AgentBoundaryType.EXCLUSIVE and is_inside:
            return True
        if self.BOUNDARY_TYPE == AgentBoundaryType.INCLUSIVE and not is_inside:
            return True

    def trim_plate(self, plate: Plate) -> None:
        """Apply the agent to the plate based on the populator agent."""
        return [plate]

    def trim_beam(
        self,
        beam: Beam2D,
        skip_notches: Optional[bool] = True,
        skip_laps: Optional[bool] = True,
    ) -> list[Beam2D]:
        """Splits the beam at the agent's boundary outline and returns the resulting segments."""
        if self.BOUNDARY_TYPE == AgentBoundaryType.NONE:
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

    def _agent_layers(self):
        """Return the layers this agent is directly registered on.

        Overridden by :class:`LayerAgent` (returns ``[self.layer]``) and
        :class:`FeatureAgent` (returns ``self.registered_layers``).
        """
        return []

    def is_on_layer(self, layer):
        """Return ``True`` if this agent operates on *layer* or any ancestor/descendant.

        Checks whether any of the agent's registered layers is *layer* itself,
        an ancestor of *layer*, or a descendant of *layer*.

        Parameters
        ----------
        layer : :class:`~timber_design.populators.Layer`

        Returns
        -------
        bool
        """
        for agent_layer in self._agent_layers():
            if agent_layer is layer:
                return True
            # layer is an ancestor of agent_layer?
            current = agent_layer.parent_layer
            while current is not None:
                if current is layer:
                    return True
                current = current.parent_layer
            # layer is a descendant of agent_layer?
            for desc in agent_layer.iter_subtree():
                if desc is layer:
                    return True
        return False

    def create_joint_candidates(self):
        """Return joint candidates for overlapping beam pairs within this agent.

        Subclasses override this to iterate the appropriate element collection.
        The base implementation iterates ``self.elements`` directly, which is
        correct for :class:`LayerAgent`.  :class:`FeatureAgent` overrides it
        to iterate ``_elements_by_layer`` per layer.
        """
        candidates = []
        solver = ConnectionSolver2D()
        beam_elements = [e for e in self.elements if isinstance(e, Beam2D)]
        pairs = solver.find_intersecting_pairs(beam_elements)
        for element_a, element_b in pairs:
            topo_result = solver.find_topology(element_a, element_b)
            if topo_result is not None:
                candidate = JointCandidate(topo_result.beam_a, topo_result.beam_b, distance=topo_result.distance, topology=topo_result.topology, location=topo_result.location)
                candidates.append(candidate)
        return candidates

    

    def trim_agent_elements(self, other_agent, layer):
        """Punch the opening contour through plates on *other_agent*'s layer.

        When :attr:`~FeatureAgent.trimming_layers` is non-empty, only agents
        whose layer is in that list receive the contour cut.  Otherwise the
        cut is applied to all plate elements in *other_agent* (full-panel
        cross-section behaviour).

        Parameters
        ----------
        other_agent : :class:`~timber_design.populators.LayerAgent`
            The agent whose plate elements receive the opening contour cut.
        """
        trimmed_elements = []
        for element in other_agent.elements_for_layer(layer):
            if element.is_plate:
                trimmed_elements.extend(self.trim_plate(element))
            if element.is_beam:
                trimmed_elements.extend(self.trim_beam(element))
        other_agent.set_elements_for_layer(layer, trimmed_elements)
        

    @abstractmethod
    def generate_elements(self):
        """Generate all elements for this agent's layer."""
        raise NotImplementedError("generate_elements method must be implemented in subclasses of LayerAgent")

    @abstractmethod
    def trim_elements(self):
        """Trim all elements for this agent."""
        raise NotImplementedError("generate_elements method must be implemented in subclasses of PopulatorAgent")

    def extend_elements(self) -> None:
        pass

    def create_joint_defs(self) -> list[DirectRule]:
        """Return :class:`~timber_design.workflow.DirectRule` objects for element pairs within this agent.

        Parameters
        ----------
        model : :class:`~compas_timber.model.TimberModel`
        elements : list, optional
            Restrict joint detection to this element subset.  Forwarded
            directly to :meth:`create_joint_candidates`; see its docstring.
        """
        for candidate in self.create_joint_candidates():
            rule = self.get_direct_rule_from_elements(candidate.element_a, candidate.element_b)
            if rule is not None:
                self.joint_defs.append(rule)
