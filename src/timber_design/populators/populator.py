try:
    from typing import TYPE_CHECKING
    from typing import Optional

    if TYPE_CHECKING:
        from compas_timber.panel_features import PanelFeature

        from timber_design.populators import ElementGeneratorParams
        from timber_design.populators import GeneratorFactoryParams
        from timber_design.populators import PanelGeneratorFactory
        from timber_design.workflow import DirectRule
except ImportError:
    pass
from compas.geometry import Box
from compas.geometry import Frame
from compas.geometry import Point
from compas.geometry import Transformation
from compas.geometry import Translation
from compas.geometry import Vector
from compas.geometry import cross_vectors
from compas.tolerance import TOL
from compas_timber.elements import Panel
from timber_design.populators.model2d import ConnectionSolver2D
from timber_design.populators.model2d import Model2D
from compas_timber.panel_features import PanelFeature


class FeaturePopulatorDefinition(object):
    """Defines a feature in the panel populator.

    Parameters
    ----------
    feature : :class:`compas_timber.elements.PanelFeature`
        The geometry of the feature.
    element_generator : timber_design.element_generators.ElementGeneratorParameters
        The element_generator for the feature.

    """

    def __init__(self, feature: PanelFeature, params: "ElementGeneratorParams", generator_type):
        self.feature = feature
        self.params = params
        self.generator_type = generator_type


class PanelPopulatorDefinition(object):
    """Defines a feature in the panel populator.

    Parameters
    ----------
    feature : :class:`compas_timber.elements.PanelFeature`
        The geometry of the feature.
    element_generator : timber_design.element_generators.ElementGeneratorParameters
        The element_generator for the feature.

    """

    def __init__(self, panel: "Panel", params: "GeneratorFactoryParams", factory: "PanelGeneratorFactory", orientation: Optional[Vector] = None):
        self.panel = panel
        self.params = params
        self.factory = factory
        self.orientation = self.get_projected_vector(orientation)

    def get_projected_vector(self, orientation: Optional[Vector] = None) -> Vector:
        if not orientation:
            return Vector(0, 1, 0)
        perp = cross_vectors(self.panel.normal, orientation)
        if all(TOL.is_zero(perp[i]) for i in range(3)):
            return Vector(0, 1, 0)
        return Vector(*cross_vectors(perp, self.panel.normal)).transformed(self.panel.transformation_to_local())


