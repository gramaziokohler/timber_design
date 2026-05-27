from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from typing import Optional
from compas_timber.connections import JointCandidate
from timber_design.populators import aabb_overlap

from .populator_agent import PopulatorAgent
from .populator_agent import PopulatorAgentConfig


from timber_design.populators.beam2d import Beam2D
from timber_design.populators.connection_solver_2d import ConnectionSolver2D

@dataclass
class FeatureAgentConfig(PopulatorAgentConfig, ABC):
    """Config base class for feature-based populator agents.

    Extends :class:`LayerAgentConfig` with an optional :attr:`feature` field,
    explicit layer lists for framing and trimming, and two factory methods:

    - :meth:`get_agent` — creates the agent from :attr:`feature` (must be set).
    - :meth:`get_agent_from_feature` — creates the agent from an explicitly
      supplied feature, ignoring :attr:`feature`.

    Parameters
    ----------
    feature : :class:`~compas_timber.panel_features.PanelFeature`, optional
        The panel feature instance driving element placement.  When set,
        :meth:`get_agent` can be called without any additional arguments.
    framing_layer_defs : list[:class:`~timber_design.populators.LayerConfig`], optional
        The layers on which this feature agent generates framing elements.
        Pass the same :class:`LayerConfig` objects given to
        :class:`~timber_design.populators.PanelPopulatorConfig` as
        ``layer_defs``; the config resolves them to :class:`Layer` objects.
        When ``None`` the agent falls back to populating every layer whose
        :attr:`~timber_design.populators.Layer.is_framing_layer` flag is
        ``True``.
    trimming_layer_defs : list[:class:`~timber_design.populators.LayerConfig`], optional
        The layers whose plate elements this feature agent modifies in the
        cross-layer trim pass (e.g. punching an opening through sheathing).
        When ``None`` the agent falls back to its subclass default behaviour.
    """

    IS_ABSTRACT = True

    feature: Optional[object] = None
    framing_layer_defs: Optional[list] = None
    trimming_layer_defs: Optional[list] = None

    @property
    def __data__(self):
        data = super().__data__
        data["feature"] = self.feature
        # LayerConfig objects are resolved at runtime; not round-tripped here.
        return data

    def get_agent(self):
        """Instantiate a feature-based agent using the stored :attr:`feature`.

        Returns
        -------
        :class:`FeatureAgent`

        Raises
        ------
        ValueError
            If :attr:`feature` is ``None``.
        NotImplementedError
            If ``AGENT_TYPE`` has not been set on this config class.
        """
        if self.feature is None:
            raise ValueError("{} has no feature set. Pass it to the constructor or call get_agent_from_feature(feature) instead.".format(type(self).__name__))
        return self.get_agent_from_feature(self.feature)

    def get_agent_from_feature(self, feature, framing_layers=None, trimming_layers=None, standard_beam_width=None):
        """Construct this config's :class:`FeatureAgent` for *feature*.

        The agent is built with explicit keyword arguments assembled by
        :meth:`~PopulatorAgentConfig._agent_kwargs` — the agent never receives
        the config object itself.  A :class:`FeatureAgent` is not bound to a
        single layer at construction time; layers are passed explicitly.

        Parameters
        ----------
        feature : :class:`~compas_timber.panel_features.PanelFeature`
            The (possibly transformed) feature instance.
        framing_layers : list[:class:`~timber_design.populators.Layer`], optional
            Resolved :class:`Layer` objects for element generation.
        trimming_layers : list[:class:`~timber_design.populators.Layer`], optional
            Resolved :class:`Layer` objects for cross-layer plate trimming.
        standard_beam_width : float, optional
            Convenience for constructing an agent in isolation: when given,
            any unset beam-category widths are filled first.  In the full
            pipeline widths are pre-filled by
            :meth:`~timber_design.populators.PanelPopulatorConfig.resolve_beam_widths`.

        Returns
        -------
        :class:`FeatureAgent`

        Raises
        ------
        NotImplementedError
            If ``AGENT_TYPE`` has not been set on this config class.
        """
        if self.AGENT_TYPE is None:
            raise NotImplementedError("{} does not define AGENT_TYPE".format(type(self).__name__))
        if standard_beam_width is not None:
            self.fill_beam_widths(standard_beam_width)
        return self.AGENT_TYPE(feature, framing_layers, trimming_layers, **self._agent_kwargs())


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

    - :attr:`framing_layers` — if non-empty, only these layers are passed to
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
    framing_layers : list[:class:`~timber_design.populators.Layer`], optional
        Explicit framing layers; overrides ``is_framing_layer`` fallback.
    trimming_layers : list[:class:`~timber_design.populators.Layer`], optional
        Explicit trimming layers; restricts cross-layer plate cutting.
    beam_widths : dict[str, float], optional
        ``{category: width}`` mapping resolved by the config.
    internal_joint_overrides, external_joint_overrides : list, optional
        Per-agent joint-rule overrides forwarded by the config.
    """

    FEATURE_TYPE = None

    def __init__(self, feature, framing_layers=None, trimming_layers=None, beam_widths=None, internal_joint_overrides=None, external_joint_overrides=None):
        # type: (object, list, list, Optional[dict], Optional[list], Optional[list]) -> None
        super().__init__(beam_widths, internal_joint_overrides, external_joint_overrides)
        self.feature = feature
        self.framing_layers = framing_layers or []
        self.trimming_layers = trimming_layers or []
        # Per-layer element tracking.  Populated during generate_elements.
        self._elements_by_layer = {}
        # Per-layer boundary outline.  A feature agent frames on several layers,
        # so it has one boundary per layer; trimming/culling on a given layer
        # must use that layer's outline (see outline_for_layer).
        self._outline_by_layer = {}
        # Layers this agent has registered itself on during generate_elements.
        self.registered_layers = []

    # ------------------------------------------------------------------
    # Layer membership
    # ------------------------------------------------------------------

    def _agent_layers(self):
        return list(self.registered_layers)

    def create_joint_candidates(self):
        """Return joint candidates per layer, using the per-layer element dict."""
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
        return self._elements_by_layer.get(layer.layer_index, [])

    def outline_for_layer(self, layer):
        """Return the boundary outline this agent generated on *layer*.

        A feature agent frames on multiple layers and stores one outline per
        layer (see :meth:`generate_elements`), so a peer trimming on a given
        layer always uses that layer's boundary rather than the last one
        generated.
        """
        if layer is None:
            return self.outline
        return self._outline_by_layer.get(layer.layer_index)

    def set_elements_for_layer(self, layer, elements):
        """Replace the element list for *layer* and rebuild ``self.elements``.

        Called by :meth:`~LayerAgent.trim_within_layer` after trimming so that
        both the per-layer dict and the flat list stay consistent.

        Parameters
        ----------
        layer : :class:`~timber_design.populators.Layer`
        elements : list
        """
        self._elements_by_layer[layer.layer_index] = elements
        # Rebuild flat list from all layer buckets, preserving insertion order.
        self.elements = [e for lst in self._elements_by_layer.values() for e in lst]

    # ------------------------------------------------------------------
    # Layer registration
    # ------------------------------------------------------------------

    def register_on_layer(self, layer):
        """Record this agent as active on *layer* and expose it to peer agents.

        Appends ``self`` to ``layer.agents`` (if not already present) so that
        :class:`~timber_design.populators.PanelPopulator`'s per-layer passes
        (extend / within-layer trim / within-layer joints) treat this feature
        agent as a peer of the layer's regular :class:`LayerAgent` instances.

        Parameters
        ----------
        layer : :class:`~timber_design.populators.Layer`
            The layer to register on.
        """
        if layer is None:
            return
        if self not in layer.agents:
            layer.agents.append(self)
        if layer not in self.registered_layers:
            self.registered_layers.append(layer)

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def generate_elements(self):
        """Generate elements across all relevant layers.

        Calls :meth:`generate_elements_for_layer` for every layer.  When
        elements are returned the agent registers itself on that layer so
        subsequent within-layer trim and join passes treat it as a peer.
        Layers where no elements are generated are not registered — cross-layer
        trimming on those layers is handled via :meth:`trim_other_layers`.

        Parameters
        ----------
        layers : list[:class:`~timber_design.populators.Layer`]
            All layers in the populator.
        """
        for layer in self.framing_layers:
            # generate_elements_for_layer sets self.outline for the layer it is
            # working on; capture it per-layer so later trim/cull passes use the
            # correct boundary for each layer rather than the last one generated.
            self.outline = None
            layer_elements = self.generate_elements_for_layer(layer)
            self._elements_by_layer[layer.layer_index] = layer_elements  # add to per-layer dict
            self._outline_by_layer[layer.layer_index] = self.outline  # capture per-layer boundary
            self.elements.extend(layer_elements)  # add to general elements list
            # Register only on layers where elements were placed.
            if layer_elements:
                self.register_on_layer(layer)

    @abstractmethod
    def generate_elements_for_layer(self, layer):
        """Generate and return elements for a single *layer*.

        Subclasses should call :meth:`_is_framing_layer` to decide whether to
        act on *layer* and return an empty list for layers they skip.

        Parameters
        ----------
        layer : :class:`~timber_design.populators.Layer`

        Returns
        -------
        list
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Cross-layer trimming
    # ------------------------------------------------------------------

    def trim_elements(self):
        """Apply :meth:`trim_agent_elements` to agents on layers this agent is not registered on.

        Overrides :meth:`LayerAgent.trim_other_layers` to skip registered
        layers (where within-layer trimming already handled peer interaction).

        Parameters
        ----------
        layers : list[:class:`~timber_design.populators.Layer`]
            All layers in the populator.
        """
        for layer in self.framing_layers + self.trimming_layers:
            for other_agent in layer.agents:
                if other_agent is self:
                    continue
                if aabb_overlap(self, other_agent):
                    self.trim_agent_elements(other_agent, layer)
