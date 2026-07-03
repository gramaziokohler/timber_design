"""A single JointRuleSolver applying both plain pairwise rules and a
CompositeJointRule at once.

Requires the `add_composite_joint` branch of compas_timber.

The model below has two unrelated groups of beams:

  * a plain 2-beam L corner -- an ordinary pairwise joint
  * a 3-beam K cluster (one spine, one crossing brace, one diagonal) --
    needs the CompositeJointRule from example 01 to join cleanly

Both groups are resolved by one `JointRuleSolver`, in one call. The
CompositeJointRule only ever matches clusters with >= 3 elements (its
default `min_element_count`), so it simply doesn't apply to the 2-beam
corner -- that one falls through to the plain `TopologyRule` instead.
"""

from compas.geometry import Line
from compas.geometry import Point
from compas.geometry import Translation
from compas_timber.connections import CompositeJoint
from compas_timber.connections import JointTopology
from compas_timber.connections import LButtJoint
from compas_timber.connections import TButtJoint
from compas_timber.elements import Beam
from compas_timber.model import TimberModel

from timber_design.workflow import CompositeJointRule
from timber_design.workflow import JointRuleSolver
from timber_design.workflow import TopologyRule


def beam(start, end, offset):
    line = Line(Point(*start), Point(*end)).transformed(Translation.from_vector(offset))
    return Beam.from_centerline(line, width=200, height=200)


# Group 1: an ordinary two-beam L corner, far away from the cluster below.
corner_a = beam((0, 0, 0), (1000, 0, 0), (0, 0, 0))
corner_b = beam((1000, 0, 0), (1000, 1000, 0), (0, 0, 0))

# Group 2: the same 3-beam K cluster from example 01, offset well clear of
# group 1 so the two don't get merged into one cluster by proximity.
cluster_offset = (10000, 0, 0)
spine = beam((0, 0, 0), (1000, 0, 0), cluster_offset)
brace = beam((0, -1000, 0), (0, 1000, 0), cluster_offset)
diagonal = beam((0, 0, 0), (-1000, -1000, 0), cluster_offset)

model = TimberModel()
model.add_elements([corner_a, corner_b, spine, brace, diagonal])

composite_rule = CompositeJointRule(
    [
        TopologyRule(JointTopology.TOPO_T, TButtJoint),
        TopologyRule(JointTopology.TOPO_L, LButtJoint),
    ],
    topo=JointTopology.TOPO_K,
)
plain_l_rule = TopologyRule(JointTopology.TOPO_L, LButtJoint)

solver = JointRuleSolver([composite_rule, plain_l_rule])
model.connect_adjacent_beams(max_distance=5.0)
errors, unjoined = solver.apply_rules_to_model(model)

print("joining errors:", errors)
print("unjoined clusters:", len(unjoined))
print()
for joint in model.joints:
    if isinstance(joint, CompositeJoint):
        print("CompositeJoint with sub-joints:", [type(sub).__name__ for sub in joint.joints])
    else:
        print(type(joint).__name__, "(plain pairwise joint)")

print()
print("The 2-beam corner never reaches the CompositeJointRule at all -- its")
print("cluster only has 2 elements, below the rule's min_element_count=3, so")
print("`try_create_joint` bails out immediately and the plain TopologyRule")
print("further down the rule list picks it up instead. The 3-beam K cluster")
print("does clear that bar and gets bundled into one CompositeJoint. Both")
print("outcomes come from the same solver.rules list and the same call to")
print("`apply_rules_to_model` -- no special-casing needed by the caller.")
