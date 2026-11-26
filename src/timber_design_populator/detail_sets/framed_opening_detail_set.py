from __future__ import annotations

from typing import Optional

from compas.geometry import Polyline
from compas.geometry import offset_polygon
from timber_design_arch.elements import LayerRole
from timber_design_arch.panel_features import Opening
from timber_design_arch.panel_features import OpeningType
from compas_timber.errors import FeatureApplicationError

from timber_design_populator.populator_agents.layer_cut_detail_agent import LayerCutDetailAgent
from timber_design_populator.populator_agents.void_framing_detail_agent import VoidFramingDetailAgent
from timber_design_populator.populator_agents.void_geometry import frame_boundary
from timber_design_populator.populator_agents.void_geometry import frame_through_outlines

from .detail_agent_set import DetailAgentSet

DOOR_BOTTOM_OFFSET = 100.0  # keeps a door's frame (it has no sill) clear of the bottom plate


class FramedOpeningDetailSet(DetailAgentSet):
    """One way to build a window or door: a framed surround in the core, and the opening cut through every layer.

    Expands into:

    - a :class:`~timber_design_populator.VoidFramingDetailAgent` on the core: header, king
      studs (and jack studs with *lintel_posts*), a sill for windows; studs inside the frame
      are removed;
    - a :class:`~timber_design_populator.LayerCutDetailAgent` on each of the exterior, core and
      interior layers (sublayers included): the opening is cut out of every plate, and beams
      on the other layers (e.g. battens) are cut back to the frame.

    Parameters
    ----------
    lintel_posts : bool, optional
        Jack studs under the header.
    split_bottom_plate_beam : bool, optional
        Doors only: split the bottom plate at the opening.
    header_width, sill_width, king_stud_width, jack_stud_width : float, optional
        Beam widths; unset ones use the populator's ``standard_beam_width``.
    cut_offsets : dict[str, float], optional
        Per layer role (``"exterior"``, ``"core"``, ``"interior"``), how far the cut in that
        layer reaches beyond the opening outline, e.g. ``{"exterior": 20}`` to cut the
        cladding 20 larger than the opening.  The framing is not affected.
    """

    FEATURE_TYPES = (Opening,)
    CUT_ROLES = (LayerRole.EXTERIOR, LayerRole.CORE, LayerRole.INTERIOR)

    def __init__(
        self,
        lintel_posts: bool = False,
        split_bottom_plate_beam: bool = False,
        header_width: Optional[float] = None,
        sill_width: Optional[float] = None,
        king_stud_width: Optional[float] = None,
        jack_stud_width: Optional[float] = None,
        cut_offsets: Optional[dict] = None,
    ):
        super().__init__()
        self.lintel_posts = lintel_posts
        self.split_bottom_plate_beam = split_bottom_plate_beam
        self.header_width = header_width
        self.sill_width = sill_width
        self.king_stud_width = king_stud_width
        self.jack_stud_width = jack_stud_width
        self.cut_offsets = {LayerRole(role).value: distance for role, distance in (cut_offsets or {}).items()}

    @property
    def __data__(self):
        return {
            "lintel_posts": self.lintel_posts,
            "split_bottom_plate_beam": self.split_bottom_plate_beam,
            "header_width": self.header_width,
            "sill_width": self.sill_width,
            "king_stud_width": self.king_stud_width,
            "jack_stud_width": self.jack_stud_width,
            "cut_offsets": dict(self.cut_offsets) or None,
        }

    def expand(self, feature, panel, layer_tree, standard_beam_width=None):
        core = self.root_layer(layer_tree, LayerRole.CORE)
        if core is None:
            return [], [FeatureApplicationError(None, None, "{}: the panel has no core layer to frame the opening in.".format(type(self).__name__))]
        door = feature.opening_type == OpeningType.DOOR
        bottom_offset = DOOR_BOTTOM_OFFSET if door else 0.0

        frame_a, frame_b = frame_through_outlines(feature.outline_a, feature.outline_b, core)
        framing = VoidFramingDetailAgent(
            frame_outline_a=frame_a,
            frame_outline_b=frame_b,
            boundary=frame_boundary(frame_a, frame_b, core.center_height, bottom_offset),
            sill=not door,
            bottom_offset=bottom_offset,
            lintel_posts=self.lintel_posts,
            split_bottom_plate_beam=self.split_bottom_plate_beam and door,
            header_width=self.header_width,
            sill_width=self.sill_width,
            king_stud_width=self.king_stud_width,
            jack_stud_width=self.jack_stud_width,
            feature=feature,
            element_layers=[core.layer_path],
            trimming_layers=[core.layer_path],
        )

        cutting = []
        for role in self.CUT_ROLES:
            root = self.root_layer(layer_tree, role)
            if root is None:
                continue
            outline_a, outline_b = self._cut_outlines(feature, role)
            cutting.append(
                LayerCutDetailAgent(
                    root.layer_path,
                    outline_a=outline_a,
                    outline_b=outline_b,
                    cut_beams=root is not core,  # the framing already bounds the core
                    bottom_offset=bottom_offset,
                    feature=feature,
                )
            )
        return [framing] + cutting, []

    def _cut_outlines(self, feature, role):
        """The opening's two face outlines, grown by this role's cut offset."""
        distance = self.cut_offsets.get(LayerRole(role).value)
        if not distance:
            return feature.outline_a, feature.outline_b
        return _grown(feature.outline_a, distance), _grown(feature.outline_b, distance)


def _grown(outline, distance):
    """*outline* (closed, planar) offset outwards by *distance*, still closed."""
    corners = outline.points[:-1]
    candidates = []
    for d in (distance, -distance):
        points = offset_polygon(corners, d)
        candidates.append(Polyline(list(points) + [points[0]]))
    return max(candidates, key=_area)


def _area(polyline):
    points = polyline.points
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:]))) / 2
