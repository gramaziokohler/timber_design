from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from typing import TYPE_CHECKING
from typing import Optional

from compas.data import Data
from compas.geometry import Line
from compas.geometry import Vector
from compas.itertools import pairwise
from compas_timber.connections import JointTopology
from compas_timber.elements import Layer
from compas_timber.elements import Plate
from compas_timber.utils import StrEnum
from compas_timber.utils import is_point_in_polyline

from timber_design.connections_2d.beam2d import Beam2D
from timber_design.connections_2d.connection_solver_2d import Beam2DPolylineIntersectionResult
from timber_design.connections_2d.connection_solver_2d import ConnectionSolver2D
from timber_design.workflow import CategoryRule
from timber_design.workflow import CompositeRule
from timber_design.workflow import JointRuleSolver
from timber_design.workflow import TopologyRule

if TYPE_CHECKING:
    from compas.geometry import Polyline  # noqa: F401
    from compas_timber.connections import Cluster  # noqa: F401


class AgentBoundaryType(StrEnum):
    """Controls how an agent's outline is used to include or exclude beam segments.

    Each concrete :class:`PopulatorAgent` declares a ``BOUNDARY_TYPE`` class
    attribute that governs what :meth:`~PopulatorAgent.cull_beam` does with
    segments whose midpoints fall inside or outside the agent's boundary
    outline on a layer.

    Attributes
    ----------
    EXCLUSIVE : str
        The outline defines a *no-go zone*.  Segments whose midpoints are inside
        the outline are discarded. 
    INCLUSIVE : str
        The outline defines an *allowed zone*.  Segments whose midpoints fall
        *outside* the outline are discarded.  U
    NONE : str
        No boundary culling — all segments are kept regardless of the outline.
        Used by agents whose elements span the full panel (studs, plates).
    """

    EXCLUSIVE = "exclusive"
    INCLUSIVE = "inclusive"
    NONE = "none"


