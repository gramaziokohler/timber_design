from __future__ import annotations

from compas_timber.connections import Cluster
from compas_timber.elements import Layer
from compas_timber.elements import Panel

from timber_design.connections_2d import AABB2D
from timber_design.connections_2d import Beam2D
from timber_design.connections_2d.connection_solver_2d import Cluster2DFinder
from timber_design.connections_2d.connection_solver_2d import ConnectionSolver2D
from timber_design.connections_2d.connection_solver_2d import aabb_overlap
from timber_design.workflow import DebugInfomation
from timber_design.workflow import JointRuleSolver


class PanelPopulator:
    """Orchestrates the full population of a timber panel with framing elements.

    ``PanelPopulator`` is the top-level coordinator for the panel-population
    workflow and the **sole writer** to its internal model.  It holds a list of
    :class:`~timber_design.populators.PopulatorAgent` instances — each a pure
    per-domain compute unit responsible for one logical group of elements
    (edge beams, studs, plates, openings, …) — and drives them through a fixed
    sequence of stages.  Agents never touch the model or each other; the
    populator tracks element ownership through each element's
    ``attributes["agent"]`` / ``attributes["layer_path"]`` tags and passes
    agents the element lists they need as arguments.

    :meth:`populate_elements` runs stages 1–7:

    1. **generate_elements** — each agent creates its beams and plates; the
       populator tags them with the agent's key and layer path and adds them
       to :attr:`model` at root level, still in populator space.
    3. **extend_elements** — agents extend their own elements to reach
       adjacent agent boundaries (e.g. king/jack studs extended to plate
       beams).
    4. **split_elements** — each trimming agent's boundary splits peer beams
       into segments and cuts plates; the populator swaps the originals for
       the segments in the model.
    5. **cull_elements** — out-of-zone segments are removed from the model.

    Call :meth:`join_elements` (stage 7) and :meth:`process_joinery` (stage 8)
    afterwards, then :meth:`merge_with_model` to move the populated layer
    subtree back under the original panel in the caller's model.

    All geometry during stages 1–5 lives in a flat 2D *populator space*: the
    panel is re-expressed as a local axis-aligned rectangle (X = panel length,
    Y = panel width, Z = panel thickness).  This simplifies topology detection
    and trimming, which are performed in 2D by :class:`~timber_design.populators.ConnectionSolver2D`.

    Parameters
    ----------
    panel : :class:`compas_timber.elements.Panel`
        The source panel in the caller's model space (or its guid).
    agents : list[:class:`~timber_design.populators.PopulatorAgent`]
        Ordered list of agents.  Ordering matters for trimming: agents
        earlier in the list are trimmed against later ones, so the edge
        agent should come first.
    default_feature_agents : dict[type, :class:`~timber_design.populators.FeatureAgent`], optional
        Prototype feature agent per feature class, instantiated for any panel
        feature no existing agent already handles.
    standard_beam_width : float, optional
        Panel-wide default beam width, used to fill any per-category width an
        agent constructor did not set.
    joint_rule_overrides : list[:class:`~timber_design.workflow.CategoryRule` | :class:`~timber_design.workflow.CompositeRule`], optional
        Panel-level joint rules kept on the populator itself — they are never
        merged into any agent's rule lists.  :meth:`_join_cluster` tries them
        on a cluster only after every owning agent's own rules have failed,
        and again per pairwise candidate after the agents' pairwise rules.
    max_distance : float, optional
        Maximum gap distance considered when finding and creating joints in
        :meth:`join_elements` — both the geometric candidate search
        (:class:`~timber_design.connections_2d.connection_solver_2d.ConnectionSolver2D`
        / :class:`~timber_design.connections_2d.connection_solver_2d.Cluster2DFinder`)
        and joint creation itself (:meth:`_join_cluster`, which falls back to
        this value for any rule that doesn't specify its own ``max_distance``).
        ``None`` (the default) resolves to ``0.1``.

    Attributes
    ----------
    agents : list[:class:`~timber_design.populators.PopulatorAgent`]
        Ordered list of agents.  Each is assigned a stable ownership key
        (``"{ClassName}_{index}"``) written into every element it generates.
    original_panel : :class:`compas_timber.elements.Panel`
        Reference to the source panel in the caller's model space.
    model : :class:`compas_timber.model.TimberModel`
        Internal model that accumulates elements and joints during population.
        Owned exclusively by the populator — agents never write to it.
    debug_info : :class:`~timber_design.workflow.DebugInfomation`
        Collects joining errors from :meth:`join_elements` and
        :meth:`process_joinery` instead of silently dropping them.
    joint_rule_overrides : list[:class:`~timber_design.workflow.CategoryRule` | :class:`~timber_design.workflow.CompositeRule`]
        Panel-level joint rules, tried by :meth:`_join_cluster` after the
        owning agents' own rules (first on the whole cluster, then per
        pairwise candidate).
    max_distance : float
        Maximum gap distance applied to all joint candidate finding and
        creation in :meth:`join_elements`.

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
        max_distance=None,
    ):

        self.model = None
        self.debug_info = DebugInfomation()
        self.max_distance = max_distance if max_distance is not None else 0.1
        self.agents = list(agents) if agents else None
        if isinstance(panel, Panel):
            self.panel_guid = panel.guid
            self.panel = panel
        else:
            self.panel_guid = panel
            self.panel = panel
        self.parse_default_feature_agents(default_feature_agents or {})
        self.resolve_beam_widths(standard_beam_width)
        self.joint_rule_overrides = list(joint_rule_overrides) if joint_rule_overrides else []
        self._repoint_agents()

    # ------------------------------------------------------------------
    # Initialization methods
    # ------------------------------------------------------------------

    def resolve_beam_widths(self, standard_beam_width):
        """Fill any unset per-category beam widths on every agent with *standard_beam_width*.

        For each agent in :attr:`agents`, walks the categories declared in
        ``agent.BEAM_CATEGORY_NAMES`` and fills entries that are either missing
        or ``None`` in ``agent.beam_widths`` with *standard_beam_width*.
        Per-category widths the caller already supplied to an agent constructor
        are left untouched, so explicit per-agent overrides always win over the
        panel-wide default.

        Does nothing when *standard_beam_width* is ``None``; in that case
        the caller is responsible for having supplied every per-category width
        directly to each agent.
        """
        if standard_beam_width is None:
            return
        for agent in self.agents:
            for category in agent.BEAM_CATEGORY_NAMES:
                if agent.beam_widths.get(category) is None:
                    agent.beam_widths[category] = standard_beam_width

    def _repoint_agents(self):
        """Rebind all agents to the current panel's layer tree using stored paths."""
        for agent in self.agents:
            agent.repoint_to_layer_tree(self.layer_tree)

    def update_panel_from_model(self, model):
        self.panel = model.element_by_guid(str(self.panel_guid))

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
        for feature in self.panel.features:
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

    @property
    def layer_tree(self):
        return {l.layer_path: l for l in self.model.layers}

    def __repr__(self):
        return "PanelPopulator({})".format(self.panel)

    # ------------------------------------------------------------------
    # Layer-aware agent / element accessors
    # ------------------------------------------------------------------

    # def get_boundary_agents_for_layer(self, layer):
    #     """Agents that frame on *layer* or any of its ancestor layers."""
    #     relevant_layers = set([layer] + self.get_ancestor_layers(layer))
    #     agents = []
    #     for agent in self.agents:
    #         if relevant_layers & set(agent.element_layers):
    #             agents.append(agent)
    #     return agents

    # def get_ancestor_layers(self, layer):
    #     ancestors = []
    #     path = layer.layer_path
    #     if path is None:
    #         return ancestors
    #     while len(path) > 1:
    #         path = path[:-1]
    #         parent = self.layer_tree.get(path)
    #         if parent is not None:
    #             ancestors.append(parent)
    #     return ancestors

    # def get_child_layers(self, layer):
    #     sublayers = []
    #     def walk(layer):
    #         if not layer.sublayers:
    #             return
    #         sublayers.extend(layer.sublayers)
    #         for sl in layer.sublayers:
    #             walk(sl)

    #     walk(layer)
    #     return sublayers

    # ------------------------------------------------------------------
    # Element grouping (ownership tags → per-pass element lists)
    # ------------------------------------------------------------------


    @staticmethod
    def _aabbs_overlap(a, b):
        """Overlap test for two (possibly ``None``) :class:`AABB2D` boxes."""
        return a is not None and b is not None and aabb_overlap(a, b)

    # ------------------------------------------------------------------
    # Population pipeline
    # ------------------------------------------------------------------

    def build_populator_model(self):
        model = self.panel.model.extract_model_from_parent(self.panel)
        # elements on layers will be removed. Elements with parent == original_panel will be kept.
        for element in list(model.elements()):
            # skip elements at root-level. these are not on a layer
            if element.parent is None:
                continue
            if not isinstance(element, Layer):
                model.remove_element(element)
        return model

    def populate_elements(self):
        """Execute stages 1–6: generate, define outlines, extend, split, cull, attach.

        Call :meth:`join_elements` and :meth:`process_joinery` afterwards to
        complete the population workflow.
        """
        # model extracted here to ensure the latest version of panel and layer geometry
        self.model = self.build_populator_model()
        self._generate_elements()
        self._extend_elements()
        self._split_elements()
        self._cull_elements()

    def _generate_elements(self):
        """Ask each agent to create its elements and add them to the model (stage 1).

        Elements are tagged with the generating agent's key and their layer's
        path, then added at the model **root**, untransformed — they stay in
        populator space until :meth:`attach_elements_to_layers` re-parents
        them, because the 2D split/cull/extend machinery reads populator-space
        coordinates.
        """
        for agent in self.agents:
            for layer, elements in agent.generate_elements().items():
                for element in elements:
                    self.model.add_element(element, parent=layer)

    def _extend_elements(self):
        """Ask each agent to extend its elements toward adjacent boundaries (stage 3).
        """
        for agent in self.agents:
            for layer in agent.element_layers:
                boundary_outlines = []
                for boundary_agent in self.agents:
                    boundary_outlines.append(boundary_agent.outline_for_layer(layer))
                agent.extend_elements(boundary_outlines, layer)

    def _split_elements(self):
        """Geometrically split beams at agent boundaries (stage 4).
        """

        for agent in self.agents:
            for layer in agent.trimming_layers:
                for element in _get_decendant_elements_for_layer(layer):
                    agent.split_element(element)


    def _cull_elements(self):
        """Discard out-of-zone beam segments after splitting (stage 5).
        """

        for agent in self.agents:
            for layer in agent.trimming_layers:
                for element in _get_decendant_elements_for_layer(layer):
                    if agent.cull_element(element):
                        self.model.remove_element(element)

    # ------------------------------------------------------------------
    # Joining
    # ------------------------------------------------------------------

    def join_elements(self):
        """Resolve all joint candidates and create joints in the model (stage 7).
        """
        for layer in self.model.layers:
            beams = _get_ancestor_beams_for_layer(layer)
            cs = Cluster2DFinder(endpoint_tolerance=self.max_distance)
            clusters = cs.find_joint_clusters(beams)
            for cluster in clusters:
                self._join_cluster(cluster, max_distance=self.max_distance)

    def _join_cluster(self, cluster, max_distance=None):
        """Resolve one cluster, trying four rule sources in order of specificity.

        1. **Agent, whole cluster.**  
        2. **Populator, whole cluster.**  
        3. **Agent, pairwise.** 
        4. **Populator, pairwise.** 
        """
        if self._try_agent_rules(cluster, max_distance):
            return
        if self._try_populator_rules(self.joint_rule_overrides, cluster, max_distance):
            return
        for candidate in cluster.joints:
            pair_cluster = Cluster([candidate])
            if self._try_agent_rules(pair_cluster, max_distance):
                continue
            self._try_populator_rules(self.joint_rule_overrides, pair_cluster, max_distance)

    def _try_agent_rules(self, cluster, max_distance):
        """Try each owning agent's own rules on *cluster*; return ``True`` on the first success."""
        for agent in self.agents:
            joint = agent.get_cluster_joint(cluster, max_distance=max_distance)
            if joint:
                self.model.add_joint(joint)
                return True
        return False

    def _try_populator_rules(self, rules, cluster, max_distance):
        """Try to resolve *cluster* with *rules*; return ``True`` on success.

        Joining errors raised by direct rules are collected onto
        :attr:`debug_info` rather than silently dropped.
        """
        if not rules:
            return False
        solver = JointRuleSolver(rules)
        unjoined = solver.joints_from_rules_and_clusters(self.model, [cluster], pairwise_fallback=False, max_distance=max_distance)
        if solver.joining_errors:
            self.debug_info.add_joint_error(solver.joining_errors)
        return not unjoined

    def _owning_agents(self, elements):
        """``(agent, own_elements)`` for every agent owning at least one of *elements*, in :attr:`agents` order."""
        pairs = []
        for agent in self.agents:
            own = [e for e in elements if _agent_tag(e) == agent.key]
            if own:
                pairs.append((agent, own))
        return pairs

    # ------------------------------------------------------------------
    # Finalization
    # ------------------------------------------------------------------

    def process_joinery(self):
        """Compute and apply fabrication features (BTLx processings) to all elements (stage 8)."""
        self.debug_info.add_joint_error(self.model.process_joinery())

    def merge_with_model(self, model, clear_panel=True):
        """Move the populated layer subtree back under the original panel in *model*.

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
        for element in self.model.elements():
            if isinstance(element, Beam2D):
                element.to_beam()
        if clear_panel:
            model.remove_element_subtree(self.panel)
        model.merge_model(self.model, parent=self.panel)


def _agent_tag(element):
    """*element*'s owning-agent key, or ``None`` for anything untagged (layers, panels, user elements)."""
    attributes = getattr(element, "attributes", None)
    return attributes.get("agent") if attributes is not None else None


def _get_ancestor_beams_for_layer(layer):
    beams = []

    def walk_up(current_layer):
        beams.extend([b for b in current_layer.children if isinstance(b, Beam2D)])
        if current_layer.parent:
            walk_up(current_layer.parent)

    walk_up(layer)
    return beams

def _get_decendant_elements_for_layer(layer):
    beams = []

    def walk_down(current_layer):
        beams.extend([b for b in current_layer.children ])
        if current_layer.children:
            for child in current_layer.children:
                beams.append(child)
                walk_down(current_layer.parent)

    walk_down(layer)
    return beams
