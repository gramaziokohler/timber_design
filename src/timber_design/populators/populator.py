from itertools import combinations, product

from compas.tolerance import TOL
from compas_timber.connections import JointCandidate
from compas_timber.connections import get_clusters_from_joint_candidates
from compas_timber.model import TimberModel
from compas_timber.panel_features import Layer

from timber_design.populators.beam2d import Beam2D
from timber_design.populators.connection_solver_2d import ConnectionSolver2D
from timber_design.populators.connection_solver_2d import aabb_overlap

from timber_design.workflow import JointRuleSolver


class PanelPopulator:
    """Orchestrates the full population of a timber panel with framing elements.

    ``PanelPopulator`` is the top-level coordinator for the panel-population
    workflow.  It holds a list of :class:`~timber_design.populators.LayerAgent`
    instances — each responsible for one logical group of elements (edge beams,
    studs, plates, openings, …) — and drives them through a fixed sequence of
    stages:

    1. **generate_elements** — each agent creates its beams and plates.
    2. **extend_elements** — agents extend elements to reach adjacent agent boundaries (e.g. king/jack studs extended to plate beams).
    3. **trim_elements** — each agent applies its boundary to its peer agents'
       same-layer elements via
       :meth:`~timber_design.populators.PopulatorAgent.trim_agent_elements`.
       Single-layer agents act on their own layer; feature agents act on every
       layer they frame or trim.

    4. **add_elements_to_model** — surviving elements are added to the internal :class:`~compas_timber.model.TimberModel`.
    5. **join_elements** — two sub-passes mirroring stage 3:

       a. **create_agent_joints** — within-agent joint candidates are resolved.
       b. **create_cross_agent_joints** — cross-agent candidates are collected,
          clustered, and matched against the joint-rule lists of both agents.

    6. **process_joinery** — fabrication features (BTLx processings) are computed and applied to each element.
    7. **merge_with_model** — elements are transformed back to world space and attached as children of the source panel in the caller's model.

    All geometry during stages 1–6 lives in a flat 2D *populator space*: the
    panel is re-expressed as a local axis-aligned rectangle (X = panel length,
    Y = panel width, Z = panel thickness).  This simplifies topology detection
    and trimming, which are performed in 2D by :class:`~timber_design.populators.ConnectionSolver2D`.

    Parameters
    ----------
    panel : :class:`compas_timber.elements.Panel`
        The local (populator-space) panel.
    agents : list[:class:`~timber_design.populators.LayerAgent`]
        Ordered list of agents.  Ordering matters for trimming: agents
        earlier in the list are trimmed against later ones, so the edge
        agent should come first.
    original_panel : :class:`compas_timber.elements.Panel`, optional
        Reference to the source panel in the caller's model space.
    transformation_to_populator : :class:`compas.geometry.Transformation`, optional
        Transformation from world/panel space to populator space.
        Its inverse is applied in :meth:`merge_with_model`.

    Attributes
    ----------
    panel : :class:`compas_timber.elements.Panel`
        A localized copy of the panel in populator (2D) space.
    agents : list[:class:`~timber_design.populators.LayerAgent`]
        Ordered list of agents.
    original_panel : :class:`compas_timber.elements.Panel`
        Reference to the source panel in the caller's model space.
    transformation_to_populator : :class:`compas.geometry.Transformation`
        Transformation from world/panel space to populator space.
        Its inverse is applied in :meth:`merge_with_model`.
    model : :class:`compas_timber.model.TimberModel`
        Internal model that accumulates elements and joints during population.

    Examples
    --------
    Typical usage::

        from timber_design.populators import PanelPopulatorConfig

        config = PanelPopulatorConfig.stud_panel(
            standard_beam_width=60.0,
            stud_spacing=625.0,
            sheeting_inside=15.0,
        )
        populator = config.create_populator(panel)
        populator.populate_elements()
        populator.join_elements()
        populator.process_joinery()
        populator.merge_with_model(model)
    """

    def __init__(
        self,
        panel,
        agents,
        default_feature_agents=None,
        standard_beam_width=None,
        joint_rule_overrides=None,
    ):
        self.original_panel = panel
        self.model = None
        # Copy the caller's list: parse_default_feature_agents appends the
        # per-feature agents, and we must not mutate (or share) the caller's
        # list — otherwise a list reused across panels accumulates every
        # panel's agents, and each populator ends up trying to join other
        # panels' elements in its own model.
        self.agents = list(agents)

        # Config-time setup that does NOT depend on the panel's final geometry.
        # Snapshot as a list (panel.layers is a live view over the layer tree).
        self.layers = list(panel.layers)
        self.parse_default_feature_agents(default_feature_agents or {})
        self.resolve_beam_widths(standard_beam_width)
        self.route_rule_overrides(joint_rule_overrides)

   
    # ------------------------------------------------------------------
    # Initialization methods
    # ------------------------------------------------------------------

    def resolve_beam_widths(self, standard_beam_width):
        """Fill any unset per-category beam widths on every agent with :attr:`standard_beam_width`.

        For each agent in :attr:`agents`, walks the categories declared in
        ``agent.BEAM_CATEGORY_NAMES`` and fills entries that are either missing
        or ``None`` in ``agent.beam_widths`` with :attr:`standard_beam_width`.
        Per-category widths the caller already supplied to an agent constructor
        are left untouched, so explicit per-agent overrides always win over the
        panel-wide default.

        Does nothing when :attr:`standard_beam_width` is ``None``; in that case
        the caller is responsible for having supplied every per-category width
        directly to each agent.
        """
        if standard_beam_width is None:
            return
        for agent in self.agents:
            for category in agent.BEAM_CATEGORY_NAMES:
                if agent.beam_widths.get(category) is None:
                    agent.beam_widths[category] = standard_beam_width

    def route_rule_overrides(self, rule_overrides):
        """Distribute joint-rule overrides to whichever agents own their categories.

        For each :class:`~timber_design.workflow.CategoryRule` in *rule_overrides*,
        every agent in :attr:`agents` whose ``BEAM_CATEGORY_NAMES`` overlaps the
        rule's category pair has the rule merged into its rule lists:

        - both categories owned by the agent → ``agent.internal_rules``
        - exactly one category owned by the agent → ``agent.external_rules``
          *and* ``agent.external_overrides`` (the latter so the rule keeps its
          precedence over another agent's base rule for the same pair in
          :meth:`create_cross_agent_joints`)

        Agents that own neither category are skipped.  Merging delegates to
        :meth:`~PopulatorAgent._apply_overrides`, which replaces an existing
        rule only when both the ``joint_type.SUPPORTED_TOPOLOGY`` *and* the
        categories match (ordered for ``TOPO_T`` / ``TOPO_EDGE_FACE``, unordered
        otherwise), so the same pair may carry several rules targeting different
        topologies (e.g. a ``TButtJoint`` and an ``LButtJoint`` for the same
        ``(stud, top_plate_beam)`` pair).

        This is the single place a panel-level rule list is matched against
        per-agent rule slots, so callers can supply rules without knowing which
        agent owns each pair.

        Parameters
        ----------
        rule_overrides : list[:class:`~timber_design.workflow.CategoryRule`] or None
        """
        if not rule_overrides:
            return
        for rule in rule_overrides:
            pair = {rule.category_a, rule.category_b}
            for agent in self.agents:
                categories = set(agent.BEAM_CATEGORY_NAMES)
                if not (pair and categories):
                    continue
                if pair <= categories:
                    # Both categories owned by this agent → internal override.
                    agent.internal_rules = agent._apply_overrides(agent.internal_rules, [rule])
                else:
                    # Exactly one category owned → external override on this
                    # agent.  We update both the merged ``external_rules`` list
                    # (consumed by the joint solver) *and* the raw
                    # ``external_overrides`` list (consumed by
                    # ``create_cross_agent_joints`` to take precedence over the
                    # other agent's base rule for the same pair).
                    agent.external_rules = agent._apply_overrides(agent.external_rules, [rule])
                    agent.external_overrides = agent._apply_overrides(agent.external_overrides, [rule])

    def parse_default_feature_agents(self, default_feature_agents):
        """Instantiate a feature agent for every panel feature lacking one.

        Walks ``original_panel.features``; for any feature that no existing agent
        already handles, looks up a prototype agent in *default_feature_agents*
        (keyed by feature class), copies it, binds the feature, and appends it to
        :attr:`agents`.  The prototype already carries its ``element_layers`` /
        ``trimming_layers`` (set by the factory against the original panel's
        layers); :meth:`repoint_agents_to_populator_layers` rebinds those to the
        populator mirror during :meth:`prepare`.

        Parameters
        ----------
        default_feature_agents : dict[type, :class:`~timber_design.populators.FeatureAgent`]
            Prototype feature agent per feature class.
        """
        for feature in self.original_panel.features:
            if any(getattr(agent, "feature", None) is feature for agent in self.agents):
                continue  # a feature agent already handles this feature
            prototype = default_feature_agents.get(type(feature))
            if prototype is None:
                continue
            agent = type(prototype)(**prototype.__data__)
            agent.feature = feature
            self.agents.append(agent)

    @property
    def elements(self):
        """List of all elements placed by all agents."""
        return [e for e in self.model.elements() if not e.children]

    def __repr__(self):
        return "PanelPopulator({})".format(self.original_panel)

    def populate_elements(self):
        """Execute stages 1–4: generate, extend, trim, and add elements to the model.

        Call :meth:`join_elements` and :meth:`process_joinery` afterwards to
        complete the population workflow.
        """
        # model extracted here to ensure the latest version of panel and layer geometry
        self.model = extract_model_from_parent(self.original_panel) 
        self.generate_elements()
        self.extend_elements()
        self.trim_elements()
        self.add_elements_to_model()

    def generate_elements(self):
        """Ask each agent to create its beams and plates, layer by layer (stage 1).

        Mirrors :meth:`extend_elements` / :meth:`trim_elements`: iterate
        :attr:`layers`, select the agents that frame on each layer, and run the
        agent's per-layer action.
        """
        for layer in self.layers:
            for agent in self._agents_framing_on(layer):
                agent.generate_elements(layer)
        # Feature agents define their footprint outline on every layer they trim
        # (beyond the ones they frame) so peer beams there can be culled.
        for agent in self.agents:
            agent.define_trimming_outlines()

    def _agents_framing_on(self, layer):
        """Agents whose :attr:`element_layers` includes *layer* (they frame there)."""
        return [a for a in self.agents if layer in a.element_layers]

    def extend_elements(self):
        """Ask each agent to extend its elements toward adjacent boundaries (stage 2)."""
        for layer in self.layers:
            element_agents = [a for a in self.agents if a.elements_by_layer.get(layer)]
            boundary_agents = [a for a in self.agents if a.outline_by_layer.get(layer)]
            for agent in element_agents:
                agent.extend_elements([a for a in boundary_agents if a is not agent], layer)

    def trim_elements(self):
        """Split beams at agent boundaries and discard out-of-zone segments (stage 3).

        After all agents have trimmed their elements, degenerate
        :class:`~timber_design.populators.Beam2D` instances whose length is
        zero (or below floating-point tolerance) are silently removed.  These
        can arise when an agent boundary exactly coincides with a beam endpoint
        — a legal geometric configuration that produces a zero-length residual
        segment that would otherwise crash downstream joint processing.
        """
        for layer in self.layers:
            # Match on layers_to_trim() (framing + trimming layers, the latter
            # expanded to their sublayers) so an agent also trims peers on the
            # sublayers of its trimming layers.
            trimming_agents = [a for a in self.agents if layer in a.layers_to_trim()]
            for agent in trimming_agents:
                other_agents = [a for a in self.agents if a.elements_by_layer.get(layer) and a is not agent]
                for other_agent in other_agents:
                    if aabb_overlap(agent, other_agent):
                        agent.trim_agent_elements(other_agent, layer)

    def _drop_degenerate_beams(self):
        """Remove zero-length :class:`~timber_design.populators.Beam2D` elements from all agents."""
        for agent in self.agents:
            agent.elements = [e for e in agent.elements if not (isinstance(e, Beam2D) and e.length < TOL.absolute)]

    def add_elements_to_model(self):
        """Add every generated element to :attr:`model` under its (detached) layer (stage 4).

        Each element is re-expressed in its owning layer's local frame
        (``element.transformation = layer.transformation_to_local() @ element.transformation``)
        and parented under that layer.  Its ``modeltransformation`` therefore
        still resolves to the panel-local placement the agent generated (so
        joinery and BTLx processing run in populator space), and
        :meth:`merge_with_model` only has to move the layer subtree back under
        the original panel — no per-element transform.
        """
        for layer in self.layers:
            for agent in self._agents_framing_on(layer):
                for element in agent.elements_by_layer.get(layer, []):
                    element.transform(layer.transformation_to_local())
                    self.model.add_element(element, parent=layer)

    def join_elements(self):
        """Resolve all joint candidates and create joints in the model (stage 5).

        Runs :meth:`create_agent_joints` first (within-agent joints),
        then :meth:`create_cross_agent_joints` (between-agent joints).
        """
        self.create_agent_joints()
        self.create_cross_agent_joints()

    def create_agent_joints(self):
        """Create within-agent joints, layer by layer.

        Mirrors the other layer-driven stages: iterate :attr:`layers`, select the
        agents with elements on each layer, and build/apply that agent's joint
        defs for that layer.  ``create_joint_defs(layer)`` resets and returns the
        per-layer defs, so a multi-layer agent is never double-applied.
        """
        for layer in self.layers:
            for agent in self.agents:
                if not agent.elements_by_layer.get(layer):
                    continue
                for j_def in agent.create_joint_defs(layer):
                    j_def.joint_type.create(self.model, *j_def.elements, **j_def.kwargs)

    def create_cross_agent_joints(self):
        """Create joints between elements of different agents on the same layer.
        """
        solver = ConnectionSolver2D()
        for layer in self.layers:
            agents = [a for a in self.agents if a.elements_by_layer.get(layer)]
            for agent_a, agent_b in solver.find_intersecting_agent_pairs(agents):
                elements_a = agent_a.elements_by_layer.get(layer, [])
                elements_b = agent_b.elements_by_layer.get(layer, [])
                candidates = []
                for element_a, element_b in product(elements_a, elements_b):
                    topo_result = solver.find_topology(element_a, element_b)
                    if topo_result is not None:
                        candidate = JointCandidate(
                            topo_result.beam_a, topo_result.beam_b, distance=topo_result.distance, topology=topo_result.topology, location=topo_result.location
                        )
                        self.model.add_joint_candidate(candidate)
                        candidates.append(candidate)
                clusters = get_clusters_from_joint_candidates(candidates, max_distance=0.001)
                # Per-agent external overrides must win even when the matching
                # base rule is owned by the *other* agent.  The solver applies
                # the first matching rule, so overrides from both agents are
                # placed ahead of the (merged) base rule lists.
                overrides = agent_a.external_overrides + agent_b.external_overrides
                jrs = JointRuleSolver(overrides + agent_a.external_rules + agent_b.external_rules)
                jrs.joints_from_rules_and_clusters(self.model, clusters=clusters)

    def process_joinery(self):
        """Compute and apply fabrication features (BTLx processings) to all elements (stage 6)."""
        self.model.process_joinery()

    def merge_with_model(self, model, clear_panel=True):
        """Move the populated layer subtree back under the original panel in *model* (stage 7).

        Reattaching each detached layer under the original panel shifts the whole
        subtree — layers **and** the generated elements parented under them —
        from panel-local (populator) space into world space.  No geometry
        transform is applied; only computed caches are reset so they recompute
        against the new parent.

        Parameters
        ----------
        model : :class:`compas_timber.model.TimberModel`
            The caller's model to merge into.  The original panel must already be
            present so the layers have a parent to reattach to.
        clear_panel : bool, optional
            When ``True``, removes all existing children of :attr:`original_panel`
            (and their joints) from *model* before merging.  Use this to
            re-populate a panel that has already been processed.
        """
        # TODO: use @chenkasirer s merge_model functionality when added to CT
        if clear_panel:
            # Remove each existing child *subtree* leaves-first.  Removing a layer
            # directly would drop its treenode subtree but leave its beam children
            # in the model dict (orphaned ghost geometry), so recurse to leaves.
            for element in list(self.original_panel.children):
                _remove_element_subtree(model, element)

        merge_model_into_model(self.model, model, parent=self.original_panel)

