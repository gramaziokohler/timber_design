from __future__ import annotations

from timber_design_arch.elements import Layer
from compas_timber.connections import Cluster
from compas_timber.errors import BeamJoiningError
from compas_timber.errors import FeatureApplicationError

from timber_design_populator.connections_2d import Beam2D
from timber_design_populator.connections_2d.connection_solver_2d import ConnectionSolver2D
from timber_design_populator.detail_sets.detail_agent_set import DetailAgentSet
from timber_design_rules import DebugInfomation
from timber_design_rules import JointRuleSolver


class PanelPopulator:
    """Orchestrates the full population of a timber panel with framing elements.

    ``PanelPopulator`` is the top-level coordinator for the panel-population
    workflow and the **sole writer** to its internal model.  It holds a list of
    :class:`~timber_design_populator.PopulatorAgent` instances — each a pure
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
    and trimming, which are performed in 2D by :class:`~timber_design_populator.connections_2d.ConnectionSolver2D`.

    Parameters
    ----------
    panel : :class:`timber_design_arch.elements.Panel`
        The source panel in the caller's model space (or its guid).
    panel_type : :class:`~timber_design_populator.PanelType`
        How the panel is built: its layer structure, the panel-wide agents that build each
        layer, the default detail set per feature type, and the populator settings below.
        The populator takes its own copies, so one type serves any number of populators.

        - **agents**: ordered; the order sets joint precedence (an earlier agent's rules are
          tried first on a cluster).  The populator orders them by
          :attr:`~timber_design_populator.PopulatorAgent.priority`, stably.
        - **default_detail_sets**: the detail set per feature class, used for every panel
          feature of that class that has no ``detail_set`` of its own.
        - **standard_beam_width**: fills any per-category width an agent did not set.
        - **joint_rule_overrides**: panel-level joint rules, tried by :meth:`_join_cluster`
          on a cluster only after every owning agent's own rules have failed, and again per
          pairwise candidate.
        - **max_distance**: the maximum gap for finding and creating joints in
          :meth:`join_elements`.  ``None`` resolves to ``0.1``.
        - **layer_structure**: see :attr:`layer_structure`.

    Raises
    ------
    ValueError
        If *panel_type* has a fixed thickness and *panel* is not that thick.

    Attributes
    ----------
    agents : list[:class:`~timber_design_populator.PopulatorAgent`]
        Ordered list of agents.  Each tags every element it generates with
        itself, which is how ownership is tracked from then on.
    panel : :class:`timber_design_arch.elements.Panel`
        Reference to the source panel in the caller's model space.
    model : :class:`compas_timber.model.TimberModel`
        Internal model that accumulates elements and joints during population.
        Owned exclusively by the populator — agents never write to it.
    debug_info : :class:`~timber_design_rules.DebugInfomation`
        Collects joining errors from :meth:`join_elements` and
        :meth:`process_joinery` instead of silently dropping them.
    joint_rule_overrides : list[:class:`~timber_design_rules.CategoryRule` | :class:`~timber_design_rules.CompositeRule`]
        Panel-level joint rules, tried by :meth:`_join_cluster` after the
        owning agents' own rules (first on the whole cluster, then per
        pairwise candidate).
    max_distance : float
        Maximum gap distance applied to all joint candidate finding and
        creation in :meth:`join_elements`.
    panel_type : :class:`~timber_design_populator.PanelType`
        The type the panel is built as.
    layer_structure : :class:`~timber_design_arch.elements.LayerStructure`
        A copy of the type's cross-section.  Given to the panel by
        :meth:`apply_layer_structure` where it has no layers in its model yet,
        so a panel can enter the model without layers.

    Examples
    --------
    Typical usage::

        from timber_design_populator import PanelPopulator, get_panel_type

        populator = PanelPopulator(panel, get_panel_type("stud_wall", stud_spacing=625.0))
        populator.populate_elements()
        populator.join_elements()
        populator.process_joinery()
        populator.merge_with_model(model)
    """

    def __init__(self, panel, panel_type):
        # duck-typed, not isinstance: in Grasshopper the panel may come from an earlier import of the module
        is_panel = hasattr(panel, "guid") and hasattr(panel, "thickness")
        if is_panel:
            panel_type.check_thickness(panel)
        self.panel_type = panel_type
        self.model = None
        self.layer_structure = panel_type.layer_structure.copy()
        self.debug_info = DebugInfomation()
        self.max_distance = panel_type.max_distance if panel_type.max_distance is not None else 0.1
        self.panel = panel
        self.panel_guid = panel.guid if is_panel else panel
        self.default_detail_sets = dict(panel_type.default_detail_sets)
        self.standard_beam_width = panel_type.standard_beam_width
        self.agents, self._agent_errors = _panel_wide_agents(panel_type.agents)
        self._feature_agents = []
        self._feature_sets = []
        self._bind_feature_agents()
        self._resolve_beam_widths(self.standard_beam_width)
        self._sort_agents()
        self.joint_rule_overrides = list(panel_type.joint_rule_overrides)

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
        self.apply_layer_structure()

    def apply_layer_structure(self):
        """Give :attr:`panel` :attr:`layer_structure`, and add its layers to the panel's model, if it has none there.

        A panel whose layers are already in its model (e.g. from
        :meth:`~timber_design_populator.PanelType.apply` and
        :meth:`~timber_design_arch.elements.Panel.merge_layer_structure`) keeps them.  Call it
        before the panel joints compute their features: layer-aware joints read the layers.

        Returns
        -------
        bool
            Whether the layers were applied.
        """
        panel = self.panel
        if panel is None or panel.model is None or panel.layers:
            return False
        panel.layer_structure = self.layer_structure.copy()
        panel.merge_layer_structure(panel.model)
        return True

    def _bind_feature_agents(self):
        """Pick the detail set for every feature :attr:`panel` has now, dropping the previous run's agents.

        Each feature is built by exactly one detail set: its own ``detail_set`` (e.g. the half
        of a connection detail a panel joint put on its interface), or else this populator's
        default for its type.  The sets are expanded by :meth:`_expand_feature_sets` once the
        layers are in populator space.  Runs on every :meth:`populate_elements`: joint-generated
        features are recreated on every model solve, and :meth:`update_panel_from_model` may swap
        :attr:`panel` for a copy.

        Returns
        -------
        list[:class:`~compas_timber.errors.FeatureApplicationError`]
            One per detail set that cannot build its feature, which is skipped.
        """
        bound = set(id(agent) for agent in self._feature_agents)
        self.agents = [agent for agent in self.agents if id(agent) not in bound]
        self._feature_agents = []
        self._feature_sets = []
        errors = []
        for feature in self.panel.features:
            detail_set = feature.detail_set if feature.detail_set is not None else self.default_detail_sets.get(type(feature))
            if detail_set is None:
                continue
            problem = _cannot_build(detail_set, feature)
            if problem:
                errors.append(FeatureApplicationError(None, None, problem))
                continue
            self._feature_sets.append((feature, detail_set.clone()))
        return errors

    def _expand_feature_sets(self):
        """Expand every bound detail set into its agents, now that the layers are in populator space.

        Returns
        -------
        list[:class:`~compas_timber.errors.FeatureApplicationError`]
            The problems the sets report.
        """
        errors = []
        layer_tree = self.layer_tree
        for feature, detail_set in self._feature_sets:
            agents, set_errors = detail_set.expand(feature, self.panel, layer_tree, self.standard_beam_width)
            errors.extend(set_errors)
            for agent in agents:
                self.agents.append(agent)
                self._feature_agents.append(agent)
        self._resolve_beam_widths(self.standard_beam_width)
        self._sort_agents()
        return errors

    def _sort_agents(self):
        """Order the agents by :attr:`~timber_design_populator.PopulatorAgent.priority`, keeping the given order for equal priorities."""
        self.agents.sort(key=lambda agent: agent.priority)

    @property
    def elements(self):
        """List of all elements placed by all agents."""
        return [e for e in self.model.elements() if not e.children]

    @property
    def layer_tree(self):
        """``{layer_path: Layer}`` for every layer in :attr:`model`."""
        return {layer.layer_path: layer for layer in self.model.find_all_elements_of_type(Layer)}

    def __repr__(self):
        return "PanelPopulator({})".format(self.panel)

    # ------------------------------------------------------------------
    # Population pipeline
    # ------------------------------------------------------------------

    def populate_elements(self):
        """Generate, define outlines, extend, split, cull and machine Elements."""
        # a fresh record for this run; the populator is reused across Grasshopper solves
        self.debug_info = DebugInfomation()
        self.apply_layer_structure()
        # model extracted here to ensure the latest version of panel and layer geometry
        self.debug_info.add_feature_error(self._agent_errors)
        self.debug_info.add_feature_error(self._bind_feature_agents())
        self.model = self._build_populator_model()
        self.debug_info.add_feature_error(self._expand_feature_sets())
        self._repoint_agents()
        self._modify_layers()
        self._generate_elements()
        self._define_outlines()
        self._extend_elements()
        self._split_elements()
        self._cull_elements()
        self._machine_elements()

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

    def _modify_layers(self):
        """Let each agent set layer extension planes, then apply them to every layer.

        Layers are the panel's own (moved, not copied, into :attr:`model`), so the
        extensions persist after :meth:`merge_with_model`.  Re-applying the same planes
        on a later run is a no-op.
        """
        layer_tree = self.layer_tree
        claimed = {}  # (layer_path, edge_index) -> the agent that set its extension plane
        for agent in self.agents:
            before = _extension_planes(layer_tree)
            self.debug_info.add_feature_error(agent.modify_layers(layer_tree))
            for key, plane in _extension_planes(layer_tree).items():
                if before.get(key) is plane:
                    continue
                if key in claimed and claimed[key] is not agent:
                    message = "{} and {} both set the extension of edge {} on layer {}; the last one wins.".format(type(claimed[key]).__name__, type(agent).__name__, key[1], key[0])
                    self.debug_info.add_feature_error(FeatureApplicationError(None, None, message))
                claimed[key] = agent
        for layer in layer_tree.values():
            if not isinstance(layer.parent, Layer):  # root layers apply to their sublayers
                layer.apply_edge_extensions()

    def _generate_elements(self):
        """Ask each agent to create its elements and add them to the model."""
        for agent in self.agents:
            for layer, elements in agent.generate_elements().items():
                for element in elements:
                    element.transform(layer.transformation_to_local())
                    self.model.add_element(element, parent=layer)

    def _define_outlines(self):
        """Ask each agent to record its boundary outline for every layer it trims."""
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

    def _machine_elements(self):
        """Let each agent add machining (drillings, notches) to the final elements on its trimming layers.

        Runs after splitting and culling, so machining is only added to elements that are kept.
        Problems the agents report are recorded in :attr:`debug_info` as feature errors.
        """
        for agent in self.agents:
            for element in list(self._elements_to_trim(agent)):
                self.debug_info.add_feature_error(agent.machine_element(element))

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
        for layer in self.model.find_all_elements_of_type(Layer):
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
    """Every :class:`~timber_design_populator.connections_2d.Beam2D` on *layer* or any of its ancestor layers."""
    beams = []

    def walk_up(current_layer):
        beams.extend([b for b in current_layer.children if isinstance(b, Beam2D)])
        if current_layer.parent:
            walk_up(current_layer.parent)

    walk_up(layer)
    return beams


