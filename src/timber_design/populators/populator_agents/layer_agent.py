from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from typing import TYPE_CHECKING
from typing import Optional

from compas_timber.elements import Layer

from .populator_agent import PopulatorAgent

if TYPE_CHECKING:
    from compas.geometry import Line  # noqa: F401

    from timber_design.connections_2d.beam2d import Beam2D  # noqa: F401


class LayerAgent(PopulatorAgent, ABC):
    """Abstract base class for agents bound to a single layer.

    A ``LayerAgent`` frames exactly one layer of the panel cross-section
    (edge beams, studs, plates).  It records the layer by its ``layer_path``
    so the agent survives panel re-solves; :meth:`repoint_to_layer_tree`
    rebinds the path to the live :class:`~compas_timber.elements.Layer` before
    each generation pass.

    Subclasses implement :meth:`generate_layer_elements`, which produces the
    elements and boundary outline for :attr:`layer`.

    Parameters
    ----------
    layer : :class:`~compas_timber.elements.Layer` or str, optional
        The layer this agent operates within, or its layer path.
    internal_joint_overrides, external_joint_overrides : list, optional
        Per-agent joint-rule overrides, see :class:`PopulatorAgent`.

    Attributes
    ----------
    layer : :class:`~compas_timber.elements.Layer` or None
        The live layer this agent is bound to; ``None`` until
        :meth:`repoint_to_layer_tree` is called.
    layer_path : str or None
        Path of :attr:`layer` in the panel's layer tree.
    """

    def __init__(self, layer=None, internal_joint_overrides=None, external_joint_overrides=None):
        # type: (Optional[Layer | str], Optional[list], Optional[list]) -> None
        super().__init__(internal_joint_overrides, external_joint_overrides)
        self._layer = None
        if isinstance(layer, Layer):
            self.layer_path = layer.layer_path
        else:
            self.layer_path = layer

    @property
    def layer(self):
        return self._layer

    def repoint_to_layer_tree(self, tree):
        """Rebind this agent's layer reference to the current panel's layer tree by path.

        If no path was recorded at construction (layer had no layer_path yet),
        the existing direct reference is left unchanged.
        """
        if self.layer_path is not None:
            self._layer = tree.get(self.layer_path)

    @property
    def __data__(self):
        data = super().__data__
        data["layer"] = self.layer_path
        return data

    @property
    def layer_center_height(self):
        """Z coordinate of the centre of this agent's layer (populator space)."""
        return self.layer.center_height if self.layer is not None else None

    @property
    def element_layers(self):
        return [self.layer]

    @property
    def trimming_layers(self):
        return [self.layer]

    def generate_elements(self):
        self.outline_by_layer.clear()
        elements, outline = self.generate_layer_elements()
        self.outline_by_layer[self.layer] = outline
        return {self.layer: elements}

    @abstractmethod
    def generate_layer_elements(self):
        """Generate the elements and boundary outline for :attr:`layer`.

        Returns
        -------
        tuple[list[:class:`~timber_design.populators.Beam2D` | :class:`~compas_timber.elements.Plate`], :class:`~compas.geometry.Polyline` or None]
            The elements and the agent's boundary outline on :attr:`layer`.
        """
        raise NotImplementedError

    def compute_outline_for_layer(self, layer):
        """A layer agent's own outline serves every layer it trims.

        Sublayers of :attr:`layer` (e.g. subdivision layers) share the parent
        layer's boundary, so the outline recorded during
        :meth:`generate_elements` applies to them as well.
        """
        return self.outline_by_layer.get(self.layer)

    def beam_from_category(self, centerline, category, layer=None, **kwargs):
        """Create a beam, defaulting *layer* to ``self.layer``."""
        return super().beam_from_category(centerline, category, layer=self.layer, **kwargs)
