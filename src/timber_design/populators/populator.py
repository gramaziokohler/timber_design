from itertools import product

from compas_timber.connections import JointCandidate
from compas_timber.connections import get_clusters_from_joint_candidates
from compas_timber.model import TimberModel

from timber_design.populators.connection_solver_2d import ConnectionSolver2D
from timber_design.workflow import JointRuleSolver


class PanelPopulator(object):
    """Orchestrates the full population of a timber panel with framing elements.

    ``PanelPopulator`` is the top-level coordinator for the panel-population
    workflow.  It holds a list of :class:`~timber_design.populators.PopulatorAgent`
    instances — each responsible for one logical group of elements (edge beams,
    studs, plates, openings, …) — and drives them through a fixed sequence of
    stages:

    1. **generate_elements** — each agent creates its beams and plates.
    2. **extend_elements** — agents extend elements to reach adjacent agent boundaries (e.g. king/jack studs extended to plate beams).
    3. **trim_elements** — two sub-passes:

       a. **trim_within_layer_elements** — agents on the same layer trim each other
          (edge frame clips studs; openings clip studs).
       b. **trim_cross_layer_elements** — agents on different layers apply targeted
          trimming governed by :meth:`~timber_design.populators.PopulatorAgent.affects_layer`
          (recess frame cuts sheeting plates; openings cut all layers).

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
    agents : list[:class:`~timber_design.populators.PopulatorAgent`]
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
    agents : list[:class:`~timber_design.populators.PopulatorAgent`]
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

    def __init__(self, panel, agents, original_panel=None, transformation_to_populator=None):
        super(PanelPopulator, self).__init__()
        self.panel = panel
        self.agents = agents
        self.original_panel = original_panel
        self.transformation_to_populator = transformation_to_populator
        self.model = TimberModel()

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
        for g in self.agents:
            g.generate_elements()

    def extend_elements(self):
        """Ask each agent to extend its elements toward adjacent boundaries (stage 2)."""
        for g in self.agents:
            other_agents = [a for a in self.agents if a != g and a.layer_index == g.layer_index]
            g.extend_elements(other_agents)

    def trim_elements(self):
        """Split beams at agent boundaries and discard out-of-zone segments (stage 3).

        Runs two passes in sequence:

        1. :meth:`trim_within_layer_elements` — agents on the **same** layer
           trim each other (e.g. edge frame clips studs; openings clip studs).
        2. :meth:`trim_cross_layer_elements` — agents on **different** layers
           apply targeted trimming where
           :meth:`~timber_design.populators.PopulatorAgent.affects_layer`
           returns ``True`` (e.g. a recess frame cuts sheeting plates on lower
           layers; openings cut through all layers).

        This mirrors the ``create_agent_joints`` / ``create_cross_agent_joints``
        pattern in :meth:`join_elements`, making the topology of inter-agent
        interactions explicit at the orchestration level.
        """
        self.trim_within_layer_elements()
        self.trim_cross_layer_elements()

    def trim_within_layer_elements(self):
        """Trim elements between agents that share the same layer index (stage 3a).

        Iterates all overlapping agent pairs.  For those whose
        :attr:`~timber_design.populators.PopulatorAgent.layer_index` matches,
        :meth:`~timber_design.populators.PopulatorAgent.trim_elements_with_agent`
        is called symmetrically on both agents.

        Typical interactions handled here:

        - Edge frame clips studs and opening elements to the panel boundary.
        - Opening surround clips studs that pass through a door or window.
        """
        solver = ConnectionSolver2D()
        for agent_a, agent_b in solver.find_intersecting_agent_pairs(self.agents):
            if agent_a.layer_index != agent_b.layer_index:
                continue
            agent_a.trim_elements_with_agent(agent_b)
            agent_b.trim_elements_with_agent(agent_a)

    def trim_cross_layer_elements(self):
        """Apply trimming between agents on different layers (stage 3b).

        Iterates all overlapping agent pairs where the two agents have
        *different* :attr:`~timber_design.populators.PopulatorAgent.layer_index`
        values.  Each agent's
        :meth:`~timber_design.populators.PopulatorAgent.affects_layer` method
        independently decides whether it should trim the other agent's elements.

        Typical cross-layer interactions:

        - :class:`~timber_design.populators.RecessPopulatorAgent` cuts sheeting
          plates on lower (inside) layers.
        - :class:`~timber_design.populators.OpeningPopulatorAgent` cuts openings
          through sheathing plates on all layers.
        """
        solver = ConnectionSolver2D()
        for agent_a, agent_b in solver.find_intersecting_agent_pairs(self.agents):
            if agent_a.layer_index == agent_b.layer_index:
                continue
            if agent_b.affects_layer(agent_a.layer_index):
                agent_a.trim_elements_with_agent(agent_b)
            if agent_a.affects_layer(agent_b.layer_index):
                agent_b.trim_elements_with_agent(agent_a)

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
        """Create joints between elements that belong to the same agent.

        Each agent collects its own joint candidates via
        :meth:`~timber_design.populators.PopulatorAgent.create_internal_joint_defs`,
        then each :class:`~timber_design.workflow.DirectRule` in
        ``agent.joint_defs`` is immediately applied to the model.
        """
        for agent in self.agents:
            agent.create_internal_joint_defs(self.model)
            for j_def in agent.joint_defs:
                j_def.joint_type.create(self.model, *j_def.elements, **j_def.kwargs)

    def create_cross_agent_joints(self):
        """Create joints between elements that belong to different agents.

        For each overlapping same-layer agent pair the solver enumerates all
        cross-product element pairs, detects topology, collects
        :class:`~compas_timber.connections.JointCandidate` objects, clusters
        them by proximity, and hands the clusters to a
        :class:`~timber_design.workflow.JointRuleSolver` built from the
        combined :attr:`~timber_design.populators.PopulatorAgent.external_rules`
        of both agents.
        """
        solver = ConnectionSolver2D()
        for agent_a, agent_b in solver.find_intersecting_agent_pairs(self.agents):
            if agent_a.layer_index != agent_b.layer_index:
                continue
            candidates = []
            for element_a, element_b in product(agent_a.elements, agent_b.elements):
                topo_result = solver.find_topology(element_a, element_b)
                if topo_result is not None:
                    candidate = JointCandidate(topo_result.beam_a, topo_result.beam_b, distance=topo_result.distance, topology=topo_result.topology, location=topo_result.location)
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
