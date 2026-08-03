from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from typing import TYPE_CHECKING
from typing import Optional

from compas.data import Data
from compas.data.data import D
from compas.geometry import Line
from compas.geometry import Vector
from compas.itertools import pairwise
from compas_timber.connections import JointTopology
from compas_timber.elements import Plate
from compas_timber.utils import StrEnum
from compas_timber.utils import is_point_in_polyline

from timber_design.connections_2d.beam2d import Beam2D
from timber_design.connections_2d.connection_solver_2d import Beam2DPolylineIntersectionResult
from timber_design.connections_2d.connection_solver_2d import ConnectionSolver2D
from timber_design.workflow import CategoryRule, TopologyRule
from timber_design.workflow import CompositeRule
from timber_design.workflow import JointRuleSolver

if TYPE_CHECKING:
    from compas.geometry import Polyline  # noqa: F401
    from compas_timber.connections import Cluster  # noqa: F401
    from compas_timber.elements import Layer  # noqa: F401


class AgentBoundaryType(StrEnum):
    """Controls how an agent's outline is used to include or exclude beam segments.

    Each concrete :class:`PopulatorAgent` declares a ``BOUNDARY_TYPE`` class
    attribute that governs what :meth:`~PopulatorAgent.cull_beam` does with
    segments whose midpoints fall inside or outside the agent's boundary
    outline on a layer.

    Attributes
    ----------
    NONE : str
        No boundary culling — all segments are kept regardless of the outline.
        Used by agents whose elements span the full panel (studs, plates).
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

    An agent is a stateless-by-design computational unit responsible for one
    logical group of framing elements within a panel (edge beams, studs,
    plates, opening surround, …).  Agents do not hold references to the
    populator's model and never touch elements owned by other agents; the
    :class:`~timber_design.populators.PanelPopulator` owns the model, tracks
    element ownership via each element's ``attributes["agent"]`` tag, and
    passes agents the element lists they need as arguments.

    An agent provides:

    - :meth:`generate_elements` — create this agent's elements, returned per
      layer for the populator to add to the model.
    - :meth:`define_outlines` / :meth:`outline_for_layer` — the agent's
      boundary outline per layer, used for trimming peer elements.
    - :meth:`split_beam` / :meth:`cull_beam` / :meth:`trim_plate` — pure
      per-element geometry decisions against this agent's boundary.
    - :meth:`joint_rules_for_cluster` — the joint rules applicable to a
      candidate cluster, selected from the internal/external/cluster rule sets.

    Class-level attributes
    ----------------------
    BEAM_CATEGORY_NAMES : list[str]
        The beam categories this agent can create.  Used by
        :meth:`~timber_design.populators.PanelPopulator.resolve_beam_widths`.
    INTERNAL_JOINT_RULES : list[:class:`~timber_design.workflow.CategoryRule`]
        Default joint rules for **within-agent** pairs — elements that belong
        to this agent and are joined to each other.
        Overridable per-instance via ``internal_joint_overrides``.
    EXTERNAL_JOINT_RULES : list[:class:`~timber_design.workflow.CategoryRule`]
        Default joint rules for **cross-agent** pairs — elements from this
        agent that are joined to elements from a different agent.
        Overridable per-instance via ``external_joint_overrides``.
    COMPOSITE_RULES : list[:class:`~timber_design.workflow.CompositeRule`]
        Rules tried for a joint cluster of 3+ elements that this agent has any
        element in — see :meth:`~timber_design.populators.PanelPopulator._join_cluster`.
        Not instance-overridable.
    BOUNDARY_TYPE : :class:`AgentBoundaryType`
        Controls how the agent's outline is used during trimming.
        Defaults to :attr:`AgentBoundaryType.NONE`.

    Parameters
    ----------
    internal_joint_overrides : list[:class:`~timber_design.workflow.CategoryRule`], optional
        Overrides merged into :attr:`INTERNAL_JOINT_RULES` to form
        :attr:`internal_rules`.
    external_joint_overrides : list[:class:`~timber_design.workflow.CategoryRule`], optional
        Overrides merged into :attr:`EXTERNAL_JOINT_RULES` to form
        :attr:`external_rules`.

    Attributes
    ----------
    key : str or None
        Stable, human-readable ownership key assigned by the populator
        (see :meth:`~timber_design.populators.PanelPopulator._assign_agent_keys`).
        Written into every generated element's ``attributes["agent"]``.
    beam_widths : dict[str, float]
        ``{category: width}`` mapping, resolved by the config / populator
        before generation.  Beam height is always the layer thickness.
    internal_rules : list[:class:`~timber_design.workflow.CategoryRule`]
        Active within-agent joint rules.
    external_rules : list[:class:`~timber_design.workflow.CategoryRule`]
        Active cross-agent joint rules.
    outline_by_layer : dict[:class:`~compas_timber.elements.Layer`, :class:`~compas.geometry.Polyline` or None]
        This agent's boundary outline per layer.  Filled during
        :meth:`generate_elements` for framing layers and by
        :meth:`define_outlines` for every other layer the agent trims.
    """

    BEAM_CATEGORY_NAMES: list[str] = []
    INTERNAL_JOINT_RULES: list[CategoryRule] = []
    EXTERNAL_JOINT_RULES: list[CategoryRule] = []
    COMPOSITE_RULES: list[CompositeRule] = []
    BOUNDARY_TYPE = AgentBoundaryType.NONE

    def __init__(self, internal_joint_overrides=None, external_joint_overrides=None, composite_joint_overrides=None):
        super().__init__()
        self.key: Optional[str] = None
        self.beam_widths: dict[str, float] = {}
        self.internal_rules = self._apply_overrides(self.INTERNAL_JOINT_RULES, internal_joint_overrides)
        self.external_rules = self._apply_overrides(self.EXTERNAL_JOINT_RULES, external_joint_overrides)
        self.composite_rules = self._apply_overrides(self.COMPOSITE_RULES, composite_joint_overrides)
        self.outline_by_layer = {}

    def merge_overrides(class_rules, overrides):
        """Return a new rule list: *class_rules* with *overrides* applied.
        See :meth:`_apply_overrides` for the merge logic.
        """
        return PopulatorAgent._apply_overrides(class_rules, overrides)


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
        """Return all elements generated by this agent."""
        elements = []
        for l in self.element_layers:
            elements.extend(self.elements_for_layer(l))


    def elements_for_layer(self,layer):
        """Return this agent's elements on *layer*, or an empty list."""
        return [e for e in layer.children if not isinstance(e, Layer) and e.attributes.get("agent") == self]


    # ------------------------------------------------------------------
    # Element generation
    # ------------------------------------------------------------------

    @abstractmethod
    def generate_elements(self):
        """Create this agent's elements, grouped per layer.

        Implementations must also record the agent's boundary outline for every
        framing layer in :attr:`outline_by_layer` (an explicit ``None`` marks a
        layer without a boundary).  The populator adds the returned elements to
        its model — agents never store element lists themselves.

        Returns
        -------
        dict[:class:`~compas_timber.elements.Layer`, list[:class:`~timber_design.populators.Beam2D` | :class:`~compas_timber.elements.Plate`]]
            The generated elements per framing layer.
        """
        raise NotImplementedError

    def beam_from_category(self, centerline: Line, category: str, layer: "Layer", **kwargs) -> Beam2D:
        """Create a :class:`~timber_design.populators.Beam2D` from a centreline and category.

        The beam width comes from :attr:`beam_widths` (filled by the config /
        populator before generation).  The beam height is always taken from
        ``layer.thickness`` — it is never stored in the agent.

        Parameters
        ----------
        centerline : :class:`compas.geometry.Line`
            The centreline of the beam.
        category : str
            Beam category; must be present in :attr:`beam_widths`.
        layer : :class:`~compas_timber.elements.Layer`
            The layer the beam belongs to.  Its thickness is used as the beam
            height.  :class:`~timber_design.populators.LayerAgent` subclasses
            automatically pass their own layer when the argument is omitted.
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

    def repoint_to_layer_tree(self, tree):
        """Rebind this agent to the current panel layer tree. No-op for agents with no layer refs."""
        pass

    # ------------------------------------------------------------------
    # Boundary outlines
    # ------------------------------------------------------------------

    def compute_outline_for_layer(self, layer):
        """Return this agent's boundary outline on *layer*, or ``None`` for no boundary.

        Called by :meth:`define_outlines` for layers the agent trims but does
        not frame on.  The base implementation has no boundary anywhere.

        Returns
        -------
        :class:`~compas.geometry.Polyline` or None
        """
        return None

    def define_outlines(self, layers):
        """Explicitly record this agent's boundary outline for every layer in *layers*.

        Layers already present in :attr:`outline_by_layer` (filled during
        :meth:`generate_elements`) are left untouched; every other layer gets
        the result of :meth:`compute_outline_for_layer` — including an explicit
        ``None`` for layers where the agent has no boundary.  After this call,
        :meth:`outline_for_layer` is defined for every layer the agent acts on;
        the populator never computes or backfills outlines itself.

        Parameters
        ----------
        layers : list[:class:`~compas_timber.elements.Layer`]
            All layers this agent frames on or trims (including sublayers),
            as determined by the populator.
        """
        for layer in layers:
            if layer not in self.outline_by_layer:
                self.outline_by_layer[layer] = self.compute_outline_for_layer(layer)

    def outline_for_layer(self, layer):
        """Return this agent's boundary outline on *layer*, or ``None``.

        Returns
        -------
        :class:`~compas.geometry.Polyline` or None
        """
        return self.outline_by_layer.get(layer)

    # ------------------------------------------------------------------
    # Per-element trimming decisions
    # ------------------------------------------------------------------

    def split_element(self, element, layer=None) -> list:
        if isinstance(element, Beam2D):
            return self.split_beam(element, layer)
        else:
            return self.trim_plate(element, layer)


    def split_beam(self, beam: Beam2D, layer=None) -> list[Beam2D]:
        """Split *beam* at this agent's outline boundary and return all resulting segments.

        No culling is applied — every segment produced by outline crossings is
        returned.  The populator applies :meth:`cull_beam` in a separate pass
        to discard out-of-zone segments.

        Breakpoints are taken directly from each crossing's own ``start_dot``/
        ``end_dot`` — *not* by sorting whole crossings and pairing adjacent
        ones by their combined ``min``/``max`` — because a single crossing can
        legitimately have a wide (non point-like) span: e.g. a stud/king-stud
        that reaches a panel corner, where the boundary enters the beam blank
        through one face and leaves through another several beam-widths away.
        Every segment bounded by two consecutive breakpoints is a candidate;
        :meth:`cull_beam` decides afterwards — via each candidate's own
        midpoint — which ones actually belong to this agent's zone.

        Returns
        -------
        list[:class:`~timber_design.populators.Beam2D`]
            ``[beam]`` (the untouched original) when the agent has no boundary
            on *layer* or the boundary does not cross the beam.
        """
        outline = self.outline_for_layer(layer)
        if self.BOUNDARY_TYPE == AgentBoundaryType.NONE or outline is None:
            return [beam]

        intersections = ConnectionSolver2D.intersection_beam2d_polyline(beam, outline)
        if not intersections:
            return [beam]

        # Add pseudo-crossings at start and end so end segments are included.
        intersections.extend(
            [
                Beam2DPolylineIntersectionResult(start_dot=0.0),
                Beam2DPolylineIntersectionResult(end_dot=beam.length),
            ]
        )
        intersections.sort(key=lambda x: x.average_dot)

        segments = []
        for pair in pairwise(intersections):
            seg_start = min(pair[0].all_dots)
            seg_end = max(pair[1].all_dots)
            if seg_end - seg_start < 0.000001:
                continue
            segments.append(beam.get_beam_segment(seg_start, seg_end))
        return segments

    def cull_beam(self, beam: Beam2D) -> bool:
        """Return ``True`` if *beam* should be removed by this agent on *layer*.

        Checks the midpoint-in-zone test (:meth:`cull_element_at_point`) and
        any agent-specific override (:meth:`cull_beam_segment`).

        Parameters
        ----------
        beam : :class:`~timber_design.populators.Beam2D`
            A peer agent's beam (or beam segment) on *layer*.
        layer : :class:`~compas_timber.elements.Layer`, optional
            The layer the decision applies to.
        own_elements : list, optional
            This agent's own elements on *layer*, supplied by the populator.
            Used by agent-specific culls (e.g. studs coinciding with king studs).
        """
        layer = beam.attributes.get("layer", None)
        if not layer:
            raise ValueError("Beam missing layer reference in attributes: {!r}".format(beam))
        return bool(self.cull_element_at_point(beam.centerline.midpoint, layer) or self.cull_beam_segment(beam))

    def cull_beam_segment(self, beam: Beam2D) -> bool:
        """Agent-specific cull hook; the base implementation never culls.

        Parameters
        ----------
        beam : :class:`~timber_design.populators.Beam2D`
        layer : :class:`~compas_timber.elements.Layer`, optional
        own_elements : list, optional
            This agent's own elements on *layer*, supplied by the populator.
        """
        return False

    def cull_element_at_point(self, point, layer=None) -> bool:
        """Return ``True`` if an element whose midpoint is at *point* falls in this agent's cull zone."""
        if self.BOUNDARY_TYPE == AgentBoundaryType.NONE:
            return False
        outline = self.outline_for_layer(layer)
        if outline is None:
            return False
        is_inside = is_point_in_polyline(point, outline, in_plane=False)
        if self.BOUNDARY_TYPE == AgentBoundaryType.EXCLUSIVE:
            return is_inside
        return not is_inside  # AgentBoundaryType.INCLUSIVE

    def trim_plate(self, plate: Plate) -> None:
        """Apply this agent's boundary to *plate* in place; the base implementation does nothing."""
        pass

    # ------------------------------------------------------------------
    # Element extension
    # ------------------------------------------------------------------

    def extend_elements(self, boundary_outlines, layer) -> None:
        """Extend *own_elements* on *layer* toward *boundary_outlines*; no-op by default.

        Parameters
        ----------
        own_elements : list[:class:`~timber_design.populators.Beam2D`]
            This agent's own elements on *layer*, supplied by the populator.
        boundary_outlines : list[:class:`~compas.geometry.Polyline`]
            Boundary outlines of peer agents on *layer* (``None`` entries
            already filtered out by the populator).
        layer : :class:`~compas_timber.elements.Layer`
            The layer the extension applies to.
        """
        pass

    # ------------------------------------------------------------------
    # Joint rules
    # ------------------------------------------------------------------

    def get_cluster_joint(self, cluster, max_distance=None):
        if not any(e in self.elements for e in cluster.elements): 
            return None
        if len(cluster.elements) >= 3:
            rules = self.composite_rules
        if all(e in self.elements for e in cluster.elements):
            rules = self.internal_rules
        rules = self.external_rules
        for rule in rules:
            joint = rule.create_instance(cluster, max_distance=max_distance)
        return joint


    @staticmethod
    def _apply_overrides(base_rules: list[CategoryRule], overrides: Optional[list[CategoryRule]]) -> list[CategoryRule]:
        """Return a new rule list: *base_rules* with *overrides* applied.

        Only the agent's *own* constructor overrides pass through here.
        Panel-level rules given to
        :class:`~timber_design.populators.PanelPopulator` are never merged into
        an agent — the populator keeps them and tries them itself once an
        agent's rules have failed on a cluster.

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
        in the category-based replace logic — anything else (e.g. a
        :class:`~timber_design.workflow.CompositeRule`) has no ``category_a``/
        ``category_b`` to compare, so it is appended rather than matched.

        The class-level :attr:`INTERNAL_JOINT_RULES` / :attr:`EXTERNAL_JOINT_RULES`
        are never mutated — a fresh list is always returned.

        Parameters
        ----------
        base_rules : list[:class:`~timber_design.workflow.CategoryRule`]
            Either :attr:`INTERNAL_JOINT_RULES` or :attr:`EXTERNAL_JOINT_RULES`.
        overrides : list[:class:`~timber_design.workflow.CategoryRule`] or None
            Per-agent overrides from ``internal_joint_overrides`` /
            ``external_joint_overrides``.
        """
        rules = list(base_rules)
        if not overrides:
            return rules
        for override in overrides:
            if isinstance(override, TopologyRule):
                for i, rule in enumerate(rules):
                    if isinstance(rule, TopologyRule) and rule.topology_type == override.topology_type:
                        rules[i] = override
                        break
                else:
                    rules.append(override)
                continue

            if isinstance(override, CategoryRule):
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
