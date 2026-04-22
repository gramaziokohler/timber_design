from abc import abstractmethod
from dataclasses import dataclass

from .layer_agent import LayerAgent
from .layer_agent import LayerAgentConfig


@dataclass
class FeatureAgentConfig(LayerAgentConfig):
    """Config base class for feature-based populator agents.

    Extends :class:`LayerAgentConfig` with :meth:`get_agent_from_feature`,
    which passes a :class:`~compas_timber.panel_features.PanelFeature` to the
    agent constructor as its third positional argument.

    All concrete feature-agent config classes (e.g.
    :class:`~timber_design.populators.OpeningPopulatorAgentConfig`) should
    extend this class.
    """

    def get_agent_from_feature(self, feature):
        """Instantiate a feature-based agent.

        A :class:`FeatureAgent` is not bound to a single layer at construction
        time — it discovers the layers it operates on from the ``layers``
        argument of :meth:`FeatureAgent.generate_elements`.  The agent is
        therefore created with ``layer=None``.

        Parameters
        ----------
        feature : :class:`~compas_timber.panel_features.PanelFeature`
            The (possibly transformed) feature instance.

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
        return self.AGENT_TYPE(None, self, feature)


class FeatureAgent(LayerAgent):
    """Abstract base class for feature-driven populator agents.

    Extends :class:`LayerAgent` by accepting a
    :class:`~compas_timber.panel_features.PanelFeature` and storing it as
    :attr:`feature`.  Subclasses handle specific feature types (e.g.
    :class:`~timber_design.populators.OpeningPopulatorAgent` for
    :class:`~compas_timber.panel_features.Opening`).

    A :class:`FeatureAgent` differs from a plain :class:`LayerAgent` in two
    important ways:

    1. A single agent instance may act on *multiple* layers.  Its
       :meth:`generate_elements` receives the full layer list and is responsible
       for selecting which layers to operate on.
    2. During generation the agent registers itself on each affected layer via
       :meth:`register_on_layer`, so peer :class:`LayerAgent` instances
       encounter it naturally during the within-layer trim and join passes.

    Element tracking
    ----------------
    Elements are stored in two complementary structures:

    - ``self.elements`` — flat list of **all** elements across all layers.
      Used by properties like :attr:`~OpeningPopulatorAgent.header` that
      search elements by category.
    - ``self._elements_by_layer`` — ``{layer_index: [elements]}`` dict.
      Used by :meth:`elements_for_layer` / :meth:`set_elements_for_layer`
      so that per-layer passes (trim, joints) see only the right subset.

    Both structures are kept in sync: :meth:`generate_elements` populates
    both, and :meth:`set_elements_for_layer` rebuilds ``self.elements`` from
    ``_elements_by_layer`` whenever a layer's list is replaced (e.g. after
    trimming).

    Parameters
    ----------
    layer : :class:`~timber_design.populators.Layer` or None
        Ignored; kept for :class:`LayerAgent` compatibility.  Callers pass
        ``None`` and layers are discovered via ``generate_elements(layers)``.
    params : :class:`FeatureAgentConfig`
        Configuration for this agent.
    feature : :class:`~compas_timber.panel_features.PanelFeature`
        The (possibly transformed) feature instance driving element placement.
    """

    FEATURE_TYPE = None

    def __init__(self, layer, params, feature):
        # type: (Layer, FeatureAgentConfig, object) -> None
        super().__init__(layer, params)
        self.feature = feature
        # Per-layer element tracking.  Populated during generate_elements.
        self._elements_by_layer = {}
        # Layers this agent has registered itself on during generate_elements.
        self.registered_layers = []

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

    def generate_elements(self, layers):
        """Generate elements across all relevant layers.

        For each layer, calls :meth:`generate_elements_for_layer`, stores the
        returned elements in both ``_elements_by_layer`` and ``self.elements``,
        then registers this agent on the layer so subsequent passes treat it as
        a peer.

        Parameters
        ----------
        layers : list[:class:`~timber_design.populators.Layer`]
            All layers in the populator.
        """
        for layer in layers:
            layer_elements = self.generate_elements_for_layer(layer)
            self._elements_by_layer[layer.layer_index] = layer_elements
            self.elements.extend(layer_elements)
            self.register_on_layer(layer)

    @abstractmethod
    def generate_elements_for_layer(self, layer):
        """Generate and return elements for a single *layer*.

        Subclasses decide which layers to act on (typically framing layers)
        and return an empty list for layers they skip.

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

    def trim_other_layers(self, layers):
        """Apply :meth:`trim_cross_layer` to agents on layers this agent did not register on.

        Overrides :meth:`LayerAgent.trim_other_layers` to skip registered
        layers (where within-layer trimming already handled peer interaction)
        rather than skipping a single ``self.layer``.

        Parameters
        ----------
        layers : list[:class:`~timber_design.populators.Layer`]
            All layers in the populator.
        """
        for layer in layers:
            if layer in self.registered_layers:
                continue
            for other_agent in layer.agents:
                if other_agent is self:
                    continue
                self.trim_cross_layer(other_agent)
