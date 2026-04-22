from itertools import product

from compas_timber.connections import JointCandidate
from compas_timber.connections import get_clusters_from_joint_candidates
from compas_timber.model import TimberModel

from timber_design.populators.connection_solver_2d import ConnectionSolver2D
from timber_design.workflow import JointRuleSolver


class PanelPopulator(object):
    """Orchestrates the full population of a timber panel with framing elements.

    ``PanelPopulator`` is the top-level coordinator for the panel-population
    workflow.  It holds a list of :class:`~timber_design.populators.LayerAgent`
    instances — each responsible for one logical group of elements (edge beams,
    studs, plates, openings, …) — and drives them through a fixed sequence of
    stages:

    1. **generate_elements** — each agent creates its beams and plates.
    2. **extend_elements** — agents extend elements to reach adjacent agent boundaries (e.g. king/jack studs extended to plate beams).
    3. **trim_elements** — for each overlapping agent pair, dispatches to
       :meth:`~timber_design.populators.LayerAgent.trim_within_layer`
       (same layer) or
       :meth:`~timber_design.populators.LayerAgent.trim_cross_layer`
       (different layers).  Each agent's implementation decides what to do.

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

    def __init__(self, panel, layers, feature_agents, original_panel=None, transformation_to_populator=None):
        super(PanelPopulator, self).__init__()
        self.panel = panel
        self.layers = layers
        self.feature_agents = feature_agents
        self.original_panel = original_panel
        self.transformation_to_populator = transformation_to_populator
        self.model = TimberModel()

    @property
    def agents(self):
        """Deduplicated list of every :class:`LayerAgent` across all layers + feature agents.

        :class:`FeatureAgent` instances register themselves on multiple layers
        during :meth:`generate_elements`, so a plain flatten of ``layer.agents``
        would contain duplicates.  This property preserves first-seen order
        and appends any feature agents that never registered on a layer.
        """
        seen = []
        for layer in self.layers:
            for agent in layer.agents:
                if agent not in seen:
                    seen.append(agent)
        for agent in self.feature_agents:
            if agent not in seen:
                seen.append(agent)
        return seen

    def __repr__(self):
        return "PanelPopulator({})".format(self.panel)

    def populate_elements(self):
        """Execute stages 1–4: generate, extend, trim, and add elements to the model.

        Call :meth:`join_elements` and :meth:`process_joinery` afterwards to
        complete the population workflow.
        """
        self.generate_elements()
        self.extend_elements()
        self.trim_elements()
        self.add_elements_to_model()

    def generate_elements(self):
        """Ask each agent to create its beams and plates (stage 1)."""
        for layer in self.layers:
            for agent in layer.agents:
                agent.generate_elements()
        for agent in self.feature_agents:
            agent.generate_elements(self.layers)

    def extend_elements(self):
        """Ask each agent to extend its elements toward adjacent boundaries (stage 2)."""
        for layer in self.layers:
            for g in layer.agents:
                other_agents = [a for a in layer.agents if a is not g]
                g.extend_elements(other_agents)

    def trim_elements(self):
        """Split beams at agent boundaries and discard out-of-zone segments (stage 3).

        Two passes are performed:

        1. **Within-layer** — for each overlapping agent pair on the same layer,
           both agents get a chance to trim the other's layer-elements via
           :meth:`~timber_design.populators.LayerAgent.trim_within_layer`.
        2. **Cross-layer** — every agent calls
           :meth:`~timber_design.populators.LayerAgent.trim_other_layers` to
           apply any cross-layer modifications (e.g. a recess agent cutting
           sheathing plates on the interior layer, or an opening agent
           punching through plates on non-framing layers).
        """
        solver = ConnectionSolver2D()
        for layer in self.layers:
            for agent_a, agent_b in solver.find_intersecting_agent_pairs(layer.agents):
                agent_a.trim_within_layer(agent_b, layer)
                agent_b.trim_within_layer(agent_a, layer)
        for agent in self.agents:
            agent.trim_other_layers(self.layers)

    def add_elements_to_model(self):
        """Add all surviving elements to the internal model (stage 4)."""
        for agent in self.agents:
            for element in agent.elements:
                self.model.add_element(element)

    def join_elements(self):
        """Resolve all joint candidates and create joints in the model (stage 5).

        Runs :meth:`create_agent_joints` first (within-agent joints),
        then :meth:`create_cross_agent_joints` (between-agent joints).
        """
        self.create_agent_joints()
        self.create_cross_agent_joints()

    def create_agent_joints(self):
        """Create joints between elements that belong to the same agent (stage 5a).

        Iterates every layer and, for each agent registered on that layer,
        detects internal joint candidates using only the elements that agent
        placed on *that* layer via
        :meth:`~timber_design.populators.LayerAgent.elements_for_layer`.
        This prevents a :class:`~timber_design.populators.FeatureAgent`
        (which registers on multiple layers) from creating joints between
        elements that live on different layers.

        ``agent.joint_defs`` is cleared after each layer pass so that a
        multi-layer agent is not double-applied on subsequent layers.
        """
        for layer in self.layers:
            for agent in layer.agents:
                layer_elements = agent.elements_for_layer(layer)
                agent.create_internal_joint_defs(self.model, elements=layer_elements)
                for j_def in agent.joint_defs:
                    j_def.joint_type.create(self.model, *j_def.elements, **j_def.kwargs)
                agent.joint_defs.clear()

    def create_cross_agent_joints(self):
        """Create joints between elements of different agents on the same layer (stage 5b).

        For each overlapping agent pair the solver enumerates cross-product
        element pairs, restricting each agent's contribution to the elements
        it placed on *this* layer via
        :meth:`~timber_design.populators.LayerAgent.elements_for_layer`.
        This keeps joints from being created between, say, king studs generated
        by a :class:`~timber_design.populators.FeatureAgent` on one layer and
        plate beams on a different layer.
        """
        solver = ConnectionSolver2D()
        for layer in self.layers:
            for agent_a, agent_b in solver.find_intersecting_agent_pairs(layer.agents):
                elements_a = agent_a.elements_for_layer(layer)
                elements_b = agent_b.elements_for_layer(layer)
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
                jrs = JointRuleSolver(agent_a.external_rules + agent_b.external_rules)
                jrs.joints_from_rules_and_clusters(self.model, clusters=clusters)

    def process_joinery(self):
        """Compute and apply fabrication features (BTLx processings) to all elements (stage 6)."""
        self.model.process_joinery()

    def merge_with_model(self, model, clear_panel=False):
        """Transform elements back to world space and attach them to the caller's model (stage 7).

        Parameters
        ----------
        model : :class:`compas_timber.model.TimberModel`
            The caller's model to merge into.
        clear_panel : bool, optional
            When ``True``, removes all existing children of :attr:`original_panel`
            (and their joints) from *model* before merging.  Use this to
            re-populate a panel that has already been processed.
        """
        if clear_panel:
            for element in self.original_panel.children[:]:
                model.remove_element(element)
        for element in self.model.elements():
            element.transform(self.transformation_to_populator.inverse())
            model.add_element(element, parent=self.original_panel)
        for j in self.model.joints:
            model.add_joint(j)
