from typing import Optional

from compas.geometry import Box
from compas.geometry import Frame
from compas.geometry import Point
from compas.geometry import Polyline
from compas.geometry import Transformation
from compas.geometry import Vector
from compas.geometry import Line
from compas.geometry import angle_vectors
from compas.geometry import angle_vectors_signed
from compas.geometry import bounding_box_xy
from compas.geometry import cross_vectors
from compas_model.elements import Element

from compas_timber.elements import Opening
from compas_timber.elements import SlabConnectionInterface
from compas_timber.elements import TimberElement
from compas_timber.elements import SlabFeature
from compas_timber.model import TimberModel
from compas_timber.utils import get_polyline_segment_perpendicular_vector
from compas_timber.utils import is_point_in_polyline
from compas_timber.utils import is_polyline_clockwise
from compas_timber.elements import Slab

from timber_design.populators import ElementGenerator
from timber_design.populators import GeneratorFactoryParams
from timber_design.populators import SlabGeneratorFactory
from timber_design.workflow import DirectRule



class FeatureDefinition(object):
    """Defines a feature in the slab populator.

    Parameters
    ----------
    feature : :class:`compas_timber.elements.SlabFeature`
        The geometry of the feature.
    element_generator : timber_design.element_generators.ElementGeneratorParameters
        The element_generator for the feature.

    """

    def __init__(self, feature, element_generator):
        self.feature = feature
        self.element_generator = element_generator


class SlabPopulator(object):
    """Create a timber assembly from a slab.    

    Parameters
    ----------
    slab : :class:`compas_timber.elements.Slab`
        The source slab to populate.
    params : :class:`timber_design.populators.GeneratorFactoryParams`
        Parameters used by the generator factory to create local data and generators.
    factory : :class:`timber_design.populators.SlabGeneratorFactory`
        Factory used to create element generators and localized slab data.
    feature_generators : list[:class:`timber_design.populators.ElementGenerator`] | None, optional
        Optional list of feature-specific element generators to include.

    Attributes
    ----------
    slab : :class:`compas_timber.elements.Slab`
        A localized copy or view of the input slab used by the generators.
    transformation_slab_to_populator : :class:`compas.geometry.Transformation`
        Transformation that brings slab local coordinates into the populator frame.
    element_generators : list[:class:`timber_design.populators.ElementGenerator`]
        The element generators responsible for creating elements for this slab.
    direct_rules : list[:class:`timber_design.workflow.DirectRule`]
        Joint/connection rules produced when generators are joined.
    model : :class:`compas_timber.model.TimberModel`
        The temporary timber model populated by the generators.

    """

    def __init__(self, slab: Slab, params: GeneratorFactoryParams, factory: SlabGeneratorFactory, feature_generators:list[ElementGenerator] | None=None)->None:
        super(SlabPopulator, self).__init__()
        self.original_slab: Slab = slab
        self._local_slab, self.transformation_slab_to_populator, feature_generators = factory.create_local_data(slab, params, feature_generators)
        self.element_generators = factory.create_generators(self.slab, params, feature_generators)
        self.element_generators.extend(feature_generators)
        self.direct_rules: list[DirectRule] = []
        self._model = TimberModel()

    def __repr__(self):
        return "SlabPopulator({})".format(self.slab)

    @property
    def slab(self):
        """The slab associated with this populator."""
        return self._local_slab

    def model(self):
        """The timber model created by this populator."""
        return self._model

    def process_populator(self):
        """Processes the slab populator and creates the elements and joints."""
        for g in self.element_generators:
            g.generate_elements()
        for g in self.element_generators:
            rules: list[DirectRule] = g.join_elements(self)
            self.direct_rules.extend(rules)

    def process_joinery(self):
        for element_generator in self.element_generators:
            for element in element_generator.elements:
                element.attributes.pop("joint_defs", None)
            self._model.add_elements(element_generator.elements)

        for j_def in self.direct_rules:
            if not j_def:
                continue
            for e in j_def.elements:
                if e not in self._model.elements():
                    raise ValueError("Element in joint definition not found in model: {}, x = {}".format(e.attributes.get("category", None), e.frame.point[0]))
            else:
                j_def.joint_type.create(self._model, *j_def.elements, **j_def.kwargs)
        self._model.process_joinery()

    def merge_with_model(self, model, clear_slab=False):
        """Merges the slab populator with a timber model."""
        if clear_slab:
            for element in self.original_slab.children:
                for joint in model.joints:
                    if element in joint.elements:
                        model.remove_joint(joint)
                model.remove_element(element)
        for element in self._model.elements():
            element.transform(self.transformation_slab_to_populator.inverse())
            model.add_element(element, parent=self.original_slab)
        for j in self._model.joints:
            model.add_joint(j)



