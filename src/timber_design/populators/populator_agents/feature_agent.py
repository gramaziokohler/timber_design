from abc import abstractmethod

from .populator_agent import PopulatorAgent


class FeatureAgent(PopulatorAgent):
    """Abstract base class for feature-driven populator agents.

    Extends :class:`LayerAgent` by accepting a
    :class:`~compas_timber.panel_features.PanelFeature` and storing it as
    :attr:`feature`.  Subclasses handle specific feature types (e.g.
    :class:`~timber_design.populators.OpeningPopulatorAgent` for
    :class:`~compas_timber.panel_features.Opening`).

    Layer selection
    ---------------
    Which layers receive generated elements (*framing*) and which have plates
    cut (*trimming*) is controlled by two explicit lists:

    - :attr:`element_layers` — if non-empty, only these layers are passed to
      :meth:`generate_elements_for_layer`.  Falls back to
      ``layer.is_framing_layer`` when empty.
    - :attr:`trimming_layers` — if non-empty, :meth:`trim_agent_elements`
      restricts itself to agents whose layer is in this list.  When empty the
      subclass's own default logic applies.

    Both lists are resolved from :attr:`FeatureAgentConfig.framing_layer_defs`
    and :attr:`FeatureAgentConfig.trimming_layer_defs` by
    :meth:`~PanelPopulatorConfig.create_feature_agents`.

    Element tracking
    ----------------
    - ``self.elements`` — flat list of **all** elements across all layers.
    - ``self._elements_by_layer`` — ``{layer_index: [elements]}`` dict for
      per-layer trim and joint passes.

    Parameters
    ----------
    feature : :class:`~compas_timber.panel_features.PanelFeature`
        The (possibly transformed) feature instance driving element placement.
    element_layers : list[:class:`~timber_design.populators.Layer`], optional
        Explicit framing layers; overrides ``is_framing_layer`` fallback.
    trimming_layers : list[:class:`~timber_design.populators.Layer`], optional
        Explicit trimming layers; restricts cross-layer plate cutting.
    beam_widths : dict[str, float], optional
        ``{category: width}`` mapping resolved by the config.
    internal_joint_overrides, external_joint_overrides : list, optional
        Per-agent joint-rule overrides forwarded by the config.
    """

    FEATURE_TYPE = None

    def __init__(self, feature, element_layers=None, trimming_layers=None, internal_joint_overrides=None, external_joint_overrides=None):
        # type: (object, list, list, Optional[list], Optional[list]) -> None
        super().__init__(internal_joint_overrides, external_joint_overrides)
        self.feature = feature
        self.element_layers = element_layers or []
        self.trimming_layers = trimming_layers or []
        # Per-layer element tracking.  Populated during generate_elements.
        self.elements_by_layer = {}
        # Per-layer boundary outline.  A feature agent frames on several layers,
        # so it has one boundary per layer; trimming/culling on a given layer
        # must use that layer's outline (see outline_for_layer).
        self.outline_by_layer = {}
        # Layers this agent has registered itself on during generate_elements.
        self.registered_layers = []

    @property
    def __data__(self):
        data = super().__data__
        data["feature"] = self.feature
        data["element_layers"] = self.element_layers or None
        data["trimming_layers"] = self.trimming_layers or None
        return data

    # ------------------------------------------------------------------
    # Layer membership
    # ------------------------------------------------------------------

    def _agent_layers(self):
        return list(self.registered_layers)

    def create_joint_candidates(self):
        """Return joint candidates per layer, using the per-layer element dict."""
        from compas_timber.connections import JointCandidate

        from timber_design.populators.beam2d import Beam2D
        from timber_design.populators.connection_solver_2d import ConnectionSolver2D

        candidates = []
        solver = ConnectionSolver2D()
        for elements in self._elements_by_layer.values():
            beam_elements = [e for e in elements if isinstance(e, Beam2D)]
            pairs = solver.find_intersecting_pairs(beam_elements)
            for element_a, element_b in pairs:
                topo_result = solver.find_topology(element_a, element_b)
                if topo_result is not None:
                    candidate = JointCandidate(topo_result.beam_a, topo_result.beam_b, distance=topo_result.distance, topology=topo_result.topology, location=topo_result.location)
                    candidates.append(candidate)
        return candidates

    # ------------------------------------------------------------------
    # Unified element API (overrides LayerAgent defaults)
    # ------------------------------------------------------------------

    def elements_for_layer(self, layer):
        """Return the elements this agent placed on *layer*.

        Parameters
        ----------
        layer : :class:`~timber_design.populators.Layer`

        Returns
        -------
        list
        """
        return self._elements_by_layer.get(layer, [])

    def outline_for_layer(self, layer):
        """Return the boundary outline this agent generated on *layer*.

        A feature agent frames on multiple layers and stores one outline per
        layer (see :meth:`generate_elements`), so a peer trimming on a given
        layer always uses that layer's boundary rather than the last one
        generated.
        """
        if layer is None:
            return self.outline
        return self._outline_by_layer.get(layer)

    def set_elements_for_layer(self, layer, elements):
        """Replace the element list for *layer* and rebuild ``self.elements``.

        Called by :meth:`~PopulatorAgent.trim_elements` after trimming so that
        both the per-layer dict and the flat list stay consistent.

        Parameters
        ----------
        layer : :class:`~timber_design.populators.Layer`
        elements : list
        """
        self._elements_by_layer[layer] = elements
        # Rebuild flat list from all layer buckets, preserving insertion order.


    @property
    def elements(self):
        return [e for lst in self._elements_by_layer.values() for e in lst]


    # ------------------------------------------------------------------
    # Layer registration
    # ------------------------------------------------------------------

    def is_on_layer(self, layer):
        """Tests whether this agent is active on *layer*.
        Parameters
        ----------
        layer : :class:`~timber_design.populators.Layer`
            The layer to check.
        """
        return layer in self.element_layers + self.trimming_layers


    def is_on_panel(self, panel):
        """Tests whether this agent is active on *layer*.
        Parameters
        ----------
        layer : :class:`~timber_design.populators.Layer`
            The layer to check.
        """
        return self.feature in panel.features

    # ------------------------------------------------------------------
    # Cross-layer trimming
    # ------------------------------------------------------------------

    def _trim_layers(self):
        """A feature agent trims peers on every layer it frames *and* trims.

        ``trim_elements`` itself is inherited from :class:`PopulatorAgent`; a
        feature agent only differs in *which* layers it acts on — its framing
        layers (where it placed studs) plus its trimming layers (e.g. sheathing
        plates it must cut through).
        """
        return self.element_layers + self.trimming_layers
