"""Multiple CompositeJointRules routing clusters by topology and element count.

Requires the `add_composite_joint` branch of compas_timber.

Four independent beam groups, each shaped differently:

  A. a plain 2-beam L corner
  B. a 3-beam "Y" cluster -- three beams meeting end-to-end at one point
  C. a 3-beam "K" cluster -- one spine, one crossing brace, one diagonal
  D. a 4-beam "K" cluster -- one spine crossed by three separate braces

Three CompositeJointRules and one plain TopologyRule are handed to a single
JointRuleSolver. Each CompositeJointRule's `topo` and `min_element_count` /
`max_element_count` act as a filter: a rule only even attempts a cluster
that matches its shape and size, so the solver ends up routing each group
to the rule meant for it.
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


# --- Group A: a plain 2-beam L corner -----------------------------------
off_a = (0, 0, 0)
a1 = beam((0, 0, 0), (1000, 0, 0), off_a)
a2 = beam((1000, 0, 0), (1000, 1000, 0), off_a)

# --- Group B: a 3-beam Y cluster (all ends meet at one point) ----------
off_b = (10000, 0, 0)
b1 = beam((0, 0, 0), (1000, 0, 0), off_b)
b2 = beam((0, 0, 0), (0, 1000, 0), off_b)
b3 = beam((0, 0, 0), (-1000, -1000, 0), off_b)

# --- Group C: a 3-beam K cluster (spine + brace + diagonal) -------------
off_c = (20000, 0, 0)
c_spine = beam((0, 0, 0), (1000, 0, 0), off_c)
c_brace = beam((0, -1000, 0), (0, 1000, 0), off_c)
c_diagonal = beam((0, 0, 0), (-1000, -1000, 0), off_c)

# --- Group D: a 4-beam K cluster (spine + three braces) -----------------
off_d = (30000, 0, 0)
d_spine = beam((-1500, 0, 0), (1500, 0, 0), off_d)
d_brace_1 = beam((-300, 0, 0), (-800, 900, 500), off_d)
d_brace_2 = beam((0, 0, 0), (0, -900, 500), off_d)
d_brace_3 = beam((300, 0, 0), (800, 900, 500), off_d)

model = TimberModel()
model.add_elements([a1, a2, b1, b2, b3, c_spine, c_brace, c_diagonal, d_spine, d_brace_1, d_brace_2, d_brace_3])

# One CJR per cluster "shape", filtered by topo + element count.
cjr_y = CompositeJointRule(
    [TopologyRule(JointTopology.TOPO_L, LButtJoint)],
    topo=JointTopology.TOPO_Y,
    max_element_count=3,
)
cjr_k_small = CompositeJointRule(
    [
        TopologyRule(JointTopology.TOPO_T, TButtJoint),
        TopologyRule(JointTopology.TOPO_L, LButtJoint),
    ],
    topo=JointTopology.TOPO_K,
    max_element_count=3,
)
cjr_k_large = CompositeJointRule(
    [TopologyRule(JointTopology.TOPO_T, TButtJoint)],
    topo=JointTopology.TOPO_K,
    min_element_count=4,
)
fallback = TopologyRule(JointTopology.TOPO_L, LButtJoint)

# Contact detection uses a tight tolerance (beams only "touch" when they
# actually meet); the solver's own max_distance is looser, purely so that
# candidates a few hundred mm apart along the same spine still cluster
# together as one group.
solver = JointRuleSolver([cjr_y, cjr_k_small, cjr_k_large, fallback], max_distance=350.0)
model.connect_adjacent_beams(max_distance=5.0)
errors, unjoined = solver.apply_rules_to_model(model)

print("joining errors:", errors)
print("unjoined clusters:", len(unjoined))
print()

groups = {"A (2-beam L)": (a1, a2), "B (3-beam Y)": (b1, b2, b3), "C (3-beam K)": (c_spine, c_brace, c_diagonal), "D (4-beam K)": (d_spine, d_brace_1, d_brace_2, d_brace_3)}
for label, group_beams in groups.items():
    group_beams = set(group_beams)
    matches = [j for j in model.joints if group_beams.issubset(set(j.elements))]
    for joint in matches:
        if isinstance(joint, CompositeJoint):
            print("{}: CompositeJoint -> {}".format(label, [type(sub).__name__ for sub in joint.joints]))
        else:
            print("{}: {}".format(label, type(joint).__name__))

print()
print("Each CompositeJointRule only *attempts* clusters matching its own")
print("topo / element-count filter, so:")
print("  - group A (2 elements)         -> below every CJR's min_element_count, falls to the plain TopologyRule")
print("  - group B (3 elements, Y)      -> matched by cjr_y")
print("  - group C (3 elements, K)      -> matched by cjr_k_small (cjr_k_large's min_element_count=4 excludes it)")
print("  - group D (4 elements, K)      -> too big for cjr_k_small's max_element_count=3, matched by cjr_k_large instead")
