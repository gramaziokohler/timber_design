from __future__ import annotations

from compas_arch.elements import LayerRole
from compas_arch.panel_features import LinearService
from compas_timber.errors import FeatureApplicationError

from timber_design_populator.populator_agents.service_drilling_detail_agent import ServiceDrillingDetailAgent
from timber_design_populator.populator_agents.service_geometry import interior_direction
from timber_design_populator.populator_agents.service_notch_detail_agent import ServiceNotchDetailAgent

from .detail_agent_set import DetailAgentSet

DRILLING = "drilling"
NOTCHING = "notching"


class LinearServiceDetailSet(DetailAgentSet):
    """One way to build a manually routed service: drill or notch the core's beams it runs through.

    Expands into a :class:`~timber_design_populator.ServiceDrillingDetailAgent` (``mode="drilling"``:
    a hole along the path) or a :class:`~timber_design_populator.ServiceNotchDetailAgent`
    (``mode="notching"``: a notch from the interior face), on the core.  Sheathing is not cut.

    Parameters
    ----------
    mode : str, optional
        ``"drilling"`` (default) or ``"notching"``.
    """

    FEATURE_TYPES = (LinearService,)
    MODES = (DRILLING, NOTCHING)

    def __init__(self, mode: str = DRILLING):
        super().__init__()
        mode = str(mode).strip().lower()
        if mode not in self.MODES:
            raise ValueError("LinearServiceDetailSet mode must be one of: {}.".format(", ".join(self.MODES)))
        self.mode = mode

    @property
    def __data__(self):
        return {"mode": self.mode}

    def expand(self, feature, panel, layer_tree, standard_beam_width=None):
        core = self.root_layer(layer_tree, LayerRole.CORE)
        if core is None:
            return [], [FeatureApplicationError(None, None, "{}: the panel has no core layer to machine.".format(type(self).__name__))]
        common = dict(path=feature.polyline, diameter=feature.thickness, feature=feature, trimming_layers=[core.layer_path])
        if self.mode == NOTCHING:
            return [ServiceNotchDetailAgent(side=interior_direction(layer_tree), **common)], []
        return [ServiceDrillingDetailAgent(**common)], []
