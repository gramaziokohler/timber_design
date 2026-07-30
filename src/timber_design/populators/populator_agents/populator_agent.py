from abc import ABC
from abc import abstractmethod
from typing import Optional
from typing import Union

from compas.data import Data
from compas.geometry import Line
from compas.geometry import Vector
from compas.itertools import pairwise
from compas_timber.base import TimberElement
from compas_timber.connections import JointTopology
from compas_timber.elements import Plate
from compas_timber.utils import is_point_in_polyline

from timber_design.connections_2d.beam2d import AABB2D
from timber_design.connections_2d.beam2d import Beam2D
from timber_design.connections_2d.connection_solver_2d import Beam2DPolylineIntersectionResult
from timber_design.connections_2d.connection_solver_2d import ConnectionSolver2D
from timber_design.connections_2d.connection_solver_2d import aabb_overlap
from timber_design.workflow import CategoryRule
from timber_design.workflow import CompositeRule
from timber_design.workflow import DirectRule
from timber_design.workflow import JointRuleSolver


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
        :class:`~timber_design.populators.EdgePopulatorAgent`.
    """

    EXCLUSIVE = "exclusive"
    INCLUSIVE = "inclusive"
    NONE = "none"


class PopulatorAgent(Data, ABC):
    """Abstract base class for all panel populator agents.

    A ``LayerAgent`` is responsible for one logical group of framing
    elements within a panel (edge beams, studs, plates, opening surround, …).
    Subclasses implement :meth:`generate_elements` and optionally override
    :meth:`extend_elements` and :meth:`cull_beam_segment`.

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
        :meth:`get_direct_rule_from_elements`.
        Overridable per-instance via the config's ``internal_joint_overrides``.
    EXTERNAL_JOINT_RULES : list[:class:`~timber_design.workflow.CategoryRule`]
        Default joint rules for **cross-agent** pairs — elements from this
        agent that are joined to elements from a different agent.  Used by
        :meth:`~timber_design.populators.PanelPopulator._resolve_pairwise`.
        Overridable per-instance via the config's ``external_joint_overrides``.
    CLUSTER_RULES : list[:class:`~timber_design.workflow.CompositeRule`]
        Rules tried first for a joint cluster of 3+ elements (2+ pairwise
        candidates) that this agent has any element in — see
        :meth:`~timber_design.populators.PanelPopulator._resolve_cluster`.
        Not instance-overridable (no matching ``*_overrides`` constructor arg).
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
    aabb : :class:`~timber_design.populators.AABB2D` or None
        2D bounding box enclosing all elements in this agent.
    """

    BEAM_CATEGORY_NAMES = []
    INTERNAL_JOINT_RULES: list[CategoryRule] = []
    EXTERNAL_JOINT_RULES: list[CategoryRule] = []
    CLUSTER_RULES: list[CompositeRule] = []
    BOUNDARY_TYPE = AgentBoundaryType.NONE

    def __init__(self, internal_joint_overrides=None, external_joint_overrides=None):
        super().__init__()
        self.beam_widths: dict[str, float] = {}
        self.internal_rules = self._apply_overrides(self.INTERNAL_JOINT_RULES, internal_joint_overrides)
        self.external_rules = self._apply_overrides(self.EXTERNAL_JOINT_RULES, external_joint_overrides)
        self.internal_overrides = list(internal_joint_overrides) if internal_joint_overrides else []
        self.external_overrides = list(external_joint_overrides) if external_joint_overrides else []
        self.elements_by_layer = {}
        self.outline_by_layer = {}

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
    def elements(self):
        return [e for lst in self.elements_by_layer.values() for e in lst]


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

        Only :class:`~timber_design.workflow.CategoryRule` instances participate
        in the category-based replace logic (both as *override* and as an
        existing entry in *base_rules*) — anything else (e.g. a
        :class:`~timber_design.workflow.CompositeRule` in :attr:`CLUSTER_RULES`,
        or one accidentally passed in as an override) has no ``category_a``/
        ``category_b`` to compare, so it's simply appended rather than matched.

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
            if not isinstance(override, CategoryRule):
                rules.append(override)
                continue
            topo = override.joint_type.SUPPORTED_TOPOLOGY
            order_sensitive = topo in (JointTopology.TOPO_T, JointTopology.TOPO_EDGE_FACE)
            for i, rule in enumerate(rules):
                if not isinstance(rule, CategoryRule) or rule.joint_type.SUPPORTED_TOPOLOGY != topo:
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


    def try_create_cluster_joint(self, model, cluster, max_distance=None):
        if len(cluster.elements) < 3:
            if all(e in self.elements for e in cluster.elements):
                rules = self.internal_rules
            else:  #only some of the elements are from this agent, so use the external rules
                rules = self.external_rules
        else:
            rules = self.CLUSTER_RULES
        jrs = JointRuleSolver(rules)
        return jrs.joints_from_rules_and_clusters(model, [cluster], pairwise_fallback=False, max_distance=max_distance)



    def cull_beam_segment(self, beam: Beam2D, layer=None) -> bool:
        """Determines whether the beam segment should be culled by the populator agent."""
        return False

    def outline_for_layer(self, layer):
        """Return this agent's boundary outline on *layer*, or ``None``.

        ``outline_by_layer`` is kept clean: an entry exists only where the agent
        explicitly defined an outline.  Layer agents define one only where they
        frame; feature agents (see :meth:`define_trimming_outlines`) define their
        footprint on every layer they frame *or* trim — including sublayers — so
        their beams are culled everywhere they act and ``None`` everywhere else.
        """
        return self.outline_by_layer.get(layer)


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

    def split_beam(self, beam: Beam2D, layer=None) -> list[Beam2D]:
        """Split *beam* at this agent's outline boundary and return all resulting segments.

        No culling is applied — every segment produced by outline crossings is
        returned.  Use :meth:`cull_beam` afterwards to discard out-of-zone
        segments, or call :meth:`trim_beam` which composes both steps.
        """
        outline = self.outline_for_layer(layer)
        if self.BOUNDARY_TYPE == AgentBoundaryType.NONE or outline is None:
            return [beam]

        intersections = ConnectionSolver2D.intersection_beam2d_polyline(beam, outline)
        if not intersections:
            return [beam]

        # add intersections at start and end to include end segments when splitting.
        intersections.extend([
            Beam2DPolylineIntersectionResult(start_dot=0.0),
            Beam2DPolylineIntersectionResult(end_dot=beam.length),
        ])
        intersections.sort(key=lambda x: x.average_dot)

        segments = []
        for pair in pairwise(intersections):
            seg_start = min(pair[0].all_dots)
            seg_end = max(pair[1].all_dots)
            # Skip degenerate segments.
            if seg_end - seg_start < 0.000001:
                continue
            segments.append(beam.get_beam_segment(seg_start, seg_end))
        return segments

    def cull_beam(self, beam: Beam2D, layer=None) -> bool:
        """Return ``True`` if *beam* should be removed by this agent on *layer*.

        Checks both the midpoint-in-zone test (:meth:`cull_element_at_point`)
        and any agent-specific override (:meth:`cull_beam_segment`).
        """
        return bool(
            self.cull_element_at_point(beam.centerline.midpoint, layer)
            or self.cull_beam_segment(beam, layer)
        )

    def split_agent_elements(self, other_agent, layer):
        """Split *other_agent*'s elements on *layer* at this agent's boundary (no culling).

        Each beam is split at outline crossings; all resulting segments are kept.
        Plates receive the agent's feature via :meth:`trim_plate` (which modifies
        them in-place rather than splitting).  Call :meth:`cull_agent_elements`
        in a second pass to discard out-of-zone segments.
        """
        result = []
        for element in other_agent.elements_by_layer.get(layer, []):
            if element.is_plate:
                result.extend(self.trim_plate(element))
            if element.is_beam:
                result.extend(self.split_beam(element, layer))
        other_agent.elements_by_layer[layer] = result

    def cull_agent_elements(self, other_agent, layer):
        """Remove *other_agent*'s elements on *layer* that this agent's zone would discard.

        Applies :meth:`cull_beam` to every beam; elements that return ``True``
        are dropped.  Non-beam elements (plates) are always kept — their trimming
        is handled geometrically by :meth:`split_agent_elements`.
        """
        other_agent.elements_by_layer[layer] = [
            element for element in other_agent.elements_by_layer.get(layer, [])
            if not (element.is_beam and self.cull_beam(element, layer))
        ]

    @abstractmethod
    def generate_elements(self):
        """Generate (and store) this agent's elements and optionally boundary outline.
        """
        raise NotImplementedError

    def repoint_to_layer_tree(self, tree):
        """Rebind this agent to the current panel layer tree. No-op for agents with no layer refs."""
        pass

    def extend_elements(self, layer_elements, layer) -> None:
        pass
