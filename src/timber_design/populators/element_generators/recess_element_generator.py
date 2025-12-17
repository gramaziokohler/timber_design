from compas.geometry import Translation
from compas.geometry import Polyline
from compas.geometry import Vector
from compas_timber.connections import LMiterJoint
from compas_timber.elements import Plate
from compas_timber.elements import Panel
from compas_timber.fabrication import FreeContour
from compas_timber.utils import extend_line_segments
from compas_timber.utils import get_polyline_segment_perpendicular_vector
from compas_timber.utils import join_polyline_segments

from timber_design.populators import ElementGenerator
from timber_design.populators import ElementGenerator
from timber_design.populators import FeatureBoundaryType
from timber_design.populators import PanelPopulator
from timber_design.workflow import CategoryRule
from timber_design.workflow import DirectRule

# ==========================================================================
# methods for edge beams
# ==========================================================================


class RecessElementGenerator(ElementGenerator):
    """A panel detail set that uses the default edge beams, studs, and plates."""

    BEAM_CATEGORY_NAMES = ["recess"]
    NAME = "RecessElementGenerator"
    RULES = [
        CategoryRule(LMiterJoint, "recess", "recess", max_distance=1.0),
    ]

    def __init__(
        self,
        frame_panel: Panel,
        edge_generator: ElementGenerator,
        recess_beam_width:float,
        recess_beam_height:float,
        sheeting_inside:float,
        standard_beam_width:float|None=None,
        beam_width_overrides:dict|None=None,
        joint_rule_overrides:list[CategoryRule]|None=None,
    ):
        super(RecessElementGenerator, self).__init__(
            frame_panel,
            standard_beam_width,
            beam_width_overrides,
            joint_rule_overrides,
        )
        self.edge_generator = edge_generator
        self.recess_beam_width = recess_beam_width
        self.recess_beam_height = recess_beam_height
        self.sheeting_inside = sheeting_inside
        self.beam_dimensions["recess"] = (self.recess_beam_width, self.recess_beam_height)

    @property
    def panel(self) -> Panel:
        """The panel feature."""
        return self.feature

    def generate_elements(self):
        """Populates the panel with plate and beam elements for the recess detail."""
        return self._create_recess_elements()

    def cull_beam_segment(self, stud) -> bool:
        """Cull and split the studs for door openings."""
        return False

    def join_elements(self, populator_direct_rules:list[DirectRule], element_generators:list[ElementGenerator])->list[DirectRule]:
        """Join the elements for WindowDetailB."""
        rules = self._create_internal_joints()
        return [rule for rule in rules if rule is not None]

    def apply_to_plate(self, plate):
        if plate.name == "inside_plate":
            return self._cut_out_of_plate(plate)

    def _create_recess_elements(self) -> None:
        """Get the edge beam definitions for the outer polyline of the panel."""
        plate_edges = []
        new_centerlines = []
        for i, edge in self.edge_generator.edges.items():
            vector = -get_polyline_segment_perpendicular_vector(self.edge_generator.outline, i)
            plate_edges.append(edge.translated(vector * 3.0))
            new_centerlines.append(
                edge.translated((vector * self.beam_dimensions["recess"][0] * 0.5) + Vector(0, 0, (self.panel.thickness - self.beam_dimensions["recess"][1]) * 0.5))
            )
        extend_line_segments(plate_edges, close_loop=True)
        plate_edges = join_polyline_segments(plate_edges, close_loop=True)
        plate_edges[-1] = plate_edges[0]
        extend_line_segments(new_centerlines, close_loop=True)
        elements = []
        edge_elements = {}
        for i, edge in enumerate(new_centerlines):
            elements.append(self.beam_from_category(edge, "recess"))
            edge_elements[i] = [elements[-1]]
        elements.append(Plate.from_outline_thickness(plate_edges, self.sheeting_inside, vector=Vector(0, 0, -1)))
        vector = Vector(0, 0, (self.panel.thickness * 0.5 - self.beam_dimensions["recess"][1]))
        self.elements[-1].transform(Translation.from_vector(vector))
        self.outline = self.edge_generator.outline.copy()
        self.edges = ({index: edge for index, edge in enumerate(self.outline.lines)},)
        self.edge_elements = ({index: [edge] for index, edge in enumerate(new_centerlines)},)
        self.boundary_type = (FeatureBoundaryType.INCLUSIVE,)

    # ==========================================================================
    # methods for joints
    # ==========================================================================

    def _create_internal_joints(self):
        """Generate the joint definitions for the panel edges. When there is an interface, we use the interface.detail_set to create the joint definition."""
        rules = []
        for corner_index in range(len(self.edges)):
            beam_a = self.elements[corner_index]
            beam_b = self.elements[(corner_index - 1) % len(self.edges)]
            rule = self.get_direct_rule_from_elements(beam_a, beam_b)
            rules.append(rule)
        return [rule for rule in rules if rule is not None]

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
        outline = self.outline.transformed(Translation.from_vector(Vector(0, 0, plate.outline_a[0].z)))
        free_contour = FreeContour.from_polyline_and_element(outline, plate, interior=True, is_joinery=False)
        plate.add_feature(free_contour)