def _panel_wide_agents(agents):
    """Clones of the panel-wide *agents*, plus an error for each detail agent, which is skipped.

    Detail agents are created by detail sets for one feature; given directly they would be
    bound to nothing.
    """
    kept, errors = [], []
    for agent in agents or []:
        if agent.IS_DETAIL:
            message = "{} is a detail agent; detail sets create these for a feature (set the feature's detail_set). Skipped.".format(type(agent).__name__)
            errors.append(FeatureApplicationError(None, None, message))
            continue
        kept.append(agent.clone())
    return kept, errors


def _cannot_build(detail_set, feature):
    """Why *detail_set* cannot build *feature*, or ``None`` if it can."""
    if not isinstance(detail_set, DetailAgentSet):
        return "Not a detail set, skipped: {!r}".format(detail_set)
    if detail_set.FEATURE_TYPES and not isinstance(feature, detail_set.FEATURE_TYPES):
        names = ", ".join(t.__name__ for t in detail_set.FEATURE_TYPES)
        return "{} builds {} features, not {}; skipped.".format(type(detail_set).__name__, names, type(feature).__name__)
    return None


def _extension_planes(layer_tree):
    """``{(layer_path, edge_index): plane}`` of every layer's current edge planes, for spotting which ones an agent set."""
    return {(path, edge): plane for path, layer in layer_tree.items() for edge, plane in layer.plate_geometry.edge_planes.items()}


def _layer_and_sublayers(layer):
    """*layer* followed by every layer beneath it, at any depth."""
    layers = [layer]
    for sublayer in layer.sublayers:
        layers.extend(_layer_and_sublayers(sublayer))
    return layers
