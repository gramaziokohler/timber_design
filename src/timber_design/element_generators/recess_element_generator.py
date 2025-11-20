import math

from compas.geometry import Line
from compas.geometry import Plane
from compas.geometry import Point
from compas.geometry import Polyline
from compas.geometry import Vector
from compas.geometry import Translation
from compas.tolerance import TOL
from compas.itertools import pairwise

from compas_timber.connections import LButtJoint
from compas_timber.elements import Plate
from compas_timber.fabrication import FreeContour
from compas_timber.utils import extend_line_segments
from compas_timber.utils import join_polyline_segments
from compas_timber.utils import get_polyline_segment_perpendicular_vector

from compas_timber.design import CategoryRule
from timber_design.element_generators import ElementGeneratorParameters
from timber_design.populators import ElementGroup
from timber_design.populators import FeatureBoundaryType
from timber_design.element_generators.generator_functions import get_beam_element_group_intersection
from timber_design.element_generators.generator_functions import split_beam_with_element_groups

# ==========================================================================
# methods for edge beams
# ==========================================================================


def create_recess_elements(parameters, slab_populator, edge_element_group):
    """Get the edge beam definitions for the outer polyline of the slab."""
    plate_edges = []
    new_centerlines = []
    new_edges = []
    for i, edge in edge_element_group.edges.items():
        print(f"edge {i}: {edge}")
        vector = -get_polyline_segment_perpendicular_vector(edge_element_group.outline, i)
        print(f"vector {i}: {vector}")
        plate_edges.append(edge.translated(vector * 3.0))
        print("PE", plate_edges)

        new_centerlines.append(edge.translated((vector * parameters.beam_dimensions["recess"][0]*0.5) - Vector(0,0,(slab_populator.frame_thickness - parameters.beam_dimensions["recess"][1])*0.5)))
        new_edges.append(edge.translated(vector * parameters.beam_dimensions["recess"][0]))
    extend_line_segments(plate_edges, close_loop=True)
    print("PE", plate_edges)
    plate_edges = join_polyline_segments(plate_edges, close_loop=True)
    
    extend_line_segments(new_centerlines, close_loop=True)
    extend_line_segments(new_edges, close_loop=True)
    outline = join_polyline_segments(new_edges, close_loop=True)
    
    elements = []
    edge_elements = {}
    for i, edge in enumerate(new_centerlines):
        elements.append(parameters.beam_from_category(edge, "recess"))
        edge_elements[i] = [elements[-1]]
    elements.append(Plate.from_outline_thickness(plate_edges, parameters.sheeting_inside, vector=Vector(0,0,-1)))
    vector = Vector(0,0,(slab_populator.frame_thickness-parameters.beam_dimensions["recess"][1])*0.5)
    elements[-1].transform(Translation.from_vector(vector))
    return ElementGroup(
        edge_element_group,
        parameters,
        elements=elements,
        edges={index: edge for index, edge in enumerate(new_edges)},
        edge_elements={index: [edge] for index, edge in enumerate(new_centerlines)},
        outline=outline,
        boundary_type=FeatureBoundaryType.INCLUSIVE,
    )



# ==========================================================================
# methods for beam joints
# ==========================================================================




def create_internal_joints(parameters, slab_populator, element_group):
    """Generate the joint definitions for the slab edges. When there is an interface, we use the interface.detail_set to create the joint definition."""
    rules = []
    for corner_index in range(slab_populator.edge_count):
        beam_a = element_group.elements[corner_index]
        beam_b = element_group.elements[(corner_index - 1) % slab_populator.edge_count]
        rule = parameters.get_direct_rule_from_elements(beam_a, beam_b)
        rules.append(rule)
    return [rule for rule in rules if rule is not None]


def cut_out_of_plate(plate, element_group):
    """Apply the opening contour to the given plate.

    Parameters
    ----------
    slab : :class:`compas_timber.elements.Slab`
        The slab to which the opening will be applied.

    Raises
    ------
    :class:`compas_timber.errors.FeatureApplicationError`
        If the opening cannot be applied to the slab.
    """
    free_contour = FreeContour.from_polyline_and_element(element_group.outline, plate, interior=True, is_joinery=False)
    plate.add_feature(free_contour)


class RecessElementGeneratorParameters(ElementGeneratorParameters):
    """A slab detail set that uses the default edge beams, studs, and plates."""

    BEAM_CATEGORY_NAMES = ["recess"]
    NAME = "SlabRecessElementGenerator"
    RULES = [
        CategoryRule(LButtJoint, "recess", "recess", mill_depth=10.0, max_distance=1.0),
    ]

    def __init__(
        self,
        recess_beam_width, 
        recess_beam_height,
        sheeting_inside,
        standard_beam_width=None,
        beam_width_overrides=None,
        joint_rule_overrides=None,
    ):
        super(RecessElementGeneratorParameters, self).__init__(
            standard_beam_width,
            beam_width_overrides,
            joint_rule_overrides,
        )
        self.recess_beam_width = recess_beam_width
        self.recess_beam_height = recess_beam_height
        self.sheeting_inside = sheeting_inside


    def generate_elements(self, slab_populator, edge_group):
        """Populates the slab with elements and joints according to the detail set.

        Parameters
        ----------
        slab_populator : :class:`compas_timber.populators.SlabPopulator`
            The slab populator to populate.
        """
        return create_recess_elements(self, slab_populator, edge_group)

    def cull_beam_segment(self, stud, element_group) -> bool:
        """Cull and split the studs for door openings."""
        return False

    def join_elements(self, slab_populator, element_group):
        """Join the elements for WindowDetailB."""
        rules = create_internal_joints(self, slab_populator, element_group)
        return [rule for rule in rules if rule is not None]

    def apply_to_plate(self, plate, element_group):
        if plate.name == "inside_plate":
            return cut_out_of_plate(plate, element_group)
        
    def update_beam_dimensions(self, slab_populator):
        self.beam_dimensions["recess"] = (self.recess_beam_width, self.recess_beam_height)   