# =============================================================================
# Model sub-tree surgery
# =============================================================================

def _remove_element_subtree(model, element):
    """Remove *element* and all its descendants from *model*, leaves-first.

    ``Model.remove_element`` drops a node's whole treenode subtree but only one
    guid from the element dict, so removing a non-leaf directly orphans its
    descendants.  Recursing to leaves keeps the model consistent.
    """
    for child in list(element.children):
        _remove_element_subtree(model, child)
    if model.has_element(element):
        model.remove_element(element)


def _reset_caches(element):
    """Invalidate an element's computed-geometry caches after a tree move.

    Re-parenting changes ``modeltransformation`` but does not touch
    ``transformation``, so the ``@reset_computed`` setter hook never fires.
    Null the caches so geometry recomputes against the new parent (``_blank``
    is a Beam-specific cache, ``_planes`` a Panel/Layer one).
    """
    for attr in ("_modelgeometry", "_aabb", "_obb", "_blank", "_planes"):
        print("resetting cached properties")
        if hasattr(element, attr):
            setattr(element, attr, None)

def _detach_subtree(model, parent):
    # type: (TimberModel, Element | None) -> list
    """Remove a subtree from *model*, returning ``(parent, [children])`` tuples.

    When *parent* is an element it is **kept** in *model* and only its descendants
    are removed; its direct children are recorded under ``None`` so they can be
    re-rooted elsewhere.  When *parent* is ``None`` every top-level element of
    *model* (and its subtree) is removed, also recorded under ``None``.

    Removal is leaves-first (so each removed node is a tree leaf, which
    ``remove_element`` handles cleanly); the returned tuples are ordered
    parents-before-children for re-insertion.
    """
    tuples = []

    def walk(element, is_kept_root):
        children = list(element.children)
        if children:
            tuples.append((None if is_kept_root else element, children))
            for child in children:
                walk(child, is_kept_root=False)
        if not is_kept_root and model.has_element(element):
            _reset_caches(element)
            model.remove_element(element)

    if parent is not None:
        walk(parent, is_kept_root=True)
    else:
        tops = [element for element in model.elements() if element.parent is None]
        tuples.append((None, tops))
        for top in tops:
            walk(top, is_kept_root=False)
    return tuples


