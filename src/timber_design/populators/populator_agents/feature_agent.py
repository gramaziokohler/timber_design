from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from typing import Optional

from timber_design.populators import aabb_overlap
from .populator_agent import PopulatorAgent
from .populator_agent import PopulatorAgentConfig


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
    framing_layer_defs : list[:class:`~timber_design.populators.LayerDefinition`], optional
        The layers on which this feature agent generates framing elements.
        Pass the same :class:`LayerDefinition` objects given to
        :class:`~timber_design.populators.PanelPopulatorConfig` as
        ``layer_defs``; the config resolves them to :class:`Layer` objects.
        When ``None`` the agent falls back to populating every layer whose
        :attr:`~timber_design.populators.Layer.is_framing_layer` flag is
        ``True``.
    trimming_layer_defs : list[:class:`~timber_design.populators.LayerDefinition`], optional
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
        # LayerDefinition objects are resolved at runtime; not round-tripped here.
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
            raise ValueError(
                "{} has no feature set. Pass it to the constructor or call "
                "get_agent_from_feature(feature) instead.".format(type(self).__name__)
            )
        return self.get_agent_from_feature(self.feature)

    def get_agent_from_feature(self, feature, framing_layers=None, trimming_layers=None):
        """Instantiate a feature-based agent.

        A :class:`FeatureAgent` is not bound to a single layer at construction
        time — layers are discovered from the ``layers`` argument of
        :meth:`FeatureAgent.generate_elements`.  The agent is therefore
        created with ``layer=None``.

        Parameters
        ----------
        feature : :class:`~compas_timber.panel_features.PanelFeature`
            The (possibly transformed) feature instance.
        framing_layers : list[:class:`~timber_design.populators.Layer`], optional
            Resolved :class:`Layer` objects for element generation.  Supplied
            by :meth:`~PanelPopulatorConfig.create_feature_agents` after it
            maps :attr:`framing_layer_defs` to ``Layer`` instances.
        trimming_layers : list[:class:`~timber_design.populators.Layer`], optional
            Resolved :class:`Layer` objects for cross-layer plate trimming.

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
        return self.AGENT_TYPE(None, self, feature, framing_layers, trimming_layers)


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
    params : :class:`FeatureAgentConfig`
        Configuration for this agent.
    feature : :class:`~compas_timber.panel_features.PanelFeature`
        The (possibly transformed) feature instance driving element placement.
    framing_layers : list[:class:`~timber_design.populators.Layer`], optional
        Explicit framing layers; overrides ``is_framing_layer`` fallback.
    trimming_layers : list[:class:`~timber_design.populators.Layer`], optional
        Explicit trimming layers; restricts cross-layer plate cutting.
    """

    FEATURE_TYPE = None

    def __init__(self, params, feature, framing_layers=None, trimming_layers=None):
        # type: (FeatureAgentConfig, object, list, list) -> None
        super().__init__(params)
        self.feature = feature
        self.framing_layers = framing_layers or []
        self.trimming_layers = trimming_layers or []
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
            layer_elements = self.generate_elements_for_layer(layer)
            self._elements_by_layer[layer.layer_index] = layer_elements # add to per-layer dict
            self.elements.extend(layer_elements) # add to general elements list
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
