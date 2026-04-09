from dataclasses import dataclass
from typing import List
from typing import Optional
from typing import Union

from compas.geometry import Translation
from compas.geometry import Vector
from compas_timber.connections import LMiterJoint
from compas_timber.connections import TButtJoint
from compas_timber.elements import Panel
from compas_timber.elements import Plate
from compas_timber.fabrication import FreeContour
from compas_timber.utils import extend_line_segments
from compas_timber.utils import get_polyline_segment_perpendicular_vector
from compas_timber.utils import join_polyline_segments

from timber_design.populators import ElementGenerator
from timber_design.populators import ElementGeneratorParams
from timber_design.populators import FeatureBoundaryType
from timber_design.workflow import CategoryRule


@dataclass
class RecessElementGeneratorParams(ElementGeneratorParams):
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


class RecessElementGenerator(ElementGenerator):
    """A panel detail set that uses the default edge beams, studs, and plates."""

    BEAM_CATEGORY_NAMES = ["recess"]
    NAME = "RecessElementGenerator"
    BOUNDARY_TYPE = FeatureBoundaryType.INCLUSIVE
    RULES = [
        CategoryRule(LMiterJoint, "recess", "recess", max_distance=1.0),
        CategoryRule(TButtJoint, "recess", "top_plate_beam", max_distance=1.0),
        CategoryRule(TButtJoint, "recess", "bottom_plate_beam", max_distance=1.0),
        CategoryRule(TButtJoint, "recess", "edge_stud", max_distance=1.0),
    ]

    def __init__(
        self,
        frame_panel: Panel,
        edge_generator: ElementGenerator,
        params: RecessElementGeneratorParams,
    ):
        super(RecessElementGenerator, self).__init__(frame_panel, params)
        self.edge_generator = edge_generator
        self.recess_beam_width = params.recess_beam_width
        self.recess_beam_height = params.recess_beam_height
        self.sheeting_recess = params.sheeting_recess
        self.beam_dimensions["recess"] = (self.recess_beam_width, self.recess_beam_height)

    def apply_to_plate(self, plate):
        if plate.name == "inside_plate":
            return self._cut_out_of_plate(plate)

    def generate_elements(self) -> None:
        """Get the edge beam definitions for the outer polyline of the panel."""
        plate_edges = []
        new_centerlines = []
        for i, edge in enumerate(self.edge_generator.outline.lines):
            vector = -get_polyline_segment_perpendicular_vector(self.edge_generator.outline, i)
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
        self.outline = self.edge_generator.outline.copy() if self.edge_generator.outline else None

    # ==========================================================================
    # methods for joints
    # ==========================================================================


    def _cut_out_of_plate(self, plate: Plate):
        """Apply the opening contour to the given plate.

        Parameters
        ----------
        panel : :class:`compas_timber.elements.Panel`
            The panel to which the opening will be applied.

        Raises
        ------
        :class:`compas_timber.errors.FeatureApplicationError`
            If the opening cannot be applied to the panel.
        """
        if not self.outline:
            raise ValueError("No outline defined for recess element generator.")
        outline = self.outline.transformed(Translation.from_vector(Vector(0, 0, plate.outline_a[0].z)))
        free_contour = FreeContour.from_polyline_and_element(outline, plate, interior=True, is_joinery=False)
        plate.add_feature(free_contour)
