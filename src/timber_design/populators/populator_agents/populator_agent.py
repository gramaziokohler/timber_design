import dataclasses
from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import List
from typing import Optional
from typing import Union

if TYPE_CHECKING:
    from timber_design.populators.layer import Layer

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

    Class Attributes
    ----------------
    AGENT_TYPE : type or None
        The :class:`PopulatorAgent` subclass this config instantiates.
        Set on each concrete subclass after both classes are defined.
    """

    AGENT_TYPE = None
    beam_width_overrides: Optional[dict] = None
    joint_rule_overrides: Optional[List[CategoryRule]] = None

    @property
    def __data__(self):
        return {
            "beam_width_overrides": self.beam_width_overrides,
            "joint_rule_overrides": self.joint_rule_overrides,
        }

    def get_agent_from_layer(self, layer):
        """Instantiate the agent for the given layer.

        Parameters
        ----------
        layer : :class:`~timber_design.populators.Layer`
            The layer to create the agent for.

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
        return self.AGENT_TYPE(layer, self)

    def get_agent_from_feature(self, feature, layer):
        """Instantiate a feature-based agent for the given layer.

        The *feature* (e.g. a transformed
        :class:`~compas_timber.panel_features.Opening`) is passed directly to
        the agent constructor as its third positional argument.  Only agents
        that declare a :attr:`FEATURE_TYPE` — currently
        :class:`~timber_design.populators.OpeningPopulatorAgent` — accept this
        argument.

        Parameters
        ----------
        feature : :class:`~compas_timber.panel_features.PanelFeature`
            The (possibly transformed) feature instance.
        layer : :class:`~timber_design.populators.Layer`
            The framing layer the agent operates within.

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
        return self.AGENT_TYPE(layer, self, feature)


class PopulatorAgent(ABC):
    """Abstract base class for all panel populator agents.

    A ``PopulatorAgent`` is responsible for one logical group of framing
    elements within a panel (edge beams, studs, plates, opening surround,
    recess frame, …).  Subclasses implement :meth:`generate_elements` and
    optionally override :meth:`extend_elements` and :meth:`cull_beam_segment`.

    Every agent holds:

    - :attr:`layer` — the :class:`~timber_design.populators.Layer` it belongs
      to, which carries the panel geometry (``layer.panel``) and the layer's
      position in the cross-section stack (``layer.layer_index``).
    - :attr:`feature` — the specific :class:`~compas_timber.panel_features.PanelFeature`
      for feature-based agents (e.g. :class:`~timber_design.populators.OpeningPopulatorAgent`);
      not present on layer-level agents.
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
    INTERNAL_RULES : list[:class:`~timber_design.workflow.CategoryRule`]
        Default joint rules for **within-agent** pairs — elements that belong
        to this agent and are joined to each other.  Used by
        :meth:`create_internal_joint_defs` / :meth:`get_direct_rule_from_elements`.
        Overridable per-instance via :attr:`PopulatorAgentConfig.joint_rule_overrides`.
    EXTERNAL_RULES : list[:class:`~timber_design.workflow.CategoryRule`]
        Default joint rules for **cross-agent** pairs — elements from this
        agent that are joined to elements from a different agent.  Used by
        :meth:`~timber_design.populators.PanelPopulator.create_cross_agent_joints`.
        Overridable per-instance via :attr:`PopulatorAgentConfig.joint_rule_overrides`.
    BOUNDARY_TYPE : :class:`FeatureBoundaryType`
        Controls how the agent's outline is used during trimming.
        Defaults to :attr:`~FeatureBoundaryType.NONE`.

    Parameters
    ----------
    layer : :class:`~timber_design.populators.Layer`
        The layer this agent operates within.  Provides the panel geometry
        (``layer.panel``) and cross-section position (``layer.layer_index``).
    params : :class:`PopulatorAgentConfig`
        Configuration including beam width overrides, joint rule overrides,
        and (for feature agents) the bound feature.

    Attributes
    ----------
    layer : :class:`~timber_design.populators.Layer`
        The layer this agent belongs to.
    layer_index : int or None
        Index of this agent's layer in the cross-section stack.
        Taken directly from ``layer.layer_index``.
    feature : :class:`~compas_timber.panel_features.PanelFeature` or None
        The panel feature for feature-based agents (e.g. an ``Opening``
        on :class:`~timber_design.populators.OpeningPopulatorAgent`).
        Not set on layer-level agents.
    panel : :class:`compas_timber.elements.Panel`
        The panel geometry for this layer.  Shortcut for ``self.layer.panel``.
    elements : list[:class:`~timber_design.populators.Beam2D` | :class:`~compas_timber.elements.Plate`]
        All elements created by this agent.  Populated by :meth:`generate_elements`
        and mutated by :meth:`trim_elements_with_agent`.
    outline : :class:`~compas.geometry.Polyline` or None
        Closed boundary polyline in populator space.  Set by :meth:`generate_elements`.
    internal_rules : list[:class:`~timber_design.workflow.CategoryRule`]
        Active within-agent joint rules (``INTERNAL_RULES`` merged with any
        matching :attr:`PopulatorAgentConfig.joint_rule_overrides`).
    external_rules : list[:class:`~timber_design.workflow.CategoryRule`]
        Active cross-agent joint rules (``EXTERNAL_RULES`` merged with any
        matching :attr:`PopulatorAgentConfig.joint_rule_overrides`).
    beam_dimensions : dict[str, tuple[float, float]]
        ``{category: (width, height)}`` mapping resolved by
        :meth:`resolve_beam_dimensions`.
    joint_defs : list[:class:`~timber_design.workflow.DirectRule`]
        Accumulated joint definitions, populated by :meth:`create_internal_joint_defs`.
    aabb : :class:`~timber_design.populators.AABB2D` or None
        2D bounding box enclosing all elements in this agent.
    layer_center_height : float
        Z coordinate of the centre of this agent's layer.  Used to place beam
        centrelines at the correct height in populator space.
    """

    FEATURE_TYPE = None
    BEAM_CATEGORY_NAMES = []
    INTERNAL_RULES = []
    EXTERNAL_RULES = []
    BOUNDARY_TYPE = FeatureBoundaryType.NONE

    def __init__(
        self,
        layer: "Layer",
        params: "PopulatorAgentConfig",
    ):
        self.layer = layer
        self.layer_index = layer.layer_index if layer is not None else None
        self.beam_width_overrides = params.beam_width_overrides or {}
        if params.joint_rule_overrides:
            self.internal_rules = self._apply_rule_overrides(self.INTERNAL_RULES, params.joint_rule_overrides)
            self.external_rules = self._apply_rule_overrides(self.EXTERNAL_RULES, params.joint_rule_overrides)
        else:
            self.internal_rules = list(self.INTERNAL_RULES)
            self.external_rules = list(self.EXTERNAL_RULES)
        self.beam_dimensions: dict[str, tuple[float, float]] = {}
        self.joint_defs = []
        self.elements = []
        self.outline = None
        self.layer_center_height = layer.panel.outline_a[0][2] + layer.panel.thickness / 2

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
        """The panel geometry for this agent's layer.

        Always returns ``self.layer.panel``.  Use this wherever the
        underlying :class:`~compas_timber.elements.Panel` geometry is needed
        (outlines, thickness, length, width, edge planes, …).
        """
        return self.layer.panel

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
            :attr:`PopulatorAgentConfig.joint_rule_overrides`.

        Returns
        -------
        list[:class:`~timber_design.workflow.CategoryRule`]
        """
        # NOTE: this is a bit of a breach of encapsulation, but necessary to allow for rule overrides
        # TODO: if we're only working with category rules here then make it explicit, if not, find a way to use the public interface of JointRule
        rules = list(base_rules)
        for override in overrides:
            for rule in rules:
                if rule.category_a not in self.BEAM_CATEGORY_NAMES or rule.category_b not in self.BEAM_CATEGORY_NAMES:
                    continue
                # element order matters for T and EDGE_FACE topologies
                if rule.joint_type.supported_topology == JointTopology.TOPO_T or rule.joint_type.supported_topology == JointTopology.TOPO_EDGE_FACE:
                    if override.category_a == rule.category_a and override.category_b == rule.category_b:
                        rule = override
                        break
                else:
                    if set([override.category_a, override.category_b]) == set([rule.category_a, rule.category_b]):
                        rule = override
                        break
            else:
                rules.append(override)
        return rules

    def resolve_beam_dimensions(self, standard_beam_width: float, frame_thickness: float) -> None:
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

    def affects_layer(self, layer_index: int) -> bool:
        """Return ``True`` if this agent participates in cross-layer trimming for *layer_index*.

        The default implementation returns ``True`` only when *layer_index*
        matches this agent's own :attr:`layer_index` (i.e. same layer, which
        is used as a no-op guard for same-layer pairs passed to
        :meth:`trim_elements_with_agent`).

        Subclasses that trim elements across layer boundaries — such as
        :class:`~timber_design.populators.RecessPopulatorAgent`, which cuts
        sheathing plates on lower layers — override this to return ``True``
        for a broader range of indices.

        Called exclusively by
        :meth:`~timber_design.populators.PanelPopulator.trim_cross_layer_elements`
        to decide whether a cross-layer trimming pass should be executed.

        Parameters
        ----------
        layer_index : int or None
            The :attr:`layer_index` of the *other* agent whose elements may
            be trimmed.

        Returns
        -------
        bool
        """
        return self.layer_index == layer_index

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
        # type: (PopulatorAgent, bool, bool) -> None
        """Split and cull this agent's elements using *agent*'s outline and boundary type.

        Called by :meth:`~timber_design.populators.PanelPopulator.trim_within_layer_elements`
        (for agents on the same layer) and by
        :meth:`~timber_design.populators.PanelPopulator.trim_cross_layer_elements`
        (for agents on different layers, after :meth:`affects_layer` has already
        confirmed the interaction is valid).

        Beams are split at outline crossings; segments outside an
        :attr:`~FeatureBoundaryType.INCLUSIVE` zone or inside an
        :attr:`~FeatureBoundaryType.EXCLUSIVE` zone are discarded.  Plates are
        passed to :meth:`~PopulatorAgent.apply_to_plate` for feature application
        (e.g. contour cuts) and are always retained.

        Parameters
        ----------
        agent : :class:`PopulatorAgent`
            The agent whose outline drives trimming/culling.
        skip_notches : bool
            Forwarded to :func:`~timber_design.populators.find_beam_outline_crossings`.
        skip_laps : bool
            Forwarded to :func:`~timber_design.populators.find_beam_outline_crossings`.
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