def _attach_subtree(tuples, model, root_element=None):
    # type: (list, TimberModel, Element | None) -> None
    """Re-add ``(parent, [children])`` tuples into *model* (parents before children).

    Tuples whose recorded parent is ``None`` are attached under *root_element*.  Each
    re-added element has its computed properties reset so geometry recomputes
    against the new tree.
    """
    for parent, children in tuples:
        target_parent = parent or root_element # when parent is None, re-root under *root_element* instead
        for child in children:
            model.add_element(child, parent=target_parent)
            child.reset_computed_properties()


def extract_model_from_parent(parent):
    # type: (Element) -> TimberModel
    """Detach *parent*'s child subtree into a new, standalone :class:`TimberModel`.

    The *parent* element itself stays in its current model; its descendants are
    removed from that model and re-rooted (hierarchy preserved) in a fresh
    :class:`TimberModel`, which is returned.

    A child element detached from its parent reports its geometry in the
    parent's local frame — convenient for operating on, e.g., a panel's layers
    in isolation, then merging them back with :func:`merge_model_into_model`.

    Parameters
    ----------
    parent : :class:`~compas_model.elements.Element`
        The element whose children are extracted.  Must be in a model.

    Returns
    -------
    :class:`TimberModel`
        A new model containing *parent*'s former subtree.
    """
    tuples = _detach_subtree(parent.model, parent)
    new_model = TimberModel()
    _attach_subtree(tuples, new_model)
    return new_model


