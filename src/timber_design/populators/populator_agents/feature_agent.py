from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING
from typing import Optional

from compas_timber.elements import Layer

from .populator_agent import PopulatorAgent

if TYPE_CHECKING:
    from compas_timber.panel_features import PanelFeature  # noqa: F401


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
    internal_joint_overrides, external_joint_overrides, composite_joint_overrides : list, optional
        Per-agent joint-rule overrides, see :class:`PopulatorAgent`.

    Attributes
    ----------
    feature : :class:`~compas_timber.panel_features.PanelFeature`
        The feature driving element placement.
    element_layer_paths : list[str]
        Paths of the framing layers, resolved to live layers by
        :meth:`repoint_to_layer_tree`.
    trimming_layer_paths : list[str]
        Paths of the trimming layers, resolved to live layers by
        :meth:`repoint_to_layer_tree`.
    """

    FEATURE_TYPE = None

    def __init__(
        self,
        feature: PanelFeature,
        element_layers: Optional[list] = None,
        trimming_layers: Optional[list] = None,
        internal_joint_overrides: Optional[list] = None,
        external_joint_overrides: Optional[list] = None,
        composite_joint_overrides: Optional[list] = None,
    ) -> None:
        super().__init__(internal_joint_overrides, external_joint_overrides, composite_joint_overrides)
        self.feature = feature
        self.element_layer_paths = [el.layer_path if isinstance(el, Layer) else el for el in element_layers or []]
        self.trimming_layer_paths = [tl.layer_path if isinstance(tl, Layer) else tl for tl in trimming_layers or []]
        self._element_layers = []
        self._trimming_layers = []

    @property
    def element_layers(self) -> list[Layer]:
        """The layers this agent generates elements on."""
        return self._element_layers

    @property
    def trimming_layers(self) -> list[Layer]:
        """The layers on which this agent's outline trims peer elements."""
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
        """Generate, tag and return this agent's elements on every framing layer.

        Returns
        -------
        dict[:class:`~compas_timber.elements.Layer`, list[:class:`~timber_design.populators.Beam2D` | :class:`~compas_timber.elements.Plate`]]
        """
        self.outline_by_layer.clear()
        elements_by_layer = {}
        for layer in self.element_layers:
            layer_elements, layer_outline = self.generate_elements_for_layer(layer)
            for element in layer_elements:
                element.attributes["agent"] = self
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
