from abc import ABC
from abc import abstractmethod
from typing import Optional
from typing import Union

from compas.data import Data
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
from timber_design.populators.connection_solver_2d import aabb_overlap
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


class PopulatorAgent(Data, ABC):
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
    - :attr:`beam_widths` — ``{category: width}`` filled by the factory method
      (*get_agent_from_layer* / *get_agent_from_feature*) just before the agent
      is constructed.  Beam height is always taken from ``layer.thickness``.

    Class-level attributes
    ----------------------
    BEAM_CATEGORY_NAMES : list[str]
        The beam categories this agent can create.  Used by
        :meth:`resolve_beam_widths`.
    INTERNAL_JOINT_RULES : list[:class:`~timber_design.workflow.CategoryRule`]
        Default joint rules for **within-agent** pairs — elements that belong
        to this agent and are joined to each other.  Used by
        :meth:`create_joint_defs` / :meth:`get_direct_rule_from_elements`.
        Overridable per-instance via the config's ``internal_joint_overrides``.
    EXTERNAL_JOINT_RULES : list[:class:`~timber_design.workflow.CategoryRule`]
        Default joint rules for **cross-agent** pairs — elements from this
        agent that are joined to elements from a different agent.  Used by
        :meth:`~timber_design.populators.PanelPopulator.create_cross_agent_joints`.
        Overridable per-instance via the config's ``external_joint_overrides``.
    BOUNDARY_TYPE : :class:`FeatureBoundaryType`
        Controls how the agent's outline is used during trimming.
        Defaults to :attr:`~FeatureBoundaryType.NONE`.

    Parameters
    ----------
    beam_widths : dict[str, float], optional
        ``{category: width}`` mapping, fully resolved by the config before
        construction.
    internal_joint_overrides : list[:class:`~timber_design.workflow.CategoryRule`], optional
        Overrides merged into :attr:`INTERNAL_JOINT_RULES` to form
        :attr:`internal_rules`.
    external_joint_overrides : list[:class:`~timber_design.workflow.CategoryRule`], optional
        Overrides merged into :attr:`EXTERNAL_JOINT_RULES` to form
        :attr:`external_rules`.

    Attributes
    ----------
    beam_widths : dict[str, float]
        ``{category: width}`` mapping passed in by the config.  Beam height is
        always ``layer.thickness``.
    joint_defs : list[:class:`~timber_design.workflow.DirectRule`]
        Accumulated joint definitions, populated by :meth:`create_joint_defs`.
    aabb : :class:`~timber_design.populators.AABB2D` or None
        2D bounding box enclosing all elements in this agent.
    """

    BEAM_CATEGORY_NAMES = []
    INTERNAL_JOINT_RULES: list[CategoryRule] = []
    EXTERNAL_JOINT_RULES: list[CategoryRule] = []
    BOUNDARY_TYPE = AgentBoundaryType.NONE

    def __init__(self, internal_joint_overrides=None, external_joint_overrides=None):
        # type: (Optional[list], Optional[list]) -> None
        # Initialise the compas ``Data`` base so ``guid`` / ``name`` exist and the
        # agent participates in COMPAS JSON serialization (json_dump / json_load).
        super().__init__()
        # ``beam_widths`` starts empty; concrete subclasses populate it from their
        # explicit per-category constructor kwargs (e.g. ``edge_stud_width``,
        # ``stud_width``).
        self.beam_widths: dict[str, float] = {}
        self.internal_rules = self._apply_overrides(self.INTERNAL_JOINT_RULES, internal_joint_overrides)
        self.external_rules = self._apply_overrides(self.EXTERNAL_JOINT_RULES, external_joint_overrides)
        # Raw overrides kept separately from the merged rule lists: ``external_overrides``
        # so cross-agent joint resolution can give a per-agent override precedence over
        # *another* agent's base rule for the same pair regardless of agent ordering,
        # and both so ``__data__`` can round-trip the agent through its constructor.
        self.internal_overrides = list(internal_joint_overrides) if internal_joint_overrides else []
        self.external_overrides = list(external_joint_overrides) if external_joint_overrides else []
        self.joint_defs = []
        self.elements = []
        self.outline = None

    @property
    def __data__(self):
        """Serializable construction state.

        Keys match the constructor parameters, so an agent round-trips through
        ``type(agent)(**agent.__data__)``.  Subclasses extend this with their own
        per-category widths (read back out of :attr:`beam_widths`) and parameters.
        """
        return {
            "internal_joint_overrides": self.internal_overrides or None,
            "external_joint_overrides": self.external_overrides or None,
        }

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

    def elements_for_layer(self, layer):
        """Return the elements this agent has placed on *layer*.

        Single-layer agents (every :class:`LayerAgent`) hold one flat element
        list and ignore *layer*.  :class:`FeatureAgent` overrides this to return
        the elements bucketed under that layer.

        Parameters
        ----------
        layer : :class:`~timber_design.populators.Layer`

        Returns
        -------
        list
        """
        return self.elements

    def set_elements_for_layer(self, layer, elements):
        """Replace this agent's element list for *layer*.

        Single-layer agents replace the whole flat list; :class:`FeatureAgent`
        overrides this to update only the bucket for *layer*.

        Parameters
        ----------
        layer : :class:`~timber_design.populators.Layer`
        elements : list
        """
        self.elements = elements

    @staticmethod
    def _apply_overrides(base_rules: list[CategoryRule], overrides: Optional[list[CategoryRule]]) -> list[CategoryRule]:
        """Return a new rule list: *base_rules* with *overrides* applied.

        For each override, an existing rule is *replaced* only when **both**:

        - it targets the same :attr:`~CategoryRule.joint_type.SUPPORTED_TOPOLOGY`, and
        - its categories match.  T-joints and edge-face plate joints compare
          categories in order (the ``(a,b)`` and ``(b,a)`` variants are kept as
          distinct rules because main/cross differs); other topologies match by
          unordered pair.

        Otherwise the override is appended, so the same ordered category pair
        may carry multiple rules as long as their topologies differ (e.g. a
        ``TButtJoint`` and an ``LButtJoint`` for ``(stud, top_plate_beam)``).

        The class-level :attr:`INTERNAL_JOINT_RULES` / :attr:`EXTERNAL_JOINT_RULES`
        are never mutated — a fresh list is always returned.

        Parameters
        ----------
        base_rules : list[:class:`~timber_design.workflow.CategoryRule`]
            Either :attr:`INTERNAL_JOINT_RULES` or :attr:`EXTERNAL_JOINT_RULES`.
        overrides : list[:class:`~timber_design.workflow.CategoryRule`] or None
            Per-agent overrides from the config's ``internal_joint_overrides``
            / ``external_joint_overrides``.
        """
        rules = list(base_rules)
        if not overrides:
            return rules
        for override in overrides:
            topo = override.joint_type.SUPPORTED_TOPOLOGY
            order_sensitive = topo in (JointTopology.TOPO_T, JointTopology.TOPO_EDGE_FACE)
            for i, rule in enumerate(rules):
                if rule.joint_type.SUPPORTED_TOPOLOGY != topo:
                    continue
                if order_sensitive:
                    if rule.category_a == override.category_a and rule.category_b == override.category_b:
                        rules[i] = override
                        break
                else:
                    if {rule.category_a, rule.category_b} == {override.category_a, override.category_b}:
                        rules[i] = override
                        break
            else:
                rules.append(override)
        return rules

    def beam_from_category(self, centerline: Line, category: str, layer: "Layer", **kwargs) -> Beam2D:
        """Create a :class:`~timber_design.populators.Beam2D` from a centreline and category.

        The beam width comes from :attr:`beam_widths` (filled by the factory
        method before the agent is constructed).  The beam height is always taken from
        ``layer.thickness`` — it is never stored in the agent.

        Parameters
        ----------
        centerline : :class:`compas.geometry.Line`
            The centreline of the beam.
        category : str
            Beam category; must be present in :attr:`beam_widths`.
        layer : :class:`~timber_design.populators.Layer`
            The layer the beam belongs to.  Its :attr:`~Layer.thickness` is
            used as the beam height.  :class:`LayerAgent` subclasses
            automatically pass ``self.layer`` when the argument is omitted
            (see :meth:`LayerAgent.beam_from_category`).
        kwargs : dict, optional
            Extra key/value pairs stored as ``beam.attributes``.

        Returns
        -------
        :class:`~timber_design.populators.Beam2D`
        """
        if category not in self.beam_widths:
            raise ValueError("Unknown beam category: {!r}".format(category))
        width = self.beam_widths[category]
        height = layer.thickness
        beam = Beam2D.from_centerline(centerline, width=width, height=height, z_vector=Vector(0, 0, 1))
        for key, value in kwargs.items():
            beam.attributes[key] = value
        beam.attributes["category"] = category
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

    def outline_for_layer(self, layer):
        """Return the boundary outline that applies on *layer*.

        Single-layer agents (every :class:`LayerAgent`) have one boundary, so
        the base implementation ignores *layer* and returns :attr:`outline`.
        Multi-layer agents (:class:`FeatureAgent`) override this to return the
        outline they generated on each specific layer, so trimming/culling on
        one layer never uses another layer's boundary.
        """
        return self.outline

    def cull_element_at_point(self, point, layer=None) -> bool:
        """Determines whether an element at the given point should be culled by the populator agent."""
        outline = self.outline_for_layer(layer)
        if self.BOUNDARY_TYPE == AgentBoundaryType.NONE:
            return False
        if outline is None:
            return False
        is_inside = is_point_in_polyline(point, outline, in_plane=False)
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
        layer=None,
        skip_notches: Optional[bool] = True,
        skip_laps: Optional[bool] = True,
    ) -> list[Beam2D]:
        """Split *beam* at this agent's boundary on *layer* and return the surviving segments."""
        outline = self.outline_for_layer(layer)
        if self.BOUNDARY_TYPE == AgentBoundaryType.NONE:
            return [beam]
        if outline is None:
            return [beam]

        crossings = find_beam_outline_crossings(beam, outline, skip_notches=skip_notches, skip_laps=skip_laps)
        if not crossings:
            # No outline crossings — keep or cull the whole beam, preserving object identity.
            # cull_element_at_point handles the in/out-of-boundary test; cull_beam_segment
            # handles agent-specific culls (e.g. studs overlapping an opening's king/jack
            # studs) that are independent of the boundary outline.
            if self.cull_element_at_point(beam.centerline.midpoint, layer) or self.cull_beam_segment(beam):
                return []
            return [beam]

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
            if self.cull_element_at_point(beam_seg.centerline.midpoint, layer):
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

    def trim_agent_elements(self, other_agent):
        """Trim *other_agent*'s elements **on *layer*** against this agent's boundary.

        Each of the peer's elements on that layer is cut by this agent's
        boundary (plates via :meth:`trim_plate`, beams via :meth:`trim_beam`),
        and the surviving segments are written back with
        :meth:`set_elements_for_layer`.

        Parameters
        ----------
        other_agent : :class:`~timber_design.populators.PopulatorAgent`
            The peer whose elements on *layer* receive the cut.
        layer : :class:`~timber_design.populators.Layer`
            The layer whose elements are trimmed.
        """
        trimmed_elements = []
        trimming_layers = set(self.trimming_layers, other_agent.element_layers)
        for layer in trimming_layers:
            for element in other_agent.elements_for_layer(layer):
                if element.is_plate:
                    trimmed_elements.extend(self.trim_plate(element))
                if element.is_beam:
                    trimmed_elements.extend(self.trim_beam(element, layer))
        other_agent.set_elements_for_layer(layer, trimmed_elements)

    @abstractmethod
    def generate_elements(self):
        """Generate all elements for this agent's layer."""
        for layer in self.element_layers:
            self.outline = None
            layer_elements, layer_outline = self.generate_elements_for_layer(layer)
            self.elements_by_layer[layer] = layer_elements  # add to per-layer dict
            self.outline_by_layer[layer] = layer_outline  # capture per-layer boundary


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
