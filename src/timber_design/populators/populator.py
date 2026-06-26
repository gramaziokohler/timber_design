from __future__ import annotations

from itertools import combinations, product
from typing import TYPE_CHECKING

from compas_timber.connections import JointCandidate
from compas_timber.connections import get_clusters_from_joint_candidates
from compas_timber.elements import Layer
from compas_timber.elements import Panel


from timber_design.connections_2d.connection_solver_2d import ConnectionSolver2D
from timber_design.connections_2d.connection_solver_2d import aabb_overlap

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
       :meth:`~timber_design.populators.PopulatorAgent.split_agent_elements`.
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
        
        self.model = None
        self.agents = list(agents)
        if isinstance(panel, Panel):
            self.panel_guid = panel.guid
            self.original_panel = panel
        else:
           self.panel_guid = panel
           self.original_panel = panel
        self.layers = list(panel.layers)
        self.layer_tree = {k:v for k, v in panel.layer_tree.items()}
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

    def _repoint_agents(self):
        """Rebind all agents to the current panel's layer tree using stored paths."""
        tree = self.original_panel.layer_tree
        for agent in self.agents:
            agent.repoint_to_layer_tree(tree)

    def update_panel_from_model(self, model):
        self.original_panel = model.element_by_guid(str(self.panel_guid))

    def parse_default_feature_agents(self, default_feature_agents):
        """Instantiate a feature agent for every panel feature lacking one.

        Walks ``original_panel.features``; for any feature that no existing agent
        already handles, looks up a prototype agent in *default_feature_agents*
        (keyed by feature class), copies it, binds the feature, and appends it to
        :attr:`agents`.  The prototype's ``element_layer_paths`` / ``trimming_layer_paths``
        are filtered to paths present in this panel's layer tree.

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
    
    # ------------------------------------------------------------------
    # Layer-aware agent / element accessors
    # ------------------------------------------------------------------

    def get_element_agents_for_layer(self, layer):
        child_layers = self.get_child_layers(layer)
        agents = []
        
        for cl in child_layers + [layer]:
            for agent in self.agents:
                if cl in agent.element_layers:
                    agents.append(agent)
        return agents

    def get_boundary_agents_for_layer(self, layer):
        relevant_layers = [layer] + self.get_ancestor_layers(layer)
        agents = []
        for rl in relevant_layers:
            for agent in self.agents:
                if rl in agent.element_layers:
                    agents.append(agent)
        return agents


    def get_ancestor_layers(self, layer):
        ancestors = []
        def walk(layer):
            parent = layer.__dict__.get('parent_layer')
            if not parent:
                return
            ancestors.append(parent)
            walk(parent)
        walk(layer)
        return ancestors

    def get_child_layers(self, layer):
        sublayers = []
        def walk(layer):
            if not layer.sublayers:
                return
            sublayers.extend(layer.sublayers)
            for sl in layer.sublayers:
                walk(sl)
        walk(layer)
        return sublayers

    def build_populator_model(self):
        model = self.original_panel.model.extract_model_from_parent(self.original_panel)
        for element in list(model.elements()):
            if not isinstance(element, Layer):
                model.remove_element(element)
        # Seed the pop model with layers that exist on the panel but were not
        # yet in the main model (first run, or layers defined outside CT_Model).
        in_model = set(id(e) for e in model.elements())
        for layer in self.original_panel.layers:
            if id(layer) not in in_model:
                model.add_element(layer)
                in_model.add(id(layer))
        return model

    def populate_elements(self):
        """Execute stages 1–4: generate, extend, trim, and add elements to the model.

        Call :meth:`join_elements` and :meth:`process_joinery` afterwards to
        complete the population workflow.
        """
        # model extracted here to ensure the latest version of panel and layer geometry
        self.model = self.build_populator_model()
        self._repoint_agents()
        self.layers = list(self.original_panel.layers)
        self.generate_elements()
        self.extend_elements()
        self.split_elements()
        self.cull_elements()
        self.add_elements_to_model()

    def generate_elements(self):
        """Ask each agent to create its beams and plates, layer by layer (stage 1).

        Mirrors :meth:`extend_elements` / :meth:`trim_elements`: iterate
        :attr:`layers`, select the agents that frame on each layer, and run the
        agent's per-layer action.
        """
        for agent in self.agents:
            agent.generate_elements()

    def extend_elements(self):
        """Ask each agent to extend its elements toward adjacent boundaries (stage 2).

        Boundary agents are collected from the element's own layer **and** from
        every ancestor layer (via ``layer.parent_layer``), so that elements on a
        sublayer extend toward plates or edges defined on the parent layer.
        """
        for agent in self.agents:
            for layer in agent.element_layers:
                boundary_agents = [ a for a in self.get_boundary_agents_for_layer(layer) if a is not agent]
                agent.extend_elements(boundary_agents, layer)


    def split_elements(self):
        """Geometrically split beams at agent boundaries (stage 3a).

        Every trimming agent cuts each peer's beams at outline crossings,
        producing sub-segments.  No segments are discarded here — that is the
        job of :meth:`cull_elements`.  Plates receive their boundary feature
        (e.g. a FreeContour) during this pass.

        Parent-layer agents trim child-layer elements; the reverse never
        occurs because trimming_layers is only expanded downward (children),
        never upward.
        """
        for agent in self.agents:
            for trimming_layer in agent.trimming_layers:
                affected_layers = [trimming_layer] + self.get_child_layers(trimming_layer)
                for layer in affected_layers:
                    if layer not in agent.outline_by_layer:
                        try:
                            agent.outline_by_layer[layer] = agent._compute_outline_for_layer(layer)
                        except (NotImplementedError, AttributeError):
                            agent.outline_by_layer[layer] = agent.outline_by_layer.get(trimming_layer)
                    agents_to_trim = [a for a in self.agents if layer in a.element_layers and a is not agent]
                    for other_agent in agents_to_trim:
                        if aabb_overlap(agent, other_agent):
                            agent.split_agent_elements(other_agent, layer)

    def cull_elements(self):
        """Discard out-of-zone beam segments after splitting (stage 3b).

        Each trimming agent removes segments from peer agents' element lists
        that fall inside an EXCLUSIVE zone or outside an INCLUSIVE zone, as
        well as any agent-specific culls (e.g. studs coinciding with king
        studs).  All splitting must be complete before this pass runs.
        """
        for agent in self.agents:
            for trimming_layer in agent.trimming_layers:
                affected_layers = [trimming_layer] + self.get_child_layers(trimming_layer)
                for layer in affected_layers:
                    agents_to_trim = [a for a in self.agents if layer in a.element_layers and a is not agent]
                    for other_agent in agents_to_trim:
                        if aabb_overlap(agent, other_agent):
                            agent.cull_agent_elements(other_agent, layer)


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

        for agent in self.agents:
            for layer, elements in agent.elements_by_layer.items():
                if elements:
                    for element in elements:
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
        for agent in self.agents:
            for j_def in agent.create_joint_defs():
                j_def.joint_type.create(self.model, *j_def.elements, **j_def.kwargs)

    def create_cross_agent_joints(self):
        """Create joints between elements of different agents on the same layer.
        """
        solver = ConnectionSolver2D(max_distance=1.0)
        for layer in self.layers:
            agents = [a for a in self.agents if a.elements_by_layer.get(layer)]
            for agent_a, agent_b in solver.find_intersecting_pairs(agents):
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
        if clear_panel:
            model.remove_element_subtree(self.original_panel)
        model.merge_model(self.model, parent=self.original_panel)
