from __future__ import annotations

from typing import Optional

from compas_timber.errors import FeatureApplicationError

from timber_design_populator.populator_agents.populator_agent import PopulatorAgent


class LayerExtensionDetailAgent(PopulatorAgent):
    """Moves one edge of some of the panel's layers onto given planes, before any element is generated.

    Creates no elements.  In :meth:`modify_layers` it sets each layer's extension plane at
    :attr:`edge_index`; the populator applies all extension planes afterwards.  A panel joint
    computes the planes (e.g. a layer stagger at a corner), so this agent needs no knowledge of
    the other panel.

    Parameters
    ----------
    edge_index : int
        The panel edge the layers are extended at.
    extensions : list[dict], optional
        ``{"layer_path": tuple, "plane": Plane}`` per layer, planes in populator space.
    messages : list[str], optional
        Problems found while computing the extensions (e.g. a missing layer), reported as
        feature errors when the agent runs.
    element_layers, trimming_layers, feature, priority, internal_joint_overrides, external_joint_overrides, composite_joint_overrides : optional
        See :class:`~timber_design_populator.PopulatorAgent`.
    """

    NAME = "LayerExtensionDetailAgent"
    IS_DETAIL = True
    PRIORITY = -100  # layer geometry first, so every other agent works on the extended layers

    def __init__(self, edge_index: Optional[int] = None, extensions: Optional[list] = None, messages: Optional[list] = None, **kwargs):
        super().__init__(**kwargs)
        self.edge_index = edge_index
        self.extensions = [{"layer_path": tuple(e["layer_path"]), "plane": e["plane"]} for e in extensions or []]
        self.messages = list(messages) if messages else []

    @property
    def __data__(self):
        data = super().__data__
        data["edge_index"] = self.edge_index
        data["extensions"] = [{"layer_path": list(e["layer_path"]), "plane": e["plane"]} for e in self.extensions]
        data["messages"] = self.messages or None
        return data

    def modify_layers(self, layer_tree):
        errors = [self._error(message) for message in self.messages]
        for extension in self.extensions:
            layer = layer_tree.get(extension["layer_path"])
            if layer is None:
                errors.append(self._error("the panel has no layer {}.".format(extension["layer_path"])))
                continue
            layer.set_extension_plane(self.edge_index, extension["plane"])
        return errors

    def _error(self, message):
        geometry = getattr(self.feature, "polyline", None) if self.feature is not None else None
        return FeatureApplicationError(geometry, None, "{}: {}".format(type(self).__name__, message))