class PanelPopulator(object):
    """Create a timber assembly from a panel.

    Parameters
    ----------
    panel : :class:`compas_timber.elements.Panel`
        The source panel to populate.
    params : :class:`timber_design.populators.GeneratorFactoryParams`
        Parameters used by the generator factory to create local data and generators.
    factory : :class:`timber_design.populators.PanelGeneratorFactory`
        Factory used to create element generators and localized panel data.
    feature_generators : list[:class:`timber_design.populators.ElementGenerator`] | None, optional
        Optional list of feature-specific element generators to include.

    Attributes
    ----------
    panel : :class:`compas_timber.elements.Panel`
        A localized copy or view of the input panel used by the generators.
    transformation_panel_to_populator : :class:`compas.geometry.Transformation`
        Transformation that brings panel local coordinates into the populator frame.
    element_generators : list[:class:`timber_design.populators.ElementGenerator`]
        The element generators responsible for creating elements for this panel.
    joint_defs : list[:class:`timber_design.workflow.DirectRule`]
        Joint/connection rules produced when generators are joined.
    model : :class:`~timber_design.populators.Model2D`
        The temporary timber model populated by the generators.

    """

    def __init__(self, panel_definition: PanelPopulatorDefinition, feature_definitions: Optional[list[FeaturePopulatorDefinition]] = None):
        super(PanelPopulator, self).__init__()
        self.original_panel: Panel = panel_definition.panel

        self.transformation_to_populator, self.panel = PanelPopulator.create_local_panel(panel_definition)
        self.element_generators = panel_definition.factory.create_generators(self.panel, panel_definition.params)

        for feature_def in feature_definitions or []:
            feature_def.feature = feature_def.feature.transformed(self.transformation_to_populator)
            self.element_generators.append(feature_def.generator_type(feature_def.feature, **feature_def.params.__data__))
        self.joint_defs: list[DirectRule] = []
        self.model = Model2D()

    def __repr__(self):
        return "PanelPopulator({})".format(self.panel)

    def process_populator(self):
        """Processes the panel populator and creates the elements and joints."""
        for g in self.element_generators:
            g.generate_elements()
        for g in self.element_generators:
            rules: list[DirectRule] = g.join_elements(self.joint_defs, self.element_generators)
            self.joint_defs.extend(rules)

    def connect_overlapping_generators(self):
        """Populate joint candidates in the model using 2D blank-outline containment.

        Iterates over all pairs of :attr:`element_generators` whose element
        AABBs overlap and tests every cross-generator beam pair for a 2D
        blank-outline intersection.  Detected candidates are added to
        :attr:`model` via :meth:`~timber_design.populators.Model2D.add_joint_candidate`.

        Clears any existing joint candidates before re-populating, so this
        method is safe to call multiple times.
        """
        for candidate in list(self.model.joint_candidates):
            self.model.remove_joint_candidate(candidate)

        solver = ConnectionSolver2D()
        for gen_a, gen_b in solver.find_intersecting_generator_pairs(self.element_generators):
            for beam_a in gen_a.elements:
                for beam_b in gen_b.elements:
                    candidate = solver.find_topology(beam_a, beam_b)
                    if candidate is not None:
                        self.model.add_joint_candidate(candidate)

    def process_joinery(self):
        for element_generator in self.element_generators:
            for element in element_generator.elements:
                element.attributes.pop("joint_defs", None)
                if element in list(self.model.elements()):
                    print(f"Element already in model: {element.attributes.get('category', None)}")
                    break
                self.model.add_elements(element_generator.elements)

        for j_def in self.joint_defs:
            if not j_def:
                continue
            for e in j_def.elements:
                if e not in self.model.elements():
                    raise ValueError("Element in joint definition not found in model: {}, x = {}".format(e.attributes.get("category", None), e.frame.point[0]))
            else:
                j_def.joint_type.create(self.model, *j_def.elements, **j_def.kwargs)
        self.model.process_joinery()

    def merge_with_model(self, model, clear_panel=False):
        """Merges the panel populator with a timber model."""
        if clear_panel:
            for element in self.original_panel.children:
                for joint in model.joints:
                    if element in joint.elements:
                        model.remove_joint(joint)
                model.remove_element(element)
        for element in self.model.elements():
            element.transform(self.transformation_to_populator.inverse())
            model.add_element(element, parent=self.original_panel)
        for j in self.model.joints:
            model.add_joint(j)

    @classmethod
    def create_local_panel(cls, panel_definition: PanelPopulatorDefinition) -> tuple[Transformation, Panel]:
        """Create a local panel for the generator.
        Parameters
        ----------
        panel : :class:`compas_timber.elements.Panel`
            The panel to be populated.
        params : :class:`timber_design.populators.GeneratorFactoryParams`
                Keyword arguments for the generator.
        feature_generators : list[:class:`timber_design.populators.ElementGenerator`], optional
            A list of feature generators to consider when populating the panel.
        Returns
        -------
        tuple[:class:`compas_timber.elements.Panel`, :class:`compas.geometry.Transformation`, list[:class:`timber_design.populators.ElementGenerator`]]
            The local panel, the transformation to the populator space, and the updated feature generators.
        """
        transformation_to_populator = _get_transformation_to_populator_space(panel_definition)
        polylines = panel_definition.panel.plate_geometry.outline_a, panel_definition.panel.plate_geometry.outline_b
        local_polylines = [pl.transformed(transformation_to_populator) for pl in polylines]
        box = Box.from_points([pt for pl in local_polylines for pt in pl.points])
        local_panel = Panel(Frame.worldXY(), box.xsize, box.ysize, box.zsize, local_polylines[0], local_polylines[1])

        return transformation_to_populator, local_panel


def _get_transformation_to_populator_space(panel_definition: PanelPopulatorDefinition) -> Transformation:
    """The Transformation from panel space to slab populator space."""
    transformation_to_populator_panel = _get_transformation_to_populator_panel(panel_definition.panel, panel_definition.orientation)
    translation_to_frame_center = _get_translation_to_frame_center(panel_definition.panel, panel_definition.params)
    return translation_to_frame_center * transformation_to_populator_panel


def _get_transformation_to_populator_panel(panel: Panel, stud_direction: Vector) -> Transformation:
    stud_dir_frame = Frame(Point(0, 0, 0), cross_vectors(stud_direction, Vector(0, 0, 1)), stud_direction)  # get frame with stud direction as y axis
    transform_to_stud_dir_frame = Transformation.from_frame(stud_dir_frame).inverse()
    pts = [pt.transformed(transform_to_stud_dir_frame) for pt in panel.plate_geometry.outline_a.points + panel.plate_geometry.outline_b.points]
    min_pt = Box.from_points(pts).points[0]
    obb_frame = Frame(min_pt, Vector(1, 0, 0), Vector(0, 1, 0)).transformed(transform_to_stud_dir_frame.inverse())
    return Transformation.from_frame(obb_frame).inverse()


def _get_translation_to_frame_center(panel: Panel, params: "GeneratorFactoryParams") -> Translation:
    si = getattr(params, "sheeting_inside", 0) or 0.0
    so = getattr(params, "sheeting_outside", 0) or 0.0
    frame_thickness = panel.thickness - si - so
    return Translation.from_vector(-Vector(0, 0, si + frame_thickness / 2))
