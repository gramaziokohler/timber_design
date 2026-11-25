from __future__ import annotations

from typing import Optional

from compas_arch.elements import LayerRole
from compas_arch.panel_features import Niche
from compas_timber.errors import FeatureApplicationError

from timber_design_populator.populator_agents.layer_cut_detail_agent import LayerCutDetailAgent
from timber_design_populator.populator_agents.void_framing_detail_agent import VoidFramingDetailAgent
from timber_design_populator.populator_agents.void_geometry import frame_boundary
from timber_design_populator.populator_agents.void_geometry import frame_on_layer_faces

from .detail_agent_set import DetailAgentSet


class FramedNicheDetailSet(DetailAgentSet):
    """One way to build a one-sided niche: a framed surround in the core, and the niche cut into its side layer.

    Expands into:

    - a :class:`~timber_design_populator.VoidFramingDetailAgent` on the core, framed around
      the niche outline like a window (header, sill, king studs; jack studs with
      *lintel_posts*).  When the niche goes through the framing (no ``depth``), studs inside
      the frame are removed too;
    - a :class:`~timber_design_populator.LayerCutDetailAgent` on the niche's side layer
      (sublayers included): with a ``depth``, a blind pocket of that depth into the plate on
      the panel face; without one, every plate of the side layer is cut through.  Beams on the
      side layer (e.g. battens) are cut back to the niche outline either way.  The opposite
      side layer is left as the back of the niche.

    Parameters
    ----------
    lintel_posts : bool, optional
        Jack studs under the header.
    header_width, sill_width, king_stud_width, jack_stud_width : float, optional
        Beam widths; unset ones use the populator's ``standard_beam_width``.
    """

    FEATURE_TYPES = (Niche,)

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
            return [], [FeatureApplicationError(None, None, "{}: the panel has no core layer to frame the niche in.".format(type(self).__name__))]
        through = feature.depth is None
        frame_a, frame_b = frame_on_layer_faces(feature.outline, core)
        framing = VoidFramingDetailAgent(
            frame_outline_a=frame_a,
            frame_outline_b=frame_b,
            boundary=frame_boundary(frame_a, frame_b, core.center_height) if through else None,
            sill=True,
            lintel_posts=self.lintel_posts,
            header_width=self.header_width,
            sill_width=self.sill_width,
            king_stud_width=self.king_stud_width,
            jack_stud_width=self.jack_stud_width,
            feature=feature,
            element_layers=[core.layer_path],
            trimming_layers=[core.layer_path] if through else [],
        )

        side = self.root_layer(layer_tree, feature.side)
        if side is None:
            return [framing], []
        cutting = LayerCutDetailAgent(side.layer_path, outline_a=feature.outline, depth=feature.depth, feature=feature)
        return [framing, cutting], []
