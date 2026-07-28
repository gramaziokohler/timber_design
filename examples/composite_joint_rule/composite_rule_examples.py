from compas.geometry import Line, Point

from compas_timber.elements import Beam
from compas_timber.model import TimberModel
from compas_timber.connections import LButtJoint, LMiterJoint, TButtJoint, JointTopology, JointCandidate
from timber_design.workflow import DirectRule, CategoryRule, TopologyRule, CompositeRule, JointRuleSolver

edge_beams = [
    Beam.from_centerline(Line(Point(0, 0, 0), Point(1000, 1000, 0)), 100, 100, category = "edge"),
    Beam.from_centerline(Line(Point(0, 0, 0), Point(-1000, 0, 0)), 100, 100, category = "edge"),
    Beam.from_centerline(Line(Point(1000, 1000, 0), Point(0, 1000, 0)), 100, 100, category = "edge"),
    Beam.from_centerline(Line(Point(0, 1000, 0), Point(-1000, 0, 0)), 100, 100, category = "edge"),    ]

butt_beams = [
    Beam.from_centerline(Line(Point(0, 0, 0), Point(0, 1000, 0)), 100, 100, category = "butt"),
    Beam.from_centerline(Line(Point(-500, 0, 0), Point(-500, 500, 0)), 100, 100, category = "butt"),
    Beam.from_centerline(Line(Point(0, 0, 0), Point(1000, -1000, 0)), 100, 100, category = "edge"),
    ]

model = TimberModel()
for element in edge_beams + butt_beams:
    model.add_element(element)

model.connect_adjacent_beams()

pairwise_rules = [
    TopologyRule(JointTopology.TOPO_T, TButtJoint, mill_depth=10),
    CategoryRule(LButtJoint, "edge", "edge"),
    CategoryRule(LButtJoint, "butt", "edge", mill_depth=10, modify_cross=False),
]


composite_rules = [
    CompositeRule([
        CategoryRule(LButtJoint, "edge", "edge", mill_depth=10),
        CategoryRule(LButtJoint, "butt", "edge", mill_depth=10, modify_cross=False),
    ], max_element_count=3),
    CompositeRule([
        TopologyRule(JointTopology.TOPO_L, LMiterJoint)
    ], min_element_count=4)
]

use_composite = True
if use_composite:
    jrs = JointRuleSolver(pairwise_rules+composite_rules)
else:
    jrs = JointRuleSolver(pairwise_rules)



jrs.apply_rules_to_model(model)

model.process_joinery()

a=model