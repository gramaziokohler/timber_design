from __future__ import annotations

from timber_design_arch.elements import LayerRole
from timber_design_arch.panel_features import MEPPenetration
from timber_design_arch.panel_features import Opening

from timber_design_populator.populator_agents.layer_cut_detail_agent import LayerCutDetailAgent

from .detail_agent_set import DetailAgentSet
from .framed_penetration_detail_set import FramedPenetrationDetailSet


class CutThroughDetailSet(DetailAgentSet):
    """One way to build an opening or penetration in a solid panel: cut it through every layer, with no framing.

    For solid timber (e.g. a cross-laminated timber core), where the core plate carries
    itself around the opening.  Expands into a
    :class:`~timber_design_populator.LayerCutDetailAgent` on each of the exterior, core and
    interior layers (sublayers included), which cuts the plates and cuts back the beams
    (battens, studs of an installation layer) in them.

    An opening is cut with its own two face outlines in every layer; a penetration with its
    outline for that layer's role.
    """

    FEATURE_TYPES = (Opening, MEPPenetration)
    CUT_ROLES = (LayerRole.EXTERIOR, LayerRole.CORE, LayerRole.INTERIOR)

    def expand(self, feature, panel, layer_tree, standard_beam_width=None):
        agents = []
        for role in self.CUT_ROLES:
            root = self.root_layer(layer_tree, role)
            if root is None:
                continue
            if isinstance(feature, MEPPenetration):
                outline_a, outline_b = FramedPenetrationDetailSet.outline_for_role(feature, role), None
            else:
                outline_a, outline_b = feature.outline_a, feature.outline_b
            agents.append(LayerCutDetailAgent(root.layer_path, outline_a=outline_a, outline_b=outline_b, cut_beams=True, feature=feature))
        return agents, []
