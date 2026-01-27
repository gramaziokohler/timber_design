
from compas.geometry import Point, Polyline, Vector, Plane, Transformation

from timber_design.populators.generator_factories.stud_panel_generator_factory import (
    StudPanelGeneratorFactory,
    StudPanelGeneratorFactoryParams,
)
from timber_design.populators.generator_factories.recess_panel_generator_factory import (
    RecessPanelGeneratorFactory,
    RecessPanelGeneratorFactoryParams,
)
from timber_design.populators.generator_factories.panel_generator_factory import get_frame_panel
from timber_design.populators.element_generators.edge_element_generator import PanelEdgeElementGeneratorA
from timber_design.populators.element_generators.stud_element_generator import PanelStudElementGeneratorA


class SimplePanel:
    """A minimal stand-in for compas_timber.elements.Panel used by the tests.
    Provides the attributes required by the factories and generators.
    """

    def __init__(self, width=2.0, height=1.0, thickness=0.2):
        pts = [Point(0, 0, 0), Point(width, 0, 0), Point(width, height, 0), Point(0, height, 0), Point(0, 0, 0)]
        self.local_outlines = [Polyline(pts), Polyline(pts)]
        # used by get_transformation_to_populator_space
        self.transformation = Transformation()
        self.thickness = thickness
        self.features = []
        # outline_a / outline_b are used by get_frame_panel and generators
        self.outline_a = self.local_outlines[0]
        self.outline_b = self.local_outlines[1]
        # edge_planes expected to be a mapping from index to Plane
        # create simple horizontal planes for each edge
        self.edge_planes = {i: Plane(Point(0, 0, 0), Vector(0, 0, 1)) for i in range(len(self.outline_a.points) - 1)}


def test_stud_factory_create_generators_and_generate():
    panel = SimplePanel()
    params = StudPanelGeneratorFactoryParams(standard_beam_width=0.05, stud_spacing=0.5)
    generators = StudPanelGeneratorFactory.create_generators(panel, params, feature_generators=None)
    assert isinstance(generators, list)
    assert len(generators) > 0

    # call update_beam_dimensions and generate_elements for each generator to ensure they run without error
    for g in generators:
        # some generators expect an attribute 'panel' or similar; create generators already receive the panel
        if hasattr(g, "update_beam_dimensions"):
            g.update_beam_dimensions(panel.thickness)
        if hasattr(g, "generate_elements"):
            g.generate_elements()
        # elements should be a list attribute (may be empty depending on params)
        assert hasattr(g, "elements")


def test_recess_factory_create_generators_and_generate():
    panel = SimplePanel()
    params = RecessPanelGeneratorFactoryParams(standard_beam_width=0.05, recess_beam_width=0.03, recess_beam_height=0.02, edge_beam_min_width=0.03)
    generators = RecessPanelGeneratorFactory.create_generators(panel, params, feature_generators=None)
    assert isinstance(generators, list)
    assert len(generators) > 0

    for g in generators:
        if hasattr(g, "update_beam_dimensions"):
            # some generators may expose `resolve_beam_dimensions` or `update_beam_dimensions`; try both
            try:
                g.update_beam_dimensions(panel.thickness)
            except Exception:
                try:
                    g.resolve_beam_dimensions(panel.thickness)
                except Exception:
                    pass
        if hasattr(g, "generate_elements"):
            g.generate_elements()
        assert hasattr(g, "elements")


def test_edge_generator_creates_edge_beams():
    panel = SimplePanel(width=3.0, height=1.5)
    frame_panel = get_frame_panel(panel, type("P", (), {"sheeting_inside": 0, "sheeting_outside": 0, "thickness": panel.thickness}))
    gen = PanelEdgeElementGeneratorA(frame_panel, standard_beam_width=0.05)
    gen.update_beam_dimensions(frame_panel.thickness)
    gen.generate_elements()
    assert hasattr(gen, "elements")
    # edge generator should have produced at least one element
    assert len(gen.elements) > 0
    # check categories are assigned on edge elements
    cats = set(e.attributes.get("category") for e in gen.elements if hasattr(e, "attributes"))
    assert any(c is not None for c in cats)


def test_stud_generator_creates_studs():
    panel = SimplePanel(width=2.0, height=1.0)
    frame_panel = get_frame_panel(panel, type("P", (), {"sheeting_inside": 0, "sheeting_outside": 0, "thickness": panel.thickness}))
    gen = PanelStudElementGeneratorA(frame_panel, stud_spacing=0.4, standard_beam_width=0.05)
    gen.update_beam_dimensions(frame_panel.thickness)
    gen.generate_elements()
    assert hasattr(gen, "elements")
    # studs generator may create several studs depending on spacing
    assert isinstance(gen.elements, list)
