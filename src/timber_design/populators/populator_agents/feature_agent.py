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
        # type: (object, list, list, Optional[list], Optional[list]) -> None
        super().__init__(internal_joint_overrides, external_joint_overrides)
        self.feature = feature
        # Coerce to a real Python list: GH passes inputs as a .NET
        # ``System.Collections.Generic.List``; storing that directly makes
        # ``set(...)`` / identity logic and ``__data__`` round-tripping behave
        # inconsistently downstream.
        self.element_layers = list(element_layers) if element_layers else []
        self.trimming_layers = list(trimming_layers) if trimming_layers else []


    @property
    def __data__(self):
        data = super().__data__
        data["feature"] = self.feature
        data["element_layers"] = self.element_layers or None
        data["trimming_layers"] = self.trimming_layers or None
        return data

    def define_trimming_outlines(self):
        """Define this feature's footprint outline on every layer it trims.

        ``generate_elements`` already sets the outline on the layers the feature
        frames on.  This fills in the remaining layers in :meth:`layers_to_trim`
        (trimming layers and their sublayers that the feature does not frame), so
        the feature culls peer beams there just as :meth:`trim_plate` already
        cuts plates there.  Layers that already have an outline are left as-is.
        """
        for layer in self.layers_to_trim():
            if self.outline_by_layer.get(layer) is None:
                self.outline_by_layer[layer] = self._compute_outline_for_layer(layer)

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

        from timber_design.populators.beam2d import Beam2D
        from timber_design.populators.connection_solver_2d import ConnectionSolver2D

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
