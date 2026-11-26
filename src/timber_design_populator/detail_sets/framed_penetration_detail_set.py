from __future__ import annotations

from typing import Optional

from timber_design_arch.elements import LayerRole
from timber_design_arch.panel_features import MEPPenetration
from compas_timber.errors import FeatureApplicationError

from timber_design_populator.populator_agents.layer_cut_detail_agent import LayerCutDetailAgent
from timber_design_populator.populator_agents.void_framing_detail_agent import VoidFramingDetailAgent
from timber_design_populator.populator_agents.void_geometry import frame_on_layer_faces
from timber_design_populator.populator_agents.void_geometry import project_to_layer_midplane

from .detail_agent_set import DetailAgentSet


class FramedPenetrationDetailSet(DetailAgentSet):
    """One way to build a service penetration: a framed surround in the core, and each layer cut by its own outline.

    Expands into:

    - a :class:`~timber_design_populator.VoidFramingDetailAgent` on the core, framed around
      the core outline like a window (header, sill, king studs; jack studs with *lintel_posts*);
    - a :class:`~timber_design_populator.LayerCutDetailAgent` on each of the exterior, core and
      interior layers (sublayers included), cutting it through by the penetration's outline for that
      layer.

    Parameters
    ----------
    lintel_posts : bool, optional
        Jack studs under the header.
    header_width, sill_width, king_stud_width, jack_stud_width : float, optional
        Beam widths; unset ones use the populator's ``standard_beam_width``.
    """

    FEATURE_TYPES = (MEPPenetration,)
    CUT_ROLES = (LayerRole.EXTERIOR, LayerRole.CORE, LayerRole.INTERIOR)

    def __init__(
        self,
        lintel_posts: bool = False,
        header_width: Optional[float] = None,
        sill_width: Optional[float] = None,
        king_stud_width: Optional[float] = None,
        jack_stud_width: Optional[float] = None,
    ):
        super().__init__()
        self.lintel_posts = lintel_posts
        self.header_width = header_width
        self.sill_width = sill_width
        self.king_stud_width = king_stud_width
        self.jack_stud_width = jack_stud_width

    @property
    def __data__(self):
        return {
            "lintel_posts": self.lintel_posts,
            "header_width": self.header_width,
            "sill_width": self.sill_width,
            "king_stud_width": self.king_stud_width,
            "jack_stud_width": self.jack_stud_width,
        }

    def expand(self, feature, panel, layer_tree, standard_beam_width=None):
        core = self.root_layer(layer_tree, LayerRole.CORE)
        if core is None:
            return [], [FeatureApplicationError(None, None, "{}: the panel has no core layer to frame the penetration in.".format(type(self).__name__))]
        frame_a, frame_b = frame_on_layer_faces(feature.outline_core, core)
        framing = VoidFramingDetailAgent(
            frame_outline_a=frame_a,
            frame_outline_b=frame_b,
            boundary=project_to_layer_midplane(feature.outline_core, core),
            sill=True,
            lintel_posts=self.lintel_posts,
            header_width=self.header_width,
            sill_width=self.sill_width,
            king_stud_width=self.king_stud_width,
            jack_stud_width=self.jack_stud_width,
            feature=feature,
            element_layers=[core.layer_path],
            trimming_layers=[core.layer_path],
        )

        cutting = [
            LayerCutDetailAgent(
                root.layer_path,
                outline_a=self.outline_for_role(feature, role),
                cut_beams=root is not core,  # the framing already bounds the core
                feature=feature,
            )
            for role, root in ((role, self.root_layer(layer_tree, role)) for role in self.CUT_ROLES)
            if root is not None
        ]
        return [framing] + cutting, []

    @staticmethod
    def outline_for_role(feature, role):
        """The penetration's outline for the layers with *role*."""
        return {LayerRole.EXTERIOR: feature.outline_exterior, LayerRole.CORE: feature.outline_core, LayerRole.INTERIOR: feature.outline_interior}[LayerRole(role)]
