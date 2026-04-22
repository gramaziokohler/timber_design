from dataclasses import dataclass
from typing import Optional

from compas.geometry import Translation
from compas.geometry import Vector
from compas_timber.connections import LMiterJoint
from compas_timber.connections import TButtJoint
from compas_timber.elements import Plate
from compas_timber.fabrication import FreeContour
from compas_timber.utils import extend_line_segments
from compas_timber.utils import get_polyline_segment_perpendicular_vector
from compas_timber.utils import join_polyline_segments

from timber_design.populators.layer import Layer
from timber_design.populators.populator_agents.layer_agent import AgentBoundaryType
from timber_design.populators.populator_agents.layer_agent import LayerAgent
from timber_design.populators.populator_agents.layer_agent import LayerAgentConfig
from timber_design.workflow import CategoryRule


@dataclass
class RecessPopulatorAgentConfig(LayerAgentConfig):
    """Configuration for a recess-frame agent.

    Parameters
    ----------
    recess_beam_width : float
        Width of the recess beam in model units.
    recess_beam_height : float, optional
        Height of the recess beam.  When ``None`` the full frame thickness is used.
    sheeting_recess : float, optional
        Thickness of the sheeting plate inserted into the recess.
    """

    recess_beam_width: float = 0.0
    recess_beam_height: Optional[float] = None
    sheeting_recess: Optional[float] = None

    @property
    def __data__(self):
        data = super().__data__
        data["recess_beam_width"] = self.recess_beam_width
        data["recess_beam_height"] = self.recess_beam_height
        data["sheeting_recess"] = self.sheeting_recess
        return data


