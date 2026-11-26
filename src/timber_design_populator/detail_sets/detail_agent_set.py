from __future__ import annotations

from compas.data import Data
from timber_design_arch.elements import LayerRole


class DetailAgentSet(Data):
    """Base class of detail sets: coordinate several agents that together build one feature.

    A feature (:class:`~timber_design_arch.panel_features.PanelFeature`) states design intent: where an
    opening is, which side a niche is on.  A detail set decides how that is built: it reads
    the feature and the panel's layers, derives what each agent needs (frames, outlines, depths,
    shared widths), and :meth:`expand`\\ s into ordinary bound agents, e.g. a
    :class:`~timber_design_populator.VoidFramingDetailAgent` and a
    :class:`~timber_design_populator.LayerCutDetailAgent`.  This is where a detail's
    coordination lives, so a custom detail can, say, cut one layer beyond the feature's outline.

    A set is one way to build a feature, not the only one.  A feature is built by exactly one
    set: its own ``detail_set``, or else the populator's default for its type.  A new base
    behaviour is a new detail agent; a new combination of agents is a new detail set.

    The populator expands the set on every run, once the panel's layers are in populator
    space, and the agents it returns are then populated like any other.

    Subclasses implement :meth:`expand`, take their parameters as constructor arguments and
    return them from :attr:`__data__`, so a set can be cloned and serialized.  Each built-in set
    lives in its own module of :mod:`timber_design_populator.detail_sets`.

    Attributes
    ----------
    FEATURE_TYPES : tuple[type, ...]
        The feature classes this set builds.
    """

    FEATURE_TYPES = ()

    def __init__(self):
        # explicit, so a set without parameters of its own offers none (CT: Detail Agent Set reads this signature)
        super().__init__()

    @property
    def __data__(self):
        return {}

    def __repr__(self):
        return "{}()".format(type(self).__name__)

    def clone(self):
        """A fresh set with the same parameters."""
        return type(self)(**self.__data__)

    def expand(self, feature, panel, layer_tree, standard_beam_width=None):
        """The agents that build *feature*, bound to it, with their layers set.

        Parameters
        ----------
        feature : :class:`~timber_design_arch.panel_features.PanelFeature`
            One of :attr:`FEATURE_TYPES`.
        panel : :class:`~timber_design_arch.elements.Panel`
            The panel being populated.
        layer_tree : dict[tuple, :class:`~timber_design_arch.elements.Layer`]
            The panel's layers in populator space, by layer path.
        standard_beam_width : float, optional
            The populator's default beam width, for coordination that depends on widths.

        Returns
        -------
        tuple[list[:class:`~timber_design_populator.PopulatorAgent`], list[:class:`~compas_timber.errors.FeatureApplicationError`]]
            The agents, in the order they should run, and problems to report.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # helpers for subclasses
    # ------------------------------------------------------------------

    @staticmethod
    def root_layer(layer_tree, role):
        """The root layer with *role*, or ``None``."""
        role = LayerRole(role)
        return next((layer for path, layer in layer_tree.items() if path is not None and len(path) == 1 and layer.role == role), None)

    @staticmethod
    def layer_and_sublayers(layer_tree, layer):
        """*layer* and every layer below it, ordered by path.  Layers without a path are skipped."""
        if layer is None or layer.layer_path is None:
            return []
        path = layer.layer_path
        below = [(sub_path, sub) for sub_path, sub in layer_tree.items() if sub_path is not None and sub_path[: len(path)] == path]
        return [sub for _, sub in sorted(below, key=lambda item: item[0])]

    @staticmethod
    def resolved_width(width, standard_beam_width):
        """*width*, or the populator's standard width when unset."""
        return width if width is not None else standard_beam_width
