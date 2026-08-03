from __future__ import annotations

from abc import abstractmethod
from typing import Optional

from compas_timber.elements import Layer

from .populator_agent import PopulatorAgent


class FeatureAgent(PopulatorAgent):
    """Abstract base class for feature-driven populator agents.

    Extends :class:`PopulatorAgent` by accepting a
    :class:`~compas_timber.panel_features.PanelFeature` and storing it as
    :attr:`feature`.  Subclasses handle specific feature types (e.g.
    :class:`~timber_design.populators.OpeningPopulatorAgent` for
    :class:`~compas_timber.panel_features.Opening`).

    Unlike a :class:`~timber_design.populators.LayerAgent`, a feature agent can
    act on several layers.  Which layers receive generated elements (*framing*)
    and which only have peer elements trimmed (*trimming*) is controlled by two
    explicit path lists recorded at construction and rebound to live layers by
    :meth:`repoint_to_layer_tree`:

    - :attr:`element_layers` — the layers passed to
      :meth:`generate_elements_for_layer`.
    - :attr:`trimming_layers` — additional layers on which the agent's outline
      trims peer elements (e.g. sheathing plates it must cut through).

    Parameters
    ----------
    feature : :class:`~compas_timber.panel_features.PanelFeature`
        The (possibly transformed) feature instance driving element placement.
    element_layers : list[:class:`~compas_timber.elements.Layer` | str], optional
        Explicit framing layers (or their paths).
    trimming_layers : list[:class:`~compas_timber.elements.Layer` | str], optional
        Explicit trimming layers (or their paths).
    internal_joint_overrides, external_joint_overrides : list, optional
        Per-agent joint-rule overrides, see :class:`PopulatorAgent`.
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
        self.outline_by_layer.clear()
        elements_by_layer = {}
        for layer in self.element_layers:
            layer_elements, layer_outline = self.generate_elements_for_layer(layer)
            elements_by_layer[layer] = layer_elements
            self.outline_by_layer[layer] = layer_outline
        return elements_by_layer

    @abstractmethod
    def generate_elements_for_layer(self, layer):
        """Generate the elements and boundary outline for one framing *layer*.

        Returns
        -------
        tuple[list[:class:`~timber_design.populators.Beam2D` | :class:`~compas_timber.elements.Plate`], :class:`~compas.geometry.Polyline` or None]
            The elements and the agent's boundary outline on *layer*.
        """
        raise NotImplementedError
