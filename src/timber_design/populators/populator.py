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

from itertools import product

from compas.geometry import Vector
from compas.geometry import cross_vectors
from compas.tolerance import TOL
from compas_timber.elements import Panel
from compas_timber.connections import JointCandidate
from compas_timber.model import TimberModel
from compas_timber.panel_features import PanelFeature
from timber_design.populators.connection_solver_2d import ConnectionSolver2D
from timber_design.workflow import JointRuleSolver
from compas_timber.connections import get_clusters_from_joint_candidates



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

        self.transformation_to_populator, self.panel = panel_definition.factory.create_local_panel(panel_definition)

        transformed_feature_defs = [
            FeaturePopulatorDefinition(
                feature_def.feature.transformed(self.transformation_to_populator),
                feature_def.params,
                feature_def.generator_type,
            )
            for feature_def in (feature_definitions or [])
        ]

        self.element_generators = panel_definition.factory.create_generators(
            self.panel, panel_definition.params, transformed_feature_defs
        )

        self.model = TimberModel()
        self.test = []

    def __repr__(self):
        return "PanelPopulator({})".format(self.panel)

    def populate_elements(self):
        """Runs the full population process, including generating elements, trimming, joining, and processing joinery."""
        self.generate_elements()
        self.extend_elements()
        self.trim_elements()
        self.add_elements_to_model()

    def generate_elements(self):
        for g in self.element_generators:
            g.generate_elements()

    def extend_elements(self):
        for g in self.element_generators:
            g.extend_elements(self.element_generators)

    def trim_elements(self):
        solver = ConnectionSolver2D()
        for gen_a, gen_b in solver.find_intersecting_generator_pairs(self.element_generators):
            gen_a.trim_elements_with_generator(gen_b)
            gen_b.trim_elements_with_generator(gen_a)

    def add_elements_to_model(self):
        for gen in self.element_generators:
            for element in gen.elements:
                self.model.add_element(element)

    def join_elements(self):
        self.create_generator_joints()
        self.create_cross_generator_joints()
        #TODO: handle clusters

    def create_generator_joints(self):
        for gen in self.element_generators:
            gen.create_internal_joint_defs(self.model)
            for j_def in gen.joint_defs:
                j_def.joint_type.create(self.model, *j_def.elements, **j_def.kwargs)

    def create_cross_generator_joints(self):
        solver = ConnectionSolver2D()
        for gen_a, gen_b in solver.find_intersecting_generator_pairs(self.element_generators):
            candidates = []
            for element_a, element_b in product(gen_a.elements, gen_b.elements):
                topo_result = solver.find_topology(element_a, element_b)
                if topo_result is not None:
                    candidate = JointCandidate(topo_result.beam_a, topo_result.beam_b, distance = topo_result.distance, topology = topo_result.topology, location = topo_result.location)
                    self.model.add_joint_candidate(candidate)
                    candidates.append(candidate)
            clusters = get_clusters_from_joint_candidates(candidates, max_distance=0.001)
            jrs = JointRuleSolver(gen_a.rules + gen_b.rules)
            jrs.joints_from_rules_and_clusters(self.model, clusters=clusters)

    def process_joinery(self):
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



