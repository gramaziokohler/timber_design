from __future__ import annotations
from re import sub
from typing import Optional
from dataclasses import dataclass

from compas.geometry import Polyline
from compas.tolerance import TOL
from compas_timber.elements import Panel

from timber_design.populators.populator_agents.populator_agent import PopulatorAgent


@dataclass

class LayerDefinition:
    """Definition of a layer within a panel."""
    def __init__(self,
                 thickness:Optional[float],
                 name: Optional[str]=None,
                 agents:Optional[list[PopulatorAgent]]=None,
                 sublayers:Optional[list[LayerDefinition]]=None,
                 is_framing_layer:Optional[bool]=False):

        if agents and sublayers:
            raise ValueError("A layer cannot have both agents and sublayers agents should be placed on the leaf sublayers.")

        if not (thickness or sublayers):
            raise ValueError("Either thickness or sublayers with thickness must be provided.")

        if thickness and sublayers:
            if not TOL.is_close(sum([l.thickness for l in sublayers]), thickness):
                raise ValueError(f"Total thickness of sublayers ({sum([l.thickness for l in sublayers])}) must equal layer thickness ({thickness}).")

        self.thickness = thickness or sum([l.thickness for l in sublayers])
        self.name = name 
        self.agents = agents or []  
        self.sublayers = sublayers or []



class Layer:
    """A named cross-section layer within a panel.

    Each ``Layer`` carries its own :class:`~compas_timber.elements.Panel` whose
    ``outline_a`` and ``outline_b`` define the exact geometric boundaries of that
    layer in populator space.

    The four standard layer names produced by
    :func:`~timber_design.populators.get_layers` are:

    ``"local"``
        The full panel in populator space (including all sheeting).
    ``"frame"``
        The structural frame panel — the full panel trimmed by
        ``sheeting_inside`` / ``sheeting_outside`` on each side.
    ``"interior"``
        The inside sheathing layer (only present when ``sheeting_inside > 0``).
        Its ``outline_a`` is the innermost face of the full panel and
        ``outline_b`` is the inner face of the frame.
    ``"exterior"``
        The outside sheathing layer (only present when ``sheeting_outside > 0``).
        Its ``outline_a`` is the outer face of the frame and ``outline_b``
        is the outermost face of the full panel.

    Parameters
    ----------
    panel : :class:`compas_timber.elements.Panel`
        The panel geometry for this layer.
    name : str
        The layer identifier (``"local"``, ``"frame"``, ``"interior"``,
        or ``"exterior"``).

    Attributes
    ----------
    thickness : float
        Convenience shortcut to ``layer.panel.thickness``.
    """
    def __init__(self, panel:Optional[Panel]=None, name: Optional[str]=None, agents:Optional[PopulatorAgent]=None, layer_index: Optional[int] = None):
         self.panel = panel
         self.name = name 
         self.agents = agents
         self.layer_index = layer_index

    def from_panel_and_range(panel: Panel, range_a: float, range_b: float, name: Optional[str], layer_index: Optional[int] = None) -> Layer:
        """Create a layer by trimming a panel to a given range along its local Z axis."""
        if range_a:
            offset = range_a / panel.thickness
            frame_outline_a = Polyline(
                [pt_a * (1.0 - offset) + pt_b * offset for pt_a, pt_b in zip(panel.outline_a.points, panel.outline_b.points)]
            )
        else:
            frame_outline_a = panel.outline_a

        # ---- frame outline on the exterior side ----
        if range_b:
            offset = range_b / panel.thickness
            frame_outline_b = Polyline(
                [pt_a * (1.0 - offset) + pt_b * offset for pt_a, pt_b in zip(panel.outline_a.points, panel.outline_b.points)]
            )
        else:
            frame_outline_b = panel.outline_b
        panel = Panel.from_outlines(frame_outline_a, frame_outline_b)
        return Layer(panel, name)



    @property
    def thickness(self) -> float:
        """Thickness of this layer's panel."""
        return self.panel.thickness
