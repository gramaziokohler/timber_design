from compas.geometry import Box
from compas.geometry import Frame
from compas.geometry import Point
from compas.geometry import Polyline
from compas.geometry import Transformation
from compas.geometry import Vector
from compas.geometry import angle_vectors
from compas.geometry import angle_vectors_signed
from compas.geometry import bounding_box_xy
from compas.geometry import cross_vectors
from compas_timber.design import CategoryRule
from compas_timber.elements import Opening
from compas_timber.elements import SlabConnectionInterface
from compas_timber.model import TimberModel
from compas_timber.utils import get_polyline_segment_perpendicular_vector
from compas_timber.utils import is_point_in_polyline
from compas_timber.utils import is_polyline_clockwise


class SlabSelector(object):  # TODO change to detail selector or similar
    """Selects slabs based on their attributes."""

    def __init__(self, slab_attr, attr_value):
        self._slab_attr = slab_attr
        self._attr_value = attr_value

    def select(self, slab):
        value = getattr(slab, self._slab_attr, None)
        if value is None:
            return False
        else:
            return value == self._attr_value


class AnySlabSelector(object):
    def select(self, _):
        return True


class OpeningPopulator(object):
    """Populates openings in a slab."""

    def __init__(self, opening, parameters, slab_populator):
        self.opening = opening
        self.parameters = parameters
        self.slab_populator = slab_populator


class FeatureDefinition(object):
    """Defines a feature in the slab populator.

    Parameters
    ----------
    feature : :class:`compas_timber.elements.SlabFeature`
        The geometry of the feature.
    parameters : timber_design.element_generators.ElementGeneratorParameters
        The parameters for the feature.

    """

    def __init__(self, feature, parameters):
        self.feature = feature
        self.parameters = parameters


