
try:
    from typing import TYPE_CHECKING
    from typing import Optional

    if TYPE_CHECKING:
        from compas_timber.elements import Panel

        from timber_design.populators import ElementGenerator
        from timber_design.populators import GeneratorFactoryParams
        from timber_design.populators import PanelGeneratorFactory
        from timber_design.workflow import DirectRule
except ImportError:
    pass

from compas_timber.model import TimberModel


class FeatureDefinition(object):
    """Defines a feature in the panel populator.

    Parameters
    ----------
    feature : :class:`compas_timber.elements.PanelFeature`
        The geometry of the feature.
    element_generator : timber_design.element_generators.ElementGeneratorParameters
        The element_generator for the feature.

    """

    def __init__(self, feature, element_generator):
        self.feature = feature
        self.element_generator = element_generator


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
    direct_rules : list[:class:`timber_design.workflow.DirectRule`]
        Joint/connection rules produced when generators are joined.
    model : :class:`compas_timber.model.TimberModel`
        The temporary timber model populated by the generators.

    """

    def __init__(self, panel, params, factory, feature_generators=None):
        # type: (Panel, GeneratorFactoryParams, PanelGeneratorFactory, Optional[list[tuple(PanelFeature, )]]) -> None
        super(PanelPopulator, self).__init__()
        self.original_panel: Panel = panel
        self._local_panel, self.transformation_panel_to_populator, feature_generators = factory.create_local_data(panel, params, feature_generators)
        self.element_generators = factory.create_generators(self.panel, params, feature_generators)
        self.element_generators.extend(feature_generators)
        self.direct_rules: list[DirectRule] = []
        self._model = TimberModel()

    def __repr__(self):
        return "PanelPopulator({})".format(self.panel)

    @property
    def panel(self):
        """The panel associated with this populator."""
        return self._local_panel

    def model(self):
        """The timber model created by this populator."""
        return self._model

    def process_populator(self):
        """Processes the panel populator and creates the elements and joints."""
        for g in self.element_generators:
            g.generate_elements()
        for g in self.element_generators:
            rules: list[DirectRule] = g.join_elements(self.direct_rules, self.element_generators)
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

    def merge_with_model(self, model, clear_panel=False):
        """Merges the panel populator with a timber model."""
        if clear_panel:
            for element in self.original_panel.children:
                for joint in model.joints:
                    if element in joint.elements:
                        model.remove_joint(joint)
                model.remove_element(element)
        for element in self._model.elements():
            element.transform(self.transformation_panel_to_populator.inverse())
            model.add_element(element, parent=self.original_panel)
        for j in self._model.joints:
            model.add_joint(j)
