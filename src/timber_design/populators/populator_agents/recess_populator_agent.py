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

from timber_design.populators import AgentBoundaryType
from timber_design.populators.beam2d import Beam2D
from timber_design.populators.layer import Layer
from timber_design.populators.populator_agents.edge_populator_agent import EdgePopulatorAgent
from timber_design.populators.populator_agents.edge_populator_agent import EdgePopulatorAgentConfig
from timber_design.workflow import CategoryRule


@dataclass
class RecessPopulatorAgentConfig(EdgePopulatorAgentConfig):
    """Configuration for a recess-frame agent.

    Parameters
    ----------
    recess_beam_width : float, optional
        Width of the recess beam.  When ``None``, *standard_beam_width* is used.
    recess_beam_height : float, optional
        Height (Z extent) of the recess beam within the frame layer.  When
        ``None`` the full layer thickness is used, producing no Z offset.
        Set this to a value smaller than the layer thickness to create a
        recessed shelf (the beam sits against ``outline_a``).
    sheeting_recess : float, optional
        Thickness of the sheeting plate inserted into the recess.
    """
    IS_ABSTRACT = False

    recess_beam_width: Optional[float] = None
    recess_beam_height: Optional[float] = None
    sheeting_recess: Optional[float] = None

    def __post_init__(self):
        super().__post_init__()
        if self.recess_beam_width is not None:
            self.beam_widths["recess"] = self.recess_beam_width

    def _agent_kwargs(self):
        kwargs = super()._agent_kwargs()
        kwargs["recess_beam_height"] = self.recess_beam_height
        kwargs["sheeting_recess"] = self.sheeting_recess
        return kwargs

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
    ``recess_beam_width / 2`` and shifted in Z so the beam sits flush with
    ``outline_a``.  Also creates a thin :class:`~compas_timber.elements.Plate`
    (the sheeting plate) whose outline matches the inward-offset edge outline.

    The agent copies the :attr:`~LayerAgent.outline` from the
    :class:`EdgePopulatorAgent` it wraps (it does not define an independent
    boundary).  Its :attr:`~LayerAgent.BOUNDARY_TYPE` is
    :attr:`~FeatureBoundaryType.INCLUSIVE`.

    Parameters
    ----------
    layer : :class:`~timber_design.populators.Layer`
        The structural frame layer this agent operates within.
    params : :class:`RecessPopulatorAgentConfig`
        Recess beam dimensions and optional sheeting recess offset.

    Attributes
    ----------
    recess_beam_height : float or None
        Height of the recess beam.  ``None`` → full layer thickness.
    sheeting_recess : float or None
        Thickness of the sheeting plate inserted into the recess.
    """

    BEAM_CATEGORY_NAMES = ["recess", "edge_stud", "top_plate_beam", "bottom_plate_beam"]
    NAME = "RecessPopulatorAgent"
    BOUNDARY_TYPE = AgentBoundaryType.INCLUSIVE
    INTERNAL_JOINT_RULES = [
        CategoryRule(LMiterJoint, "recess", "recess", max_distance=1.0),
    ]
    EXTERNAL_JOINT_RULES = [
        CategoryRule(TButtJoint, "recess", "top_plate_beam", max_distance=1.0),
        CategoryRule(TButtJoint, "recess", "bottom_plate_beam", max_distance=1.0),
        CategoryRule(TButtJoint, "recess", "edge_stud", max_distance=1.0),
    ]

    def __init__(
        self,
        layer,
        beam_widths=None,
        internal_joint_overrides=None,
        external_joint_overrides=None,
        standard_beam_width_increment=None,
        recess_beam_height=None,
        sheeting_recess=None,
    ):
        super(RecessPopulatorAgent, self).__init__(
            layer,
            beam_widths=beam_widths,
            internal_joint_overrides=internal_joint_overrides,
            external_joint_overrides=external_joint_overrides,
            standard_beam_width_increment=standard_beam_width_increment,
        )
        self.recess_beam_height = recess_beam_height
        self.sheeting_recess = sheeting_recess

    def trim_plate(self, plate):
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
        outline = self.outline.transformed(Translation.from_vector(Vector(0, 0, plate.outline_a[0].z - self.outline[0].z)))
        free_contour = FreeContour.from_polyline_and_element(outline, plate, interior=True, is_joinery=False)
        plate.add_feature(free_contour)

    def generate_elements(self) -> None:
        """Generate edge beams, recess beams, and the sheeting plate."""
        super(RecessPopulatorAgent, self).generate_elements()

        recess_width = self.beam_widths["recess"]
        recess_height = self.recess_beam_height if self.recess_beam_height is not None else self.layer.thickness
        z_offset = (self.layer.thickness - recess_height) * 0.5

        plate_edges = []
        new_centerlines = []
        for i, edge in enumerate(self.outline.lines):
            vector = -get_polyline_segment_perpendicular_vector(self.outline, i)
            plate_edges.append(edge.translated(vector * 3.0))
            new_centerlines.append(
                edge.translated((vector * recess_width * 0.5) + Vector(0, 0, z_offset))
            )

        extend_line_segments(plate_edges, close_loop=True)
        plate_edges = join_polyline_segments(plate_edges, close_loop=True)[0][0]
        plate_edges[-1] = plate_edges[0]
        extend_line_segments(new_centerlines, close_loop=True)

        for edge in new_centerlines:
            beam = Beam2D.from_centerline(edge, width=recess_width, height=recess_height, z_vector=Vector(0, 0, 1))
            beam.attributes["category"] = "recess"
            self.elements.append(beam)

        if self.sheeting_recess:
            self.elements.append(Plate.from_outline_thickness(plate_edges, self.sheeting_recess, vector=Vector(0, 0, -1)))
            plate_vector = Vector(0, 0, self.layer.thickness * 0.5 - recess_height)
            self.elements[-1].transform(Translation.from_vector(plate_vector))
        self.outline = self.outline.copy() if self.outline else None

    # ==========================================================================
    # Cross-layer trimming
    # ==========================================================================

    def create_joint_defs(self):
        """Generate joint definitions for both edge beams and recess beams.

        Edge-beam pairs (both elements have ``edge_index``) are handled by the
        geometric :meth:`~EdgePopulatorAgent.create_edge_beam_joint_rule`
        inherited from :class:`EdgePopulatorAgent`.  All other pairs — in
        practice ``"recess"``–``"recess"`` pairs — fall through to
        :meth:`~LayerAgent.get_direct_rule_from_elements`, which looks up
        :attr:`~PopulatorAgent.INTERNAL_JOINT_RULES` by category name and finds
        the ``CategoryRule(LMiterJoint, "recess", "recess")`` entry.
        """
        for candidate in self.create_joint_candidates():
            edge_a = candidate.element_a.attributes.get("edge_index")
            edge_b = candidate.element_b.attributes.get("edge_index")
            if edge_a is not None and edge_b is not None:
                # Edge-beam pairs: geometric joint by default, rule-based when
                # the pair was overridden (see EdgePopulatorAgent._edge_joint_rule).
                rule = self._edge_joint_rule(*candidate.elements)
            else:
                rule = self.get_direct_rule_from_elements(candidate.element_a, candidate.element_b)
            if rule is not None:
                self.joint_defs.append(rule)


# Set after both classes are defined so forward reference is resolved
RecessPopulatorAgentConfig.AGENT_TYPE = RecessPopulatorAgent