def merge_model_into_model(model, target_model, parent=None):
    # type: (TimberModel, TimberModel, Element | None) -> None
    """Move every element (and joints) of *model* into *target_model* under *parent*.

    All of *model*'s top-level elements and their subtrees are detached and
    re-added beneath *parent* in *target_model* (or under the root when *parent*
    is ``None``), preserving the hierarchy and resetting each moved element's
    computed properties.  Joints defined on *model* are copied across.

    Parameters
    ----------
    model : :class:`TimberModel`
        The source model whose contents are moved out.
    target_model : :class:`TimberModel`
        The model to merge *model*'s elements into.
    parent : :class:`~compas_model.elements.Element`, optional
        The element under which the moved elements are re-rooted.  ``None``
        attaches them under the target model's root.
    """
    joints = list(model.joints)

    # Drive the move from the model's authoritative element set (its element
    # dict) rather than a tree walk.  A children-based walk silently drops any
    # element that is in the model but orphaned from the tree (e.g. left with a
    # stale parent pointer after a parent was removed); a joint referencing such
    # an element would then fail to re-add with a cryptic "add both elements to
    # the model first" error at ``add_joint``.
    elements = list(model.elements())
    element_set = set(elements)

    # Snapshot each element's parent *within the moving set* before detaching.
    # A parent outside the set (or a stale/None parent on an orphan) maps to
    # None, so the element is re-rooted under *parent*.
    parent_of = {element: (element.parent if element.parent in element_set else None) for element in elements}

    def depth(element):
        d = 0
        p = parent_of[element]
        while p is not None:
            d += 1
            p = parent_of[p]
        return d

    # Detach deepest-first so ``remove_element`` only ever drops tree leaves and
    # never orphans a subtree in the source model.
    for element in sorted(elements, key=depth, reverse=True):
        if model.has_element(element):
            _reset_caches(element)
            model.remove_element(element)

    # Re-attach shallowest-first so every parent exists before its children.
    for element in sorted(elements, key=depth):
        target_parent = parent_of[element] if parent_of[element] is not None else parent
        target_model.add_element(element, parent=target_parent)
        element.reset_computed_properties()

    for joint in joints:
        missing = [e for e in joint.elements if not target_model.has_element(e)]
        if missing:
            raise ValueError(
                "Cannot re-add {} joint during merge: element(s) {} are not in the source model, so they were "
                "never merged. This usually means the joint references an element owned by a different "
                "panel/populator (shared agent or layer across panels).".format(
                    type(joint).__name__,
                    [e.attributes.get("category", type(e).__name__) for e in missing],
                )
            )
        target_model.add_joint(joint)
