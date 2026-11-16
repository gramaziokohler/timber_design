from __future__ import annotations

from compas_timber.connections import Cluster
from compas_timber.elements import Layer
from compas_timber.elements import Panel
from compas_timber.errors import BeamJoiningError

from compas_timber_populator.connections_2d import Beam2D
from compas_timber_populator.connections_2d.connection_solver_2d import ConnectionSolver2D
from compas_timber_rules import DebugInfomation
from compas_timber_rules import JointRuleSolver


class PanelPopulator:
    """Orchestrates the full population of a timber panel with framing elements.

    ``PanelPopulator`` is the top-level coordinator for the panel-population
    workflow and the **sole writer** to its internal model.  It holds a list of
    :class:`~compas_timber_populator.PopulatorAgent` instances — each a pure
    per-domain compute unit responsible for one logical group of elements
    (edge beams, studs, plates, openings, …) — and drives them through a fixed
    sequence of stages.  Agents never touch the model or each other; each
    element carries an ``attributes["agent"]`` tag identifying the agent that
    generated it, and every agent recovers its own elements from a layer's
    children through that tag.

    :meth:`populate_elements` runs stages 1–5:

    1. **generate_elements** — each agent creates its beams and plates,
       already tagged with itself; the populator adds them to :attr:`model`
       under their layer, still in populator space.
    2. **define_outlines** — each agent records its boundary outline for every
       layer it trims but does not frame on, so the trimming passes below have
       an outline everywhere they act.
    3. **extend_elements** — agents extend their own elements to reach
       adjacent agent boundaries (e.g. king/jack studs extended to plate
       beams).
    4. **split_elements** — each trimming agent's boundary splits peer beams
       into segments and cuts plates; the populator swaps the originals for
       the segments in the model.
    5. **cull_elements** — out-of-zone segments are removed from the model.

    An agent never trims its own elements: stages 4 and 5 skip any element
    whose ``attributes["agent"]`` is the trimming agent itself, so an
    ``INCLUSIVE`` agent does not cull the very beams that define its boundary.

    Call :meth:`join_elements` (stage 6) and :meth:`process_joinery` (stage 7)
    afterwards, then :meth:`merge_with_model` to move the populated layer
    subtree back under the original panel in the caller's model.

    All geometry during stages 1–5 lives in a flat 2D *populator space*: the
    panel is re-expressed as a local axis-aligned rectangle (X = panel length,
    Y = panel width, Z = panel thickness).  This simplifies topology detection
    and trimming, which are performed in 2D by :class:`~compas_timber_populator.connections_2d.ConnectionSolver2D`.

    Parameters
    ----------
    panel : :class:`compas_timber.elements.Panel`
        The source panel in the caller's model space (or its guid).
    agents : list[:class:`~compas_timber_populator.PopulatorAgent`]
        Ordered list of agents.  Ordering sets joint precedence: when
        several agents own elements in a cluster, the earlier agent's rules
        are tried first.  Each agent is cloned (see
        :meth:`~compas_timber_populator.PopulatorAgent.clone`), so the
        same agent instances can be passed to several populators; use
        :attr:`agents` to inspect the populated ones.
    default_feature_agents : dict[type, :class:`~compas_timber_populator.FeatureAgent`], optional
        Prototype feature agent per feature class, instantiated for any panel
        feature no existing agent already handles.
    standard_beam_width : float, optional
        Panel-wide default beam width, used to fill any per-category width an
        agent constructor did not set.
    joint_rule_overrides : list[:class:`~compas_timber_rules.CategoryRule` | :class:`~compas_timber_rules.CompositeRule`], optional
        Panel-level joint rules kept on the populator itself — they are never
        merged into any agent's rule lists.  :meth:`_join_cluster` tries them
        on a cluster only after every owning agent's own rules have failed,
        and again per pairwise candidate after the agents' pairwise rules.
    max_distance : float, optional
        Maximum gap distance considered when finding and creating joints in
        :meth:`join_elements` — both the geometric candidate search
        (:class:`~compas_timber_populator.connections_2d.connection_solver_2d.ConnectionSolver2D`
        / :class:`~compas_timber_populator.connections_2d.connection_solver_2d.Cluster2DFinder`)
        and joint creation itself (:meth:`_join_cluster`, which falls back to
        this value for any rule that doesn't specify its own ``max_distance``).
        ``None`` (the default) resolves to ``0.1``.

    Attributes
    ----------
    agents : list[:class:`~compas_timber_populator.PopulatorAgent`]
        Ordered list of agents.  Each tags every element it generates with
        itself, which is how ownership is tracked from then on.
    panel : :class:`compas_timber.elements.Panel`
        Reference to the source panel in the caller's model space.
    model : :class:`compas_timber.model.TimberModel`
        Internal model that accumulates elements and joints during population.
        Owned exclusively by the populator — agents never write to it.
    debug_info : :class:`~compas_timber_rules.DebugInfomation`
        Collects joining errors from :meth:`join_elements` and
        :meth:`process_joinery` instead of silently dropping them.
    joint_rule_overrides : list[:class:`~compas_timber_rules.CategoryRule` | :class:`~compas_timber_rules.CompositeRule`]
        Panel-level joint rules, tried by :meth:`_join_cluster` after the
        owning agents' own rules (first on the whole cluster, then per
        pairwise candidate).
    max_distance : float
        Maximum gap distance applied to all joint candidate finding and
        creation in :meth:`join_elements`.

    Examples
    --------
    Typical usage::

        from compas_timber_populator import stud_panel

        populator = stud_panel(panel, standard_beam_width=60.0, stud_spacing=625.0)
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
        self.agents = [agent.clone() for agent in agents] if agents else []
        self.panel = panel
        self.panel_guid = panel.guid if isinstance(panel, Panel) else panel
        self._parse_default_feature_agents(default_feature_agents or {})
        self._resolve_beam_widths(standard_beam_width)
        self.joint_rule_overrides = list(joint_rule_overrides) if joint_rule_overrides else []

    # ------------------------------------------------------------------
    # Initialization methods
    # ------------------------------------------------------------------

    def _resolve_beam_widths(self, standard_beam_width):
        """Fill any unset per-category beam widths on every agent with *standard_beam_width*.

        Parameters
        ----------
        standard_beam_width: float
            populator-level width for any undefined dimensions.
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
        """Rebind :attr:`panel` to the instance with the same guid in *model*.

        Use this when *model* is a copy of the model the populator was created
        from (e.g. a Grasshopper re-solve), so population reads the copy's
        panel and layer geometry.

        Parameters
        ----------
        model : :class:`compas_timber.model.TimberModel`
        """
        self.panel = model.element_by_guid(str(self.panel_guid))

    def _parse_default_feature_agents(self, default_feature_agents):
        """Instantiate a feature agent for every panel feature lacking one.

        Parameters
        ----------
        default_feature_agents : dict[type, :class:`~compas_timber_populator.FeatureAgent`]
            Prototype feature agent per feature class.
        """
        for feature in self.panel.features:
            if any(getattr(agent, "feature", None) is feature for agent in self.agents):
                continue  # a feature agent already handles this feature
            prototype = default_feature_agents.get(type(feature))
            if prototype is None:
                continue

            agent = prototype.clone()
            agent.feature = feature
            self.agents.append(agent)

    @property
    def elements(self):
        """List of all elements placed by all agents."""
        return [e for e in self.model.elements() if not e.children]

    @property
    def layer_tree(self):
        """``{layer_path: Layer}`` for every layer in :attr:`model`."""
        return {layer.layer_path: layer for layer in self.model.layers}

    def __repr__(self):
        return "PanelPopulator({})".format(self.panel)

    # ------------------------------------------------------------------
    # Population pipeline
    # ------------------------------------------------------------------

    def populate_elements(self):
        """Generate, define outlines, extend, split, cull Elements."""
        # model extracted here to ensure the latest version of panel and layer geometry
        self.model = self._build_populator_model()
        self._repoint_agents()
        self._generate_elements()
        self._define_outlines()
        self._extend_elements()
        self._split_elements()
        self._cull_elements()

    def _build_populator_model(self):
        """Extract a fresh populator-space model holding only :attr:`panel`'s layer tree.

        Returns
        -------
        :class:`~compas_timber.model.TimberModel`
        """
        model = self.panel.model.extract_model_from_parent(self.panel)
        # elements on layers will be removed. Elements with parent == the panel will be kept.
        for element in list(model.elements()):
            # skip elements at root-level. these are not on a layer
            if element.parent is None:
                continue
            if not isinstance(element, Layer):
                model.remove_element(element)
        return model

    def _generate_elements(self):
        """Ask each agent to create its elements and add them to the model."""
        for agent in self.agents:
            for layer, elements in agent.generate_elements().items():
                for element in elements:
                    element.transform(layer.transformation_to_local())
                    self.model.add_element(element, parent=layer)

    def _define_outlines(self):
        """Ask each agent to record its boundary outline for every layer it trims.
        """
        for agent in self.agents:
            agent.define_outlines([sub for layer in agent.trimming_layers for sub in _layer_and_sublayers(layer)])

    def _extend_elements(self):
        """Ask each agent to extend its elements toward adjacent boundaries."""
        for agent in self.agents:
            for layer in agent.element_layers:
                boundary_outlines = [a.outline_for_layer(layer) for a in self.agents if a is not agent]
                agent.extend_elements([o for o in boundary_outlines if o is not None], layer)

    def _split_elements(self):
        """Geometrically split beams at agent boundaries."""
        for agent in self.agents:
            for element in self._elements_to_trim(agent):
                segments = agent.split_element(element)
                if segments == [element]:
                    continue
                parent = element.parent
                self.model.remove_element(element)
                for segment in segments:
                    self.model.add_element(segment, parent=parent)

    def _cull_elements(self):
        """Discard out-of-zone beam segments after splitting."""
        for agent in self.agents:
            for element in self._elements_to_trim(agent):
                if agent.cull_element(element):
                    self.model.remove_element(element)

    def _elements_to_trim(self, agent):
        """Yield every element *agent* may trim: those on its trimming layers, minus its own."""
        for layer in agent.trimming_layers:
            for sublayer in _layer_and_sublayers(layer):
                for element in [e for e in sublayer.children if not isinstance(e, Layer)]:
                    if element.attributes.get("agent") is not agent:
                        yield element

    # ------------------------------------------------------------------
    # Joining
    # ------------------------------------------------------------------

    def join_elements(self):
        """Resolve all joint candidates and create joints in the model."""
        solver = ConnectionSolver2D(max_distance=self.max_distance)
        for layer in self.model.layers:
            if layer.sublayers:
                continue
            for cluster in solver.find_joint_clusters(_get_ancestor_beams_for_layer(layer)):
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
        """Try each owning agent's own rules on *cluster*; return ``True`` on the first success.

        Joining errors raised by a matching rule are collected onto
        :attr:`debug_info` rather than silently dropped, and the next agent
        still gets its turn.
        """
        for agent in self.agents:
            try:
                joint = agent.get_cluster_joint(cluster, max_distance=max_distance)
            except BeamJoiningError as error:
                self.debug_info.add_joint_error(error)
                continue
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

    # ------------------------------------------------------------------
    # Finalization
    # ------------------------------------------------------------------

    def process_joinery(self):
        """Compute and apply fabrication features (BTLx processings) to all elements (stage 7)."""
        self.debug_info.add_joint_error(self.model.process_joinery())

    def merge_with_model(self, model, clear_panel=True):
        """Move the populated layer subtree back under the original panel in *model*.

        Parameters
        ----------
        model : :class:`compas_timber.model.TimberModel`
            The caller's model to merge into.  The original panel must already be
            present so the layers have a parent to reattach to.
        clear_panel : bool, optional
            When ``True``, removes all existing children of :attr:`panel`
            (and their joints) from *model* before merging.  Use this to
            re-populate a panel that has already been processed.
        """
        for element in self.model.elements():
            # the ownership tag is only meaningful inside the populator; don't leak agents into the caller's model
            element.attributes.pop("agent", None)
            if isinstance(element, Beam2D):
                element.to_beam()
        if clear_panel:
            model.remove_element_subtree(self.panel)
        model.merge_model(self.model, parent=self.panel)


def _get_ancestor_beams_for_layer(layer):
    """Every :class:`~compas_timber_populator.connections_2d.Beam2D` on *layer* or any of its ancestor layers."""
    beams = []

    def walk_up(current_layer):
        beams.extend([b for b in current_layer.children if isinstance(b, Beam2D)])
        if current_layer.parent:
            walk_up(current_layer.parent)

    walk_up(layer)
    return beams


def _layer_and_sublayers(layer):
    """*layer* followed by every layer beneath it, at any depth."""
    layers = [layer]
    for sublayer in layer.sublayers:
        layers.extend(_layer_and_sublayers(sublayer))
    return layers