class SlabPopulator(object):
    """Create a timber assembly from a surface.

    Parameters
    ----------
    configuration_set : :class:`WallPopulatorConfigurationSet`
        The configuration for this wall populator.
    slab : :class:`compas_timber.elements.Slab`
        The slab for this populater to fill with beams.

    Attributes
    ----------
    outline_a : :class:`compas.geometry.Polyline`
        The outline A of the slab.
    outline_b : :class:`compas.geometry.Polyline`
        The outline B of the slab.
    openings : list of :class:`compas.geometry.Polyline`
        The openings in the slab.
    frame : :class:`compas.geometry.Polyline`
        The frame of the slab.
    interfaces : list of :class:`compas_timber.connections.SlabToSlabInterface`
        The interfaces of the slab. These are the connections to other slabs.
    edge_count : int
        The number of edges in the slab outline.
    stud_spacing : float
        The spacing between studs in the slab.
    stud_direction : :class:`compas.geometry.Vector`
        The direction of the studs in the slab.
    tolerance : :class:`compas_tolerance.Tolerance`
        The tolerance for the slab populator.
    sheeting_outside : float
        The outside sheeting thickness from the configuration set.
    sheeting_inside : float
        The inside sheeting thickness from the configuration set.
    frame_outline_a : :class:`compas.geometry.Polyline`
        The outline A of the frame.
    frame_outline_b : :class:`compas.geometry.Polyline`
        The outline B of the frame.


    """

    def __init__(self, slab, parameters, feature_definitions=None):
        super(SlabPopulator, self).__init__()
        self._slab = slab
        self.parameters = parameters
        self.test = []
        self.stud_direction = getattr(parameters, "stud_direction", Vector(0, 0, 1))
        self.transformation_slab_to_populator = self.get_transformation_to_populator_space(slab, parameters)
        self.outline_a = slab.local_outlines[0].transformed(self.transformation_slab_to_populator)
        self.outline_b = slab.local_outlines[1].transformed(self.transformation_slab_to_populator)
        self.element_groups = []
        self.feature_definitions = feature_definitions or []
        for fd in self.feature_definitions:
            fd.feature = fd.feature.transformed(self.transformation_slab_to_populator)
            fd.parameters.update_beam_dimensions(self)

        self._obb = None
        self._model = TimberModel()
        self.direct_rules = []
        self.edge_planes = {}
        for i, pl in self._slab.edge_planes.items():
            self.edge_planes[i] = pl.transformed(self.transformation_slab_to_populator)
        self._inner_edge_beam_dict = {}
        self._interior_corner_indices = []
        self._edge_perpendicular_vectors = []
        self.test = []
        self.set_frame_outlines(parameters)
        self.parameters.update_beam_dimensions(self)

    def __repr__(self):
        return "SlabPopulator({}, {})".format(self.parameters, self._slab)

    @property
    def slab(self):
        """The slab associated with this populator."""
        return self._slab

    @property
    def edge_count(self):
        """Returns the number of edges in the slab outline."""
        return len(self.outline_a) - 1

    @property
    def frame(self):
        """The frame of the slab populator. This frame is in relation to the slab outlines in the slab local space."""
        return Frame.from_transformation(self.transformation_slab_to_populator.inverse())

    def get_transformation_to_populator_space(self, slab, parameters):
        """The slab_populator frame in global space."""

        if not getattr(parameters, "stud_direction", None):
            stud_dir = Vector(0, 1, 0)
        else:
            stud_dir = parameters.stud_direction.transformed(slab.transformation.inverse())  # bring stud direction into local slab space
            if angle_vectors(stud_dir, Vector(0, 0, 1)) < 1e-3 or angle_vectors(stud_dir, Vector(0, 0, -1)) < 1e-3:
                stud_dir = Vector(0, 1, 0)
            else:
                stud_dir[2] = 0.0

        frame = Frame(Point(0, 0, 0), cross_vectors(stud_dir, Vector(0, 0, 1)), stud_dir)  # get frame with stud direction as y axis
        transform_to_sp = Transformation.from_frame(frame).inverse()
        rebased_pts = [pt.transformed(transform_to_sp) for pt in slab.local_outlines[0].points + slab.local_outlines[1].points]  # rebase slab points into stud direction frame
        min_pt = bounding_box_xy(rebased_pts)[0]
        frame = Frame(min_pt, Vector(1, 0, 0), Vector(0, 1, 0)).transformed(transform_to_sp.inverse())
        frame.point[2] = parameters.sheeting_inside + self.frame_thickness / 2  # offset to make frame center plane at world XY
        return Transformation.from_frame(frame).inverse()

    @property
    def elements(self):
        return list(self._model.elements())

    @property
    def beams(self):
        return list(self._model.beams)

    @property
    def plates(self):
        return list(self._model.plates)

    def add_element(self, element, edge_index=None):
        self._model.add_element(element)

    def remove_element(self, element):
        self._model.remove_element(element)

    def add_elements(self, elements, edge_index=None):
        if not isinstance(elements, list):
            elements = [elements]
        for element in elements:
            self.add_element(element, edge_index)

    def process_joinery(self):
        for element_group in self.element_groups:
            self.add_elements(element_group.elements)

        for j_def in self.direct_rules:
            if isinstance(j_def, CategoryRule):
                continue
            if not j_def:
                continue
            for e in j_def.elements:
                if e not in self.elements:
                    raise ValueError("Element in joint definition not found in model: {}, x = {}".format(e.attributes.get("category", None), e.frame.point[0]))
            else:
                j_def.joint_type.create(self._model, *j_def.elements, **j_def.kwargs)
        self._model.process_joinery()

    def merge_with_model(self, model, clear_slab=False):
        """Merges the slab populator with a timber model."""
        if clear_slab:
            for element in self._slab.children:
                model.remove_element(element)
                for joint in model.joints:
                    if element in joint.elements:
                        model.remove_joint(joint)
        for element in self.elements:
            element.transform(self.transformation_slab_to_populator.inverse())
            model.add_element(element, parent=self._slab)
        for j in self._model.joints:
            model.add_joint(j)

    @property
    def thickness(self):
        """Returns the thickness of the slab."""
        return self._slab.thickness

    @property
    def frame_thickness(self):
        """Returns the frame thickness, adjusted for sheeting."""
        return self.thickness - self.parameters.sheeting_inside - self.parameters.sheeting_outside

    @property
    def interfaces(self):
        """Get all interfaces of the slab."""
        return list(filter(lambda x: isinstance(x, SlabConnectionInterface), self._slab.features))

    @property
    def openings(self):
        """Get all openings of the slab."""
        return list(filter(lambda x: isinstance(x, Opening), self._slab.features))

    @property
    def edge_interfaces(self):
        """Get the edge interfaces of the slab."""
        interfaces = {}
        for interface in self.interfaces:
            if interface.edge_index is not None:
                if interfaces.get(interface.edge_index) is None:
                    interfaces[interface.edge_index] = []
                interfaces[interface.edge_index].append(interface)
        return interfaces

    @property
    def face_interfaces(self):
        """Get the face interfaces of the slab."""
        return [i for i in self._slab.interfaces if i.edge_index is None]

    @property
    def edge_perpendicular_vectors(self):
        """Returns the perpendicular vectors for the edges of the slab."""
        if not self._edge_perpendicular_vectors:
            self._edge_perpendicular_vectors = [get_polyline_segment_perpendicular_vector(self.outline_a, i) for i in range(self.edge_count)]
        return self._edge_perpendicular_vectors

    @property
    def interior_corner_indices(self):
        """Get the indices of the interior corners of the slab outline."""
        if not self._interior_corner_indices:
            """Get the indices of the interior corners of the slab outline."""
            points = self.outline_a.points[0:-1]
            cw = is_polyline_clockwise(self.outline_a, Vector(0, 0, 1))
            for i in range(len(points)):
                angle = angle_vectors_signed(points[i - 1] - points[i], points[(i + 1) % len(points)] - points[i], Vector(0, 0, 1), deg=True)
                if not (cw ^ (angle < 0)):
                    self._interior_corner_indices.append(i)
        return self._interior_corner_indices

    @property
    def interior_segment_indices(self):
        """Get the indices of the interior segments of the slab outline."""
        if not self._interior_corner_indices:
            for i in range(self.edge_count):
                if i in self.interior_corner_indices and (i + 1) % self.edge_count in self.interior_corner_indices:
                    yield i

    @property
    def obb(self):
        """Calculates the oriented bounding box (OBB) for the slab."""
        if not self._obb:
            self._obb = Box.from_points(self.outline_a.points + self.outline_b.points)
        return self._obb

    @property
    def length(self):
        """Returns the length of the slab populator along the X axis."""
        return self.obb.xsize

    @property
    def width(self):
        """Returns the width of the slab populator along the Y axis."""
        return self.obb.ysize

    def set_frame_outlines(self, parameters):
        """Handles the sheeting offsets for the slab outlines."""
        """This method creates new outlines for the beam frame based on the sheeting thicknesses."""
        if not parameters.plate_generator or not parameters.plate_generator.sheeting_inside:
            self.frame_outline_a = self.outline_a
        else:
            offset_inside = parameters.plate_generator.sheeting_inside / self.thickness
            pts_inside = []
            for pt_a, pt_b in zip(self.outline_a.points, self.outline_b.points):
                pt = pt_a * (1 - offset_inside) + pt_b * offset_inside
                pts_inside.append(pt)
            self.frame_outline_a = Polyline(pts_inside)

        if not parameters.plate_generator or not parameters.plate_generator.sheeting_outside:
            self.frame_outline_b = self.outline_b
        else:
            offset_outside = parameters.plate_generator.sheeting_outside / self.thickness
            pts_outside = []
            for pt_a, pt_b in zip(self.outline_a.points, self.outline_b.points):
                pts_outside.append(pt_a * offset_outside + pt_b * (1 - offset_outside))

            self.frame_outline_b = Polyline(pts_outside)

    def get_elements_by_category(self, category):
        return list(filter(lambda x: x.attributes.get("category", None) == category, self.elements))

    def process_populator(self):
        """Processes the slab populator and creates the elements and joints."""
        self.parameters.generate_elements(self)
        for f in self.feature_definitions:
            group = f.parameters.generate_elements(f.feature)
            self.element_groups.append(group)
        for g in self.element_groups[::-1]:
            rules = g.parameters.join_elements(self, g)
            self.direct_rules.extend(rules)

    @classmethod
    def from_model(cls, model, configuration_sets):
        # type: (TimberModel, List[WallPopulatorConfigurationSet]) -> List[WallPopulator]
        """matches configuration sets to walls and returns a list of SlabPopulator instances, each per wall"""
        # TODO: make sure number of walls and configuration sets match
        slabs = list(model.slabs)  # TODO: these are anoying, consider making these lists again
        if len(slabs) != len(configuration_sets):
            raise ValueError("Number of walls and configuration sets do not match")

        slab_populators = []
        for slab in slabs:
            for config_set in configuration_sets:
                if config_set.slab_selector.select(slab):
                    interfaces = [interaction.get_interface_for_slab(slab) for interaction in model.get_interactions_for_element(slab)]
                    slab_populators.append(cls(config_set, slab, interfaces))
                    break
        return slab_populators