class RecessPopulatorAgent(LayerAgent):
    """Generates a recessed frame and sheathing plate along the panel outline.

    Creates one ``"recess"`` :class:`~timber_design.populators.Beam2D` per
    segment of the edge agent's outline, offset inward by
    ``recess_beam_width / 2`` and shifted in Z so the beam sits flush with the
    required Z level.  Also creates a thin :class:`~compas_timber.elements.Plate`
    (the sheeting plate) whose outline matches the inward-offset edge outline.

    The agent copies the :attr:`~LayerAgent.outline` from the
    :class:`EdgePopulatorAgent` it wraps (it does not define an independent
    boundary).  Its :attr:`~LayerAgent.BOUNDARY_TYPE` is
    :attr:`~FeatureBoundaryType.INCLUSIVE`.

    Cross-layer behaviour
    ---------------------
    :meth:`trim_cross_layer` cuts sheathing plates on any layer whose index is
    strictly less than this agent's own :attr:`~LayerAgent.layer_index`
    (i.e. layers that sit inside the recess frame).

    Parameters
    ----------
    layer : :class:`~timber_design.populators.Layer`
        The structural frame layer this agent operates within.
    edge_agent : :class:`~timber_design.populators.EdgePopulatorAgent`
        The edge agent whose :attr:`~LayerAgent.outline` is used as the
        baseline for the recess beam centrelines.
    params : :class:`RecessPopulatorAgentConfig`
        Recess beam dimensions and optional sheeting recess offset.

    Attributes
    ----------
    edge_agent : :class:`~timber_design.populators.EdgePopulatorAgent`
        Reference to the companion edge agent.
    recess_beam_width : float
        Width of the recess beam in model units.
    recess_beam_height : float or None
        Height of the recess beam.  When ``None`` the full frame thickness is used.
    sheeting_recess : float or None
        Thickness of the sheeting plate inserted into the recess.
    """

    BEAM_CATEGORY_NAMES = ["recess"]
    NAME = "RecessPopulatorAgent"
    BOUNDARY_TYPE = AgentBoundaryType.INCLUSIVE
    INTERNAL_RULES = [
        CategoryRule(LMiterJoint, "recess", "recess", max_distance=1.0),
    ]
    EXTERNAL_RULES = [
        CategoryRule(TButtJoint, "recess", "top_plate_beam", max_distance=1.0),
        CategoryRule(TButtJoint, "recess", "bottom_plate_beam", max_distance=1.0),
        CategoryRule(TButtJoint, "recess", "edge_stud", max_distance=1.0),
    ]

    def __init__(self, layer, edge_agent, params):
        # type: (Layer, LayerAgent, RecessPopulatorAgentConfig) -> None
        super(RecessPopulatorAgent, self).__init__(layer, params)
        self.edge_agent = edge_agent
        self.recess_beam_width = params.recess_beam_width
        self.recess_beam_height = params.recess_beam_height
        self.sheeting_recess = params.sheeting_recess
        self.beam_dimensions["recess"] = (self.recess_beam_width, self.recess_beam_height)

    def apply_to_plate(self, plate):
        """Cut the recess outline into *plate*."""
        self._cut_out_of_plate(plate)

    def generate_elements(self) -> None:
        """Generate recess beams and the sheeting plate for the panel outline."""
        plate_edges = []
        new_centerlines = []
        for i, edge in enumerate(self.edge_agent.outline.lines):
            vector = -get_polyline_segment_perpendicular_vector(self.edge_agent.outline, i)
            plate_edges.append(edge.translated(vector * 3.0))
            new_centerlines.append(
                edge.translated((vector * self.beam_dimensions["recess"][0] * 0.5) + Vector(0, 0, (self.panel.thickness - self.beam_dimensions["recess"][1]) * 0.5))
            )
        extend_line_segments(plate_edges, close_loop=True)
        plate_edges = join_polyline_segments(plate_edges, close_loop=True)[0][0]
        plate_edges[-1] = plate_edges[0]
        extend_line_segments(new_centerlines, close_loop=True)
        for edge in new_centerlines:
            self.elements.append(self.beam_from_category(edge, "recess"))
        self.elements.append(Plate.from_outline_thickness(plate_edges, self.sheeting_recess, vector=Vector(0, 0, -1)))
        vector = Vector(0, 0, (self.panel.thickness * 0.5 - self.beam_dimensions["recess"][1]))
        self.elements[-1].transform(Translation.from_vector(vector))
        self.outline = self.edge_agent.outline.copy() if self.edge_agent.outline else None

    # ==========================================================================
    # Cross-layer trimming
    # ==========================================================================

    def trim_cross_layer(self, other_agent):
        """Cut the recess outline into plates on inner (lower-index) layers.

        Only acts when *other_agent*'s :attr:`~LayerAgent.layer_index` is
        strictly less than this agent's own index, i.e. the other layer sits
        inside (closer to the interior face) of the recess frame.

        Parameters
        ----------
        other_agent : :class:`~timber_design.populators.LayerAgent`
            The agent whose plate elements may receive the recess contour cut.
        """
        if self.layer_index is None or other_agent.layer_index is None:
            return
        if other_agent.layer_index >= self.layer_index:
            return
        for element in other_agent.elements:
            if element.is_plate:
                self._cut_out_of_plate(element)

    # ==========================================================================
    # Private helpers
    # ==========================================================================

    def _cut_out_of_plate(self, plate: Plate):
        """Apply the recess outline as a ``FreeContour`` cut to *plate*.

        Parameters
        ----------
        plate : :class:`compas_timber.elements.Plate`
            The sheathing plate to cut.

        Raises
        ------
        ValueError
            If :attr:`outline` has not been set (i.e. :meth:`generate_elements`
            has not been called yet).
        """
        if not self.outline:
            raise ValueError("No outline defined for recess populator agent.")
        outline = self.outline.transformed(Translation.from_vector(Vector(0, 0, plate.outline_a[0].z)))
        free_contour = FreeContour.from_polyline_and_element(outline, plate, interior=True, is_joinery=False)
        plate.add_feature(free_contour)


# Set after both classes are defined so forward reference is resolved
RecessPopulatorAgentConfig.AGENT_TYPE = RecessPopulatorAgent
