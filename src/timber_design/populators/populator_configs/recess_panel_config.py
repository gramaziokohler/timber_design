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

from timber_design.populators import FeatureBoundaryType
from timber_design.populators import EdgePopulatorAgent
from timber_design.populators.layer import Layer
from timber_design.workflow import CategoryRule
from timber_design.populators import LayerDefinition
from timber_design.populators import PanelPopulatorConfig

from timber_design.populators.populator_agents.edge_populator_agent import EdgePopulatorAgentConfig
from timber_design.populators.populator_agents.recess_populator_agent import RecessPopulatorAgentConfig
from timber_design.populators.populator_agents.plate_populator_agent import PlatePopulatorAgentConfig



def recess_panel(
    panel=None,
    standard_beam_width=None,
    recess_beam_width=None,
    recess_beam_height=None,
    edge_beam_min_width=None,
    standard_beam_width_increment=None,
    sheeting_outside=0,
    sheeting_inside=0,
    sheeting_recess=0,
    beam_width_overrides=None,
    joint_rule_overrides=None,
    default_feature_configs=None,
):
    """Create a config for a recess panel populator.

    Parameters
    ----------
    panel : :class:`compas_timber.elements.Panel`, optional
        The panel to populate.
    standard_beam_width : float, optional
        Default beam width.
    recess_beam_width : float, optional
        Width of the recess beam.
    recess_beam_height : float, optional
        Height of the recess beam.
    edge_beam_min_width : float, optional
        Minimum width for edge beams.
    standard_beam_width_increment : float, optional
        Rounding increment for edge-beam widths.
    sheeting_outside : float, optional
        Thickness of external sheathing plate.
    sheeting_inside : float, optional
        Thickness of internal sheathing plate.
    sheeting_recess : float, optional
        Thickness of the sheeting plate in the recess.
    beam_width_overrides : dict, optional
        Per-category width overrides passed to every agent config.
    joint_rule_overrides : list, optional
        Rules that replace matching entries in any agent's ``INTERNAL_RULES`` list.
    default_feature_configs : dict, optional
        Mapping from panel feature class to a ``PopulatorAgentConfig`` instance.
    """

    recess_agent_config = RecessPopulatorAgentConfig(
        standard_beam_width_increment=standard_beam_width_increment,
        edge_beam_min_width=edge_beam_min_width or standard_beam_width,        
        recess_beam_width=recess_beam_width or standard_beam_width,
        recess_beam_height=recess_beam_height or standard_beam_width,
        sheeting_recess=sheeting_recess,
        beam_width_overrides=beam_width_overrides,
        joint_rule_overrides=joint_rule_overrides,
    )
    layer_defs = []
    if sheeting_inside:
        layer_defs.append(LayerDefinition(sheeting_inside, name="interior", agent_configs=[PlatePopulatorAgentConfig()]))
    layer_defs.append(LayerDefinition(None, name="frame", is_framing_layer=True, agent_configs=[recess_agent_config]))
    if sheeting_outside:
        layer_defs.append(LayerDefinition(sheeting_outside, name="exterior", agent_configs=[PlatePopulatorAgentConfig()]))


    config = PanelPopulatorConfig(panel=panel, layer_defs=layer_defs, default_feature_configs=default_feature_configs)
    return config


@dataclass
class RecessPopulatorAgentConfig(EdgePopulatorAgentConfig):
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


class RecessPopulatorAgent(EdgePopulatorAgent):
    """Generates a recessed frame and sheathing plate along the panel outline.

    Creates one ``"recess"`` :class:`~timber_design.populators.Beam2D` per
    segment of the edge agent's outline, offset inward by
    ``recess_beam_width / 2`` and shifted in Z so the beam sits flush with the
    required Z level.  Also creates a thin :class:`~compas_timber.elements.Plate`
    (the sheeting plate) whose outline matches the inward-offset edge outline.

    The agent copies the :attr:`~PopulatorAgent.outline` from the
    :class:`EdgePopulatorAgent` it wraps (it does not define an independent
    boundary).  Its :attr:`~PopulatorAgent.BOUNDARY_TYPE` is
    :attr:`~FeatureBoundaryType.INCLUSIVE`.

    Cross-layer behaviour
    ---------------------
    :meth:`affects_layer` returns ``True`` for any layer whose index is less
    than or equal to this agent's own :attr:`~PopulatorAgent.layer_index`.
    This allows the recess frame to cut sheeting plates on lower (inside)
    layers during :meth:`~timber_design.populators.PanelPopulator.trim_cross_layer_elements`.

    Parameters
    ----------
    layer : :class:`~timber_design.populators.Layer`
        The structural frame layer this agent operates within.
    params : :class:`RecessPopulatorAgentConfig`
        Recess beam dimensions and optional sheeting recess offset.

    Attributes
    ----------
    recess_beam_width : float
        Width of the recess beam in model units.
    recess_beam_height : float or None
        Height of the recess beam.  When ``None`` the full frame thickness is used.
    sheeting_recess : float or None
        Thickness of the sheeting plate inserted into the recess.
    """

    BEAM_CATEGORY_NAMES = ["recess"]
    NAME = "RecessPopulatorAgent"
    BOUNDARY_TYPE = FeatureBoundaryType.INCLUSIVE
    INTERNAL_RULES = [
        CategoryRule(LMiterJoint, "recess", "recess", max_distance=1.0),
    ]
    EXTERNAL_RULES = [
        CategoryRule(TButtJoint, "recess", "top_plate_beam", max_distance=1.0),
        CategoryRule(TButtJoint, "recess", "bottom_plate_beam", max_distance=1.0),
        CategoryRule(TButtJoint, "recess", "edge_stud", max_distance=1.0),
    ]

    def __init__(
        self,
        layer: Layer,
        params: RecessPopulatorAgentConfig,
    ):
        super(RecessPopulatorAgent, self).__init__(layer, params)
        self.recess_beam_width = params.recess_beam_width
        self.recess_beam_height = params.recess_beam_height
        self.sheeting_recess = params.sheeting_recess
        self.beam_dimensions["recess"] = (self.recess_beam_width, self.recess_beam_height)

    def apply_to_plate(self, plate):
        """Cut the recess outline into *plate* if it belongs to an affected layer."""
        if self.affects_layer(getattr(plate, "layer_index", None)):
            return self._cut_out_of_plate(plate)

    def generate_elements(self) -> None:
        """Generate recess beams and the sheeting plate for the panel outline."""
        super().generate_elements(self)
        plate_edges = []
        new_centerlines = []
        for i, edge in enumerate(self.outline.lines):
            vector = -get_polyline_segment_perpendicular_vector(self.outline, i)
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
        self.outline = self.outline.copy() if self.outline else None

    # ==========================================================================
    # Cross-layer boundary behaviour
    # ==========================================================================

    def affects_layer(self, layer_index):
        """Return ``True`` for any layer at or below this agent's own layer index.

        This makes the recess agent cut sheathing plates on lower (inside)
        layers during
        :meth:`~timber_design.populators.PanelPopulator.trim_cross_layer_elements`.

        Parameters
        ----------
        layer_index : int or None
            Layer index to check.  ``None`` is treated as matching any layer.
        """
        if layer_index is None or self.layer_index is None:
            return True
        return layer_index <= self.layer_index

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
