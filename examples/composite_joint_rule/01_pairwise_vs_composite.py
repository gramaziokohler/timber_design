"""Pairwise JointRules vs. CompositeJointRule on a single 3-beam cluster.

Requires the `add_composite_joint` branch of compas_timber (CompositeJoint /
YButtJoint are not yet on main).

A "K" cluster: one continuous spine beam crossed by a brace (T), plus a third
beam meeting both the spine and the brace at their ends (L). All three
pairwise relationships live at (roughly) the same point, so the connection
solver groups them into a single 3-element cluster instead of three
independent 2-beam joints.
"""

from compas.geometry import Line
from compas.geometry import Point
from compas_timber.connections import CompositeJoint
from compas_timber.connections import JointTopology
from compas_timber.connections import LButtJoint
from compas_timber.connections import TButtJoint
from compas_timber.elements import Beam
from compas_timber.model import TimberModel

from timber_design.workflow import CompositeJointRule
from timber_design.workflow import JointRuleSolver
from timber_design.workflow import TopologyRule


def build_beams():
    w = h = 200
    spine = Beam.from_centerline(Line(Point(0, 0, 0), Point(1000, 0, 0)), w, h)
    brace = Beam.from_centerline(Line(Point(0, -1000, 0), Point(0, 1000, 0)), w, h)
    diagonal = Beam.from_centerline(Line(Point(0, 0, 0), Point(-1000, -1000, 0)), w, h)
    return spine, brace, diagonal


print("=" * 70)
print("PART A -- pairwise rules only, covering just the T-topology pair")
print("=" * 70)

spine, brace, diagonal = build_beams()
model = TimberModel()
model.add_elements([spine, brace, diagonal])

# A rule set that looks reasonable in isolation: "T-joints get a TButtJoint".
# It says nothing about the L-topology pair (spine <-> diagonal), which also
# exists in this cluster.
rule = TopologyRule(JointTopology.TOPO_T, TButtJoint)
solver = JointRuleSolver([rule])
model.connect_adjacent_beams(max_distance=5.0)
errors, unjoined = solver.apply_rules_to_model(model)

print("joining errors:", errors)
print("unjoined clusters left over:", len(unjoined))
for cluster in unjoined:
    print("  -> {} elements never got a joint".format(len(cluster.elements)))
print("joints actually created:", [type(j).__name__ for j in model.joints])
print()
print("Only the two T-pairs got resolved. The solver's fallback splits any")
print("cluster that a rule can't match as a whole into independent pairwise")
print("sub-clusters and matches each one on its own -- so the spine/diagonal")
print("L-pair, which no rule covers, is silently left unjoined. The model")
print("reports it (in `unjoined`), but nothing connects those two beams.")

print()
print("=" * 70)
print("PART B -- same cluster, joined with a CompositeJointRule")
print("=" * 70)

spine, brace, diagonal = build_beams()
model = TimberModel()
model.add_elements([spine, brace, diagonal])

# The composite rule matches the WHOLE 3-element cluster at once (topo=TOPO_K)
# and requires every pairwise relationship inside it to resolve via one of
# its own sub-rules. Miss one, and the whole composite match fails instead of
# silently leaving a gap.
composite_rule = CompositeJointRule(
    [
        TopologyRule(JointTopology.TOPO_T, TButtJoint),
        TopologyRule(JointTopology.TOPO_L, LButtJoint),
    ],
    topo=JointTopology.TOPO_K,
)
solver = JointRuleSolver([composite_rule])
model.connect_adjacent_beams(max_distance=5.0)
errors, unjoined = solver.apply_rules_to_model(model)

print("joining errors:", errors)
print("unjoined clusters left over:", len(unjoined))
joint = list(model.joints)[0]
print("joint created:", joint)
print("  sub-joints:", [type(sub).__name__ for sub in joint.joints])
print()
print("All three pairwise relationships (T, T, L) were matched together and")
print("bundled into a single CompositeJoint. Nothing is silently skipped:")
print("if any pair had been left uncovered by the sub-rules, the whole")
print("composite match would have failed and the cluster would show up in")
print("`unjoined` as a single 3-element group -- easy to spot, unlike a")
print("quietly missing pairwise joint.")