class FeatureBoundaryType(object):
    """Defines the boundary type for a feature definition.
    Attributes
    ----------
    EXCLUSIVE : str
        The feature defines an exclusive boundary, i.e. an area where elements should not be placed.
    INCLUSIVE : str
        The feature defines an inclusive boundary, i.e. an area where elements are allowed.
    """

    EXCLUSIVE = "exclusive"
    INCLUSIVE = "inclusive"


class ElementGroup(object):
    """Defines a feature in the slab populator.

    Parameters
    ----------
    feature_type : str
        The type of the feature.
    parameters : dict
        The parameters for the feature.

    """

    def __init__(self, feature=None, parameters=None, elements=None, edges=None, edge_elements=None, outline=None, boundary_type=FeatureBoundaryType.EXCLUSIVE):
        self.feature = feature
        self.parameters = parameters
        self.elements = elements or []
        self.edges = edges or {}
        self.edge_elements = edge_elements or {}
        self.outline = outline
        self.boundary_type = boundary_type

    def generate_elements(self):
        """Generates the elements for the feature."""
        return self.parameters.generate_elements(self)

    def join_elements(self, slab_populator):
        """Joins the elements for the feature."""
        return self.parameters.join_elements(slab_populator, self)

    def cull_element_at_point(self, point, element=None):
        """Determines whether to keep a segment based on the boundary type."""

        if element:
            if self.parameters.cull_beam_segment(element, self):
                return True
        if not self.outline:
            return False
        return (self.boundary_type == FeatureBoundaryType.INCLUSIVE) ^ is_point_in_polyline(point, self.outline, in_plane=False)


    def __str__(self):
        return "ElementGroup({}, {}, {} elements)".format(self.feature.__class__.__name__, self.parameters.NAME, len(self.elements))

    def __repr__(self):
        return "ElementGroup({}, {}, {} elements)".format(self.feature.__class__.__name__, self.parameters.NAME, len(self.elements))
