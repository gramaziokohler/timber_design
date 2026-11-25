from __future__ import annotations

from typing import Optional

from compas.geometry import Vector
from compas_arch.elements import LayerRole
from compas_arch.panel_features import PanelConnectionInterface
from compas_timber.errors import FeatureApplicationError

from timber_design_populator.populator_agents.backing_stud_detail_agent import BackingStudDetailAgent
from timber_design_populator.populator_agents.layer_extension_detail_agent import LayerExtensionDetailAgent

from .detail_agent_set import DetailAgentSet


class PanelJointDetailSet(DetailAgentSet):
    """Base class of the detail sets panel joints create: one panel's half of a connection detail.

    A panel joint that builds a connection detail does the cross-panel calculation once, with
    both panels in view, and puts each panel's half on that panel's
    :class:`~compas_arch.panel_features.PanelConnectionInterface` as one of these sets.  Its
    inputs are already in that panel's local frame (populator space), so expanding it needs
    nothing from the other panel.

    It expands into a :class:`~timber_design_populator.LayerExtensionDetailAgent` when there
    are layer extensions (or problems to report), and a
    :class:`~timber_design_populator.BackingStudDetailAgent` on the core when there are backing
    stud positions.  Subclasses pair with a joint class and say which inputs it fills.

    Parameters
    ----------
    edge_index : int, optional
        The panel edge the joint is on (``None`` on the face side of a T).
    extensions : list[dict], optional
        ``{"layer_path": tuple, "plane": Plane}`` per layer to extend at *edge_index*.
    backing_positions : list[:class:`~compas.geometry.Point`], optional
        A point on each backing stud line, at the core's mid-height.
    backing_direction : :class:`~compas.geometry.Vector`, optional
        The direction of the backing studs.
    backing_stud_width : float, optional
        Unset: the populator's ``standard_beam_width``.
    messages : list[str], optional
        Problems the joint found (e.g. missing layers), reported as feature errors.
    """

    FEATURE_TYPES = (PanelConnectionInterface,)

    def __init__(
        self,
        edge_index: Optional[int] = None,
        extensions: Optional[list] = None,
        backing_positions: Optional[list] = None,
        backing_direction: Optional[Vector] = None,
        backing_stud_width: Optional[float] = None,
        messages: Optional[list] = None,
    ):
        super().__init__()
        self.edge_index = edge_index
        self.extensions = [{"layer_path": tuple(e["layer_path"]), "plane": e["plane"]} for e in extensions or []]
        self.backing_positions = list(backing_positions) if backing_positions else []
        self.backing_direction = backing_direction
        self.backing_stud_width = backing_stud_width
        self.messages = list(messages) if messages else []

    @property
    def __data__(self):
        return {
            "edge_index": self.edge_index,
            "extensions": [{"layer_path": list(e["layer_path"]), "plane": e["plane"]} for e in self.extensions],
            "backing_positions": self.backing_positions,
            "backing_direction": self.backing_direction,
            "backing_stud_width": self.backing_stud_width,
            "messages": self.messages or None,
        }

    def expand(self, feature, panel, layer_tree, standard_beam_width=None):
        agents = []
        errors = []
        if self.extensions or self.messages:
            agents.append(LayerExtensionDetailAgent(edge_index=self.edge_index, extensions=self.extensions, messages=self.messages, feature=feature))
        if self.backing_positions:
            core = self.root_layer(layer_tree, LayerRole.CORE)
            if core is None:
                errors.append(FeatureApplicationError(None, None, "{}: the panel has no core layer for the backing studs.".format(type(self).__name__)))
            else:
                agents.append(
                    BackingStudDetailAgent(
                        positions=self.backing_positions,
                        direction=self.backing_direction,
                        width=self.backing_stud_width,
                        feature=feature,
                        element_layers=[core.layer_path],
                        trimming_layers=[core.layer_path],
                    )
                )
        return agents, errors
