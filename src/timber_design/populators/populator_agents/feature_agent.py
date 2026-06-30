from abc import abstractmethod

from compas_timber.elements import Layer
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
    - :attr:`trimming_layers` — if non-empty, :meth:`split_agent_elements`
      restricts itself to agents whose layer is in this list.  When empty the
      subclass's own default logic applies.

    Both lists are resolved from :attr:`FeatureAgentConfig.framing_layer_defs`
    and :attr:`FeatureAgentConfig.trimming_layer_defs` by
    :meth:`~PanelPopulatorConfig.create_feature_agents`.

    Element tracking
    ----------------
    - ``self.elements`` — flat list of **all** elements across all layers.
    - ``self.elements_by_layer`` — ``{layer_index: [elements]}`` dict for
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
        # type: (object, Optional[list], Optional[list], Optional[list], Optional[list]) -> None
        super().__init__(internal_joint_overrides, external_joint_overrides)
        self.feature = feature
        self.element_layer_paths = []
        for el in element_layers or []:
            if isinstance(el, Layer):
                self.element_layer_paths.append(el.layer_path)
            else:
                self.element_layer_paths.append(el)

        self.trimming_layer_paths = []
        for tl in trimming_layers or []:
            if isinstance(tl, Layer):
                self.trimming_layer_paths.append(tl.layer_path)
            else:
                self.trimming_layer_paths.append(tl)

        self._element_layers = []
        self._trimming_layers = []


    @property
    def element_layers(self):
        return self._element_layers

    @property
    def trimming_layers(self):
        return self._trimming_layers


    def repoint_to_layer_tree(self, tree):
        """Rebind this agent's layer references to the current panel's layer tree by path."""
        if self.element_layer_paths:
            self._element_layers = [tree[p] for p in self.element_layer_paths if p in tree]
        if self.trimming_layer_paths:
            self._trimming_layers = [tree[p] for p in self.trimming_layer_paths if p in tree]

    @property
    def __data__(self):
        data = super().__data__
        data["feature"] = self.feature
        data["element_layers"] = self.element_layer_paths
        data["trimming_layers"] = self.trimming_layer_paths
        return data

    def generate_elements(self):
        """Generate (and store) this agent's elements.

        With *layer* given, generates only on that layer; otherwise on every
        framing layer in :attr:`element_layers`.  The populator drives this one
        layer at a time (mirroring :meth:`split_agent_elements` /
        :meth:`extend_elements`), but the no-argument form is kept for callers
        that want the whole agent generated at once.
        """
        # Clear stale entries from previous solves before regenerating.
        self.elements_by_layer.clear()
        self.outline_by_layer.clear()
        for layer in self.element_layers:
            layer_elements, layer_outline = self.generate_elements_for_layer(layer)
            self.elements_by_layer[layer] = layer_elements  # add to per-layer dict
            self.outline_by_layer[layer] = layer_outline  # capture per-layer boundary


    def _compute_outline_for_layer(self, layer):
        """Return this feature's footprint outline on *layer*.

        Subclasses implement the feature-specific footprint (e.g. the opening
        frame).  Called for both framing and trimming layers, so it must not
        depend on elements having been generated on *layer*.
        """
        raise NotImplementedError

    def create_joint_candidates(self, layer=None):
        """Return within-agent joint candidates, pairing beams per layer.

        With *layer* given, only that layer's bucket is paired; otherwise every
        layer this agent has elements on.  Pairs are always formed *within* a
        single layer so a beam on one layer is never joined to one on another.
        """
        from compas_timber.connections import JointCandidate

        from timber_design.connections_2d.beam2d import Beam2D
        from timber_design.connections_2d.connection_solver_2d import ConnectionSolver2D

        candidates = []
        solver = ConnectionSolver2D()
        layers = [layer] if layer is not None else list(self.elements_by_layer.keys())
        for layer in layers:
            elements = self.elements_by_layer.get(layer, [])
            beam_elements = [e for e in elements if isinstance(e, Beam2D)]
            pairs = solver.find_intersecting_pairs(beam_elements)
            for element_a, element_b in pairs:
                topo_result = solver.find_topology(element_a, element_b)
                if topo_result is not None:
                    candidate = JointCandidate(topo_result.beam_a, topo_result.beam_b, distance=topo_result.distance, topology=topo_result.topology, location=topo_result.location)
                    candidates.append(candidate)
        return candidates


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