class PopulatorAgent(Data, ABC):
    """Abstract base class for all panel populator agents.

    An agent is a stateless-by-design computational unit responsible for one
    logical group of framing elements within a panel (edge beams, studs,
    plates, opening surround, …).  Agents do not hold element lists and never
    write to the populator's model; the
    :class:`~timber_design.populators.PanelPopulator` owns the model and is its
    sole writer.  Ownership is recorded on the elements themselves: an agent
    stamps ``attributes["agent"] = self`` on everything it generates, so
    :meth:`elements_for_layer` can recover its own elements from a layer's
    children at any later stage.  Split segments inherit the tag automatically,
    because :meth:`~timber_design.connections_2d.beam2d.Beam2D.get_beam_segment`
    rebuilds a beam from its ``__data__`` (which carries ``attributes``).

    An agent provides:

    - :meth:`generate_elements` — create this agent's elements, returned per
      layer for the populator to add to the model.
    - :meth:`define_outlines` / :meth:`outline_for_layer` — the agent's
      boundary outline per layer, used for trimming peer elements.
    - :meth:`split_element` / :meth:`cull_element` — pure per-element geometry
      decisions against this agent's boundary, dispatched to
      :meth:`split_beam` / :meth:`cull_beam` / :meth:`trim_plate`.
    - :meth:`get_cluster_joint` — the joint this agent would create for a
      candidate cluster, using the internal/external/composite rule sets.

    Class-level attributes
    ----------------------
    BEAM_CATEGORY_NAMES : list[str]
        The beam categories this agent can create.  
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
        Overridable per-instance via ``composite_joint_overrides``.
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
    composite_joint_overrides : list[:class:`~timber_design.workflow.CompositeRule`], optional
        Overrides merged into :attr:`COMPOSITE_RULES` to form
        :attr:`composite_rules`.

    Attributes
    ----------
    beam_widths : dict[str, float]
        ``{category: width}`` mapping, resolved by the config / populator
        before generation.  Beam height is always the layer thickness.
    trimming_layers : list[:class:`~compas_timber.elements.Layer`]
        The layers on which this agent's boundary trims peer elements.
    element_layers : list[:class:`~compas_timber.elements.Layer`]
        The layers this agent generates elements on.
    elements : list[:class:`~timber_design.populators.Beam2D` | :class:`~compas_timber.elements.Plate`]
        Every element currently in the model that carries this agent's tag.
    external_rules : list[:class:`~timber_design.workflow.CategoryRule`]
        Active cross-agent joint rules.
    composite_rules : list[:class:`~timber_design.workflow.CompositeRule`]
        Active rules for clusters of three or more elements.
    internal_rules : list[:class:`~timber_design.workflow.CategoryRule`]
        Active within-agent joint rules.
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
            "composite_joint_overrides": self.composite_overrides or None,
        }

    def __init__(self, internal_joint_overrides=None, external_joint_overrides=None, composite_joint_overrides=None):
        super().__init__()
        self.beam_widths: dict[str, float] = {}
        self.internal_overrides = list(internal_joint_overrides) if internal_joint_overrides else []
        self.external_overrides = list(external_joint_overrides) if external_joint_overrides else []
        self.composite_overrides = list(composite_joint_overrides) if composite_joint_overrides else []
        self.internal_rules = self._apply_overrides(self.INTERNAL_JOINT_RULES, internal_joint_overrides)
        self.external_rules = self._apply_overrides(self.EXTERNAL_JOINT_RULES, external_joint_overrides)
        self.composite_rules = self._apply_overrides(self.COMPOSITE_RULES, composite_joint_overrides)
        self.outline_by_layer: dict[Layer, Optional[Polyline]] = {}

    def __repr__(self):
        return "{}({})".format(type(self).__name__, ", ".join(self.BEAM_CATEGORY_NAMES))

    @property
    @abstractmethod
    def element_layers(self) -> list[Layer]:
        """The layers this agent generates elements on."""
        raise NotImplementedError

    @property
    @abstractmethod
    def trimming_layers(self) -> list[Layer]:
        """The layers on which this agent's boundary trims peer elements."""
        raise NotImplementedError

    @property
    def elements(self) -> list:
        """Every element currently in the model that carries this agent's tag."""
        elements = []
        for layer in self.element_layers:
            elements.extend(self.elements_for_layer(layer))
        return elements

    def elements_for_layer(self, layer: Layer) -> list:
        """Return this agent's elements on *layer*, or an empty list.

        Returns
        -------
        list[:class:`~timber_design.populators.Beam2D` | :class:`~compas_timber.elements.Plate`]
        """
        return [e for e in layer.children if not isinstance(e, Layer) and e.attributes.get("agent") is self]

    # ------------------------------------------------------------------
    # Element generation
    # ------------------------------------------------------------------

    @abstractmethod
    def generate_elements(self):
        """Create this agent's elements, grouped per layer.

        Implementations must stamp ``attributes["agent"] = self`` on every
        element they return and record the agent's boundary outline for every
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

        Returns
        -------
        :class:`~compas.geometry.Polyline` or None
        """
        return None

    def define_outlines(self, layers):
        """Explicitly set this agent's boundary outline for every layer in *layers*.

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

    def split_element(self, element) -> list:
        """Apply this agent's boundary to *element*, returning what should replace it.

        Parameters
        ----------
        element: :class:`~timber_design.populators.Beam2D` | :class:`~compas_timber.elements.Plate`
            the element to be split.

        Returns
        -------
        list[:class:`~timber_design.populators.Beam2D` | :class:`~compas_timber.elements.Plate`]
            ``[element]`` when this agent's boundary leaves *element* intact.
            The populator swaps the original for the returned list only when
            they differ.
        """
        layer = element.parent
        if isinstance(element, Beam2D):
            return self.split_beam(element)
        self.trim_plate(element)
        return [element]

    def cull_element(self, element) -> bool:
        """Return ``True`` if this agent's boundary discards *element* entirely.

        Only beams are ever culled — a plate is cut by :meth:`trim_plate`
        during :meth:`split_element` rather than removed.

        Returns
        -------
        bool
        """
        return self.cull_beam(element) if isinstance(element, Beam2D) else False

    def split_beam(self, beam: Beam2D) -> list[Beam2D]:
        """Split *beam* at this agent's outline boundary and return all resulting segments.

        Returns
        -------
        list[:class:`~timber_design.populators.Beam2D`]
            ``[beam]`` (the untouched original) when the agent has no boundary
            on *layer* or the boundary does not cross the beam.
        """
        layer = beam.parent
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
        """Return ``True`` if *beam* should be removed by this agent.

        Parameters
        ----------
        beam : :class:`~timber_design.populators.Beam2D`
            A beam (or beam segment) on one of this agent's trimming layers.

        Returns
        -------
        bool
        """
        layer = beam.parent
        return self.cull_element_at_point(beam.centerline.midpoint, layer)


    def cull_element_at_point(self, point, layer: Optional[Layer] = None) -> bool:
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
        """Apply this agent's boundary to *plate* in place; the base implementation does nothing.

        Parameters
        ----------
        plate : :class:`compas_timber.elements.Plate`
            The plate to cut.
        layer : :class:`~compas_timber.elements.Layer`
            The layer *plate* belongs to.
        """
        pass

    # ------------------------------------------------------------------
    # Element extension
    # ------------------------------------------------------------------

    def extend_elements(self, boundary_outlines, layer: Layer) -> None:
        """Extend this agent's elements on *layer* toward *boundary_outlines*; no-op by default.

        Implementations recover their own elements via
        :meth:`elements_for_layer` — the populator supplies only the peer
        boundaries.

        Parameters
        ----------
        boundary_outlines : list[:class:`~compas.geometry.Polyline`]
            Boundary outlines of peer agents on *layer*.  The populator filters
            out ``None`` entries and this agent's own outline before calling.
        layer : :class:`~compas_timber.elements.Layer`
            The layer the extension applies to.
        """
        pass

    # ------------------------------------------------------------------
    # Joint rules
    # ------------------------------------------------------------------

    def get_cluster_joint(self, cluster, max_distance=None):
        """Return the joint this agent would create for *cluster*, or ``None``.

        Parameters
        ----------
        cluster : :class:`~compas_timber.connections.Cluster`
            The candidate cluster to resolve.
        max_distance : float, optional
            Fallback maximum gap for rules that do not specify their own.

        Returns
        -------
        :class:`~compas_timber.connections.Joint` or None

        Raises
        ------
        :class:`~compas_timber.errors.BeamJoiningError`
            Propagated from a matching rule so the populator can collect it
            onto its debug info rather than silently dropping it.
        """
        own_elements = self.elements
        owned = [e for e in cluster.elements if e in own_elements]
        if not owned:
            return None
        if len(cluster.elements) >= 3:
            rules = self.composite_rules
        elif len(owned) == len(cluster.elements):
            rules = self.internal_rules
        else:
            rules = self.external_rules
        for rule in JointRuleSolver._sort_rules(rules):
            joint = rule.create_instance(cluster, max_distance=max_distance)
            if joint:
                return joint
        return None

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
