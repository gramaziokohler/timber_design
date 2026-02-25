from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from typing import TYPE_CHECKING
from typing import List
from typing import Union

from compas.geometry import Box
from compas.geometry import Frame
from compas.geometry import Polyline
from compas_timber.elements import Panel
from compas_timber.panel_features import PanelFeature

# type-only import to avoid circular imports
if TYPE_CHECKING:
    from timber_design.populators import ElementGenerator
    from timber_design.populators import GeneratorFactoryParams


class PanelGeneratorFactory(ABC):
    """Abstract factory class for creating element generators.
    The factory takes a panel, a generator parameters object, and an optional list of feature element generators as input and produces one or more
    element generators to populate the panel. Different types of panel element generator factories can be implemented by subclassing this class and
    implementing the `create_generator` method. These subclasses would be used to create specific sets of element generators that populate a specific wall type.
    """

    @classmethod
    @abstractmethod
    def create_generators(cls, element: Union[Panel, PanelFeature], params: GeneratorFactoryParams) -> List[ElementGenerator]:
        """Create an element generator.
        Parameters
        ----------
        params
            Keyword arguments for the generator.
        Returns
        -------
        :class:`timber_design.element_generators.ElementGenerator`
            The created element generator.
        """
        pass


class GeneratorFactoryParams(ABC):
    """Base class for generator factory parameters."""

    pass


def get_frame_panel(panel: Panel, params: GeneratorFactoryParams) -> Panel:
    """Handles the sheeting offsets for the panel outlines."""
    """This method creates a panel that represents the original panel frame without sheeting."""

    si = getattr(params, "sheeting_inside", 0)
    if not si:
        frame_outline_a = panel.outline_a
    else:
        offset_inside = si / panel.thickness
        pts_inside = []
        for pt_a, pt_b in zip(panel.outline_a.points, panel.outline_b.points):
            pt = pt_a * (1 - offset_inside) + pt_b * offset_inside
            pts_inside.append(pt)
        frame_outline_a = Polyline(pts_inside)

    so = getattr(params, "sheeting_outside", 0)
    if not so:
        frame_outline_b = panel.outline_b
    else:
        offset_outside = so / panel.thickness
        pts_outside = []
        for pt_a, pt_b in zip(panel.outline_a.points, panel.outline_b.points):
            pts_outside.append(pt_a * offset_outside + pt_b * (1 - offset_outside))

        frame_outline_b = Polyline(pts_outside)

    box = Box.from_points([pt for pt in frame_outline_a.points + frame_outline_b.points])
    frame_panel = Panel(Frame.worldXY(), box.xsize, box.ysize, box.zsize, frame_outline_a, frame_outline_b)
    return frame_panel
