from typing import Optional

from compas.geometry import Frame
from compas.geometry import Polyline

from compas_arch.elements.layer import LayerRole

from .panel_features import PanelFeature
from .panel_features import PanelFeatureType


class Niche(PanelFeature):
    """A one-sided blind recess in a panel.

    The closed outline is stored in the feature frame. ``side`` is the role of the
    surface layer the niche is cut into (:attr:`LayerRole.INTERIOR` or
    :attr:`LayerRole.EXTERIOR`), and ``depth`` is the blind cut depth, measured from
    the panel face. ``depth=None`` means the niche goes through the side layer and the
    framing (core) layer, leaving only the opposite side layer as its back.
    """

    SIDES = (LayerRole.INTERIOR, LayerRole.EXTERIOR)

    def __init__(self, frame: Frame, outline: Polyline, side: LayerRole, depth: Optional[float] = None, name="Niche", **kwargs):
        if not outline.is_closed:
            raise ValueError("Niche outline must be closed.")
        if depth is not None and depth <= 0:
            raise ValueError("Niche depth must be greater than zero, or None to go through the framing layer.")
        side = LayerRole(side)
        if side not in self.SIDES:
            raise ValueError("Niche side must be {} or {}, not {}.".format(LayerRole.INTERIOR.value, LayerRole.EXTERIOR.value, side.value))
        super(Niche, self).__init__(frame=frame, panel_feature_type=PanelFeatureType.RECESS, name=name, **kwargs)
        self._outline = outline
        self.side = side
        self.depth = depth

    @property
    def outline(self) -> Polyline:
        return self._outline.transformed(self.transformation)

    @property
    def geometry(self) -> Polyline:
        return self.outline

    @property
    def __data__(self) -> dict:
        data = super(Niche, self).__data__
        data["outline"] = self._outline
        data["side"] = self.side.value
        data["depth"] = self.depth
        return data

    def compute_elementgeometry(self, include_features=False) -> Polyline:
        return self._outline
