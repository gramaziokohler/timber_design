from compas.geometry import Frame
from compas.geometry import Polyline

from .panel_features import PanelFeature
from .panel_features import PanelFeatureType


class MEPPenetration(PanelFeature):
    """A service penetration with a separate outline for each panel layer.

    The outlines are stored in the feature frame and exposed in model space.
    A feature agent uses the core outline to generate surround framing and
    each layer's outline to trim elements on that layer.
    """

    def __init__(self, frame: Frame, outline_interior: Polyline, outline_core: Polyline, outline_exterior: Polyline, name="MEPPenetration", **kwargs):
        for layer_name, outline in (
            ("interior", outline_interior),
            ("core", outline_core),
            ("exterior", outline_exterior),
        ):
            if not outline.is_closed:
                raise ValueError("The {} MEP outline must be closed.".format(layer_name))
        super(MEPPenetration, self).__init__(frame=frame, panel_feature_type=PanelFeatureType.OPENING, name=name, **kwargs)
        self._outline_interior = outline_interior
        self._outline_core = outline_core
        self._outline_exterior = outline_exterior

    @property
    def outline_interior(self) -> Polyline:
        return self._outline_interior.transformed(self.transformation)

    @property
    def outline_core(self) -> Polyline:
        return self._outline_core.transformed(self.transformation)

    @property
    def outline_exterior(self) -> Polyline:
        return self._outline_exterior.transformed(self.transformation)

    @property
    def geometry(self) -> list[Polyline]:
        return [self.outline_interior, self.outline_core, self.outline_exterior]

    @property
    def __data__(self) -> dict:
        data = super(MEPPenetration, self).__data__
        data["outline_interior"] = self._outline_interior
        data["outline_core"] = self._outline_core
        data["outline_exterior"] = self._outline_exterior
        return data
