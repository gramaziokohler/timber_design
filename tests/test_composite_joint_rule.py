import pytest
from compas.geometry import Line
from compas.geometry import Point

from compas_timber.connections import JointTopology
from compas_timber.connections import LButtJoint
from compas_timber.connections import LMiterJoint
from compas_timber.connections import TButtJoint
from compas_timber.connections import CompositeJoint
from compas_timber.elements import Beam
from compas_timber.model import TimberModel

from timber_design.workflow import CompositeJointRule
from timber_design.workflow import DirectRule
from timber_design.workflow import JointRuleSolver
from timber_design.workflow import TopologyRule


@pytest.fixture
def Y_beams():
    """Three beams meeting at the origin — forms a single TOPO_Y cluster with 3 L-type candidates."""
    w = 0.2
    h = 0.2
    lines = [
        Line(Point(0, 0, 0), Point(1, 0, 0)),
        Line(Point(0, 0, 0), Point(0, 1, 0)),
        Line(Point(0, 0, 0), Point(-1, -1, 0)),
    ]
    return [Beam.from_centerline(line, w, h) for line in lines]


@pytest.fixture
def K_beams():
    """Three beams in a K topology — one T and two L candidates."""
    w = 0.2
    h = 0.2
    lines = [
        Line(Point(0, 0, 0), Point(1, 0, 0)),
        Line(Point(0, -1, 0), Point(0, 1, 0)),
        Line(Point(0, 0, 0), Point(-1, -1, 0)),
    ]
    return [Beam.from_centerline(line, w, h) for line in lines]


@pytest.fixture
def L_beams():
    """Two beams in an L topology — only 2 elements, too few for CompositeJointRule default."""
    w = 0.2
    h = 0.2
    lines = [
        Line(Point(0, 0, 0), Point(1, 0, 0)),
        Line(Point(1, 0, 0), Point(1, 1, 0)),
    ]
    return [Beam.from_centerline(line, w, h) for line in lines]


def _make_model_with_clusters(beams):
    model = TimberModel()
    model.add_elements(beams)
    model.connect_adjacent_beams()
    return model


# ---------------------------------------------------------------------------
# Constructor / repr
# ---------------------------------------------------------------------------


def test_composite_joint_rule_repr():
    rule = CompositeJointRule([TopologyRule(JointTopology.TOPO_L, LButtJoint)])
    assert "CompositeJointRule" in repr(rule)
    assert "1" in repr(rule)


def test_composite_joint_rule_repr_no_rules():
    rule = CompositeJointRule([])
    assert "0" in repr(rule)


# ---------------------------------------------------------------------------
# try_create_joint — element count guards
# ---------------------------------------------------------------------------


def test_too_few_elements_returns_none(L_beams):
    """A 2-element cluster is below the default min_element_count=3; rule must pass."""
    rule = CompositeJointRule([TopologyRule(JointTopology.TOPO_L, LButtJoint)])
    model = _make_model_with_clusters(L_beams)
    from timber_design.workflow import get_clusters_from_model

    clusters = get_clusters_from_model(model)
    assert len(clusters) == 1
    joint, error = rule.try_create_joint(model, clusters[0])
    assert joint is None
    assert error is None


def test_min_element_count_override(Y_beams):
    """min_element_count=4 should block a 3-element Y cluster."""
    rule = CompositeJointRule([TopologyRule(JointTopology.TOPO_L, LButtJoint)], min_element_count=4)
    model = _make_model_with_clusters(Y_beams)
    from timber_design.workflow import get_clusters_from_model

    clusters = get_clusters_from_model(model)
    assert len(clusters) == 1
    joint, error = rule.try_create_joint(model, clusters[0])
    assert joint is None
    assert error is None


def test_max_element_count_rejects_large_cluster(Y_beams):
    """A cluster with 3 elements must be rejected when max_element_count=2."""
    rule = CompositeJointRule([TopologyRule(JointTopology.TOPO_L, LButtJoint)], max_element_count=2)
    model = _make_model_with_clusters(Y_beams)
    from timber_design.workflow import get_clusters_from_model

    clusters = get_clusters_from_model(model)
    assert len(clusters) == 1
    joint, error = rule.try_create_joint(model, clusters[0])
    assert joint is None
    assert error is None


# ---------------------------------------------------------------------------
# try_create_joint — topology filter
# ---------------------------------------------------------------------------


def test_topo_filter_mismatch_returns_none(Y_beams):
    """When topo is set and the cluster topology doesn't match, the rule must skip."""
    rule = CompositeJointRule([TopologyRule(JointTopology.TOPO_L, LButtJoint)], topo=JointTopology.TOPO_T)
    model = _make_model_with_clusters(Y_beams)
    from timber_design.workflow import get_clusters_from_model

    clusters = get_clusters_from_model(model)
    assert len(clusters) == 1
    joint, error = rule.try_create_joint(model, clusters[0])
    assert joint is None
    assert error is None


def test_topo_filter_match_succeeds(Y_beams):
    """topo=TOPO_Y should match the Y cluster and produce a CompositeJoint."""
    rule = CompositeJointRule([TopologyRule(JointTopology.TOPO_L, LButtJoint)], topo=JointTopology.TOPO_Y)
    model = _make_model_with_clusters(Y_beams)
    from timber_design.workflow import get_clusters_from_model

    clusters = get_clusters_from_model(model)
    assert len(clusters) == 1
    joint, error = rule.try_create_joint(model, clusters[0])
    assert isinstance(joint, CompositeJoint)
    assert error is None


# ---------------------------------------------------------------------------
# try_create_joint — successful composite creation
# ---------------------------------------------------------------------------


def test_composite_joint_created_for_y_cluster(Y_beams):
    """All three L-pairs in a Y cluster should be matched and bundled into a CompositeJoint."""
    rule = CompositeJointRule([TopologyRule(JointTopology.TOPO_L, LButtJoint)])
    model = _make_model_with_clusters(Y_beams)
    from timber_design.workflow import get_clusters_from_model

    clusters = get_clusters_from_model(model)
    assert len(clusters) == 1

    joint, error = rule.try_create_joint(model, clusters[0])
    assert isinstance(joint, CompositeJoint)
    assert error is None
    assert len(joint.joints) == 3
    assert all(isinstance(j, LButtJoint) for j in joint.joints)


def test_composite_joint_registered_in_model(Y_beams):
    """try_create_joint must register the CompositeJoint in the model."""
    rule = CompositeJointRule([TopologyRule(JointTopology.TOPO_L, LButtJoint)])
    model = _make_model_with_clusters(Y_beams)
    from timber_design.workflow import get_clusters_from_model

    clusters = get_clusters_from_model(model)
    joint, _ = rule.try_create_joint(model, clusters[0])
    assert joint in list(model.joints)


def test_composite_joint_elements_cover_all_beams(Y_beams):
    """The CompositeJoint's elements should include all three beams in the cluster."""
    rule = CompositeJointRule([TopologyRule(JointTopology.TOPO_L, LButtJoint)])
    model = _make_model_with_clusters(Y_beams)
    from timber_design.workflow import get_clusters_from_model

    clusters = get_clusters_from_model(model)
    joint, _ = rule.try_create_joint(model, clusters[0])
    assert set(joint.elements) == set(Y_beams)


# ---------------------------------------------------------------------------
# try_create_joint — partial match
# ---------------------------------------------------------------------------


def test_partial_match_returns_none(K_beams):
    """If not all pairwise candidates can be matched, the rule must return (None, None)."""
    # K cluster has both L and T candidates; TopologyRule(TOPO_L) won't match the T pair
    rule = CompositeJointRule([TopologyRule(JointTopology.TOPO_L, LButtJoint)])
    model = _make_model_with_clusters(K_beams)
    from timber_design.workflow import get_clusters_from_model

    clusters = get_clusters_from_model(model)
    assert len(clusters) == 1
    joint, error = rule.try_create_joint(model, clusters[0])
    assert joint is None
    assert error is None


def test_all_topos_covered_succeeds(K_beams):
    """When sub-rules cover all pair topologies in a K cluster, the rule must succeed."""
    rule = CompositeJointRule(
        [
            TopologyRule(JointTopology.TOPO_L, LButtJoint),
            TopologyRule(JointTopology.TOPO_T, TButtJoint),
        ]
    )
    model = _make_model_with_clusters(K_beams)
    from timber_design.workflow import get_clusters_from_model

    clusters = get_clusters_from_model(model)
    joint, error = rule.try_create_joint(model, clusters[0])
    assert isinstance(joint, CompositeJoint)
    assert error is None
    joint_types = {type(j) for j in joint.joints}
    assert LButtJoint in joint_types
    assert TButtJoint in joint_types


# ---------------------------------------------------------------------------
# try_create_joint — sub-rule error propagation
# ---------------------------------------------------------------------------


def test_sub_rule_error_propagated(Y_beams):
    """A BeamJoiningError raised by a matching sub-rule should be returned as the error."""
    from timber_design.workflow import get_clusters_from_model

    # Inspect the cluster first so we can target the first candidate reliably regardless of ordering.
    model = _make_model_with_clusters(Y_beams)
    clusters = get_clusters_from_model(model)
    first_pair = list(clusters[0].joints[0].elements)

    # DirectRule targets the first candidate's elements but requests TOPO_T — those beams are TOPO_L,
    # so _comply_topology raises BeamJoiningError when that candidate is processed.
    bad_rule = DirectRule(TButtJoint, first_pair)
    rule = CompositeJointRule([bad_rule])

    model2 = _make_model_with_clusters(Y_beams)
    clusters2 = get_clusters_from_model(model2)
    joint, error = rule.try_create_joint(model2, clusters2[0])
    assert joint is None
    assert error is not None


# ---------------------------------------------------------------------------
# sub-rule priority within CompositeJointRule
# ---------------------------------------------------------------------------


def test_sub_rule_priority_direct_over_topology(Y_beams):
    """A DirectRule sub-rule should win over a TopologyRule for the same pair."""
    # Identify which pair DirectRule will target by checking the cluster
    model = _make_model_with_clusters(Y_beams)
    from timber_design.workflow import get_clusters_from_model

    clusters = get_clusters_from_model(model)
    cluster = clusters[0]
    first_candidate = cluster.joints[0]
    first_pair = list(first_candidate.elements)

    direct = DirectRule(LMiterJoint, first_pair)
    topo = TopologyRule(JointTopology.TOPO_L, LButtJoint)
    rule = CompositeJointRule([direct, topo])

    model2 = _make_model_with_clusters(Y_beams)
    clusters2 = get_clusters_from_model(model2)
    joint, error = rule.try_create_joint(model2, clusters2[0])

    assert isinstance(joint, CompositeJoint)
    assert error is None
    joint_types = [type(j) for j in joint.joints]
    assert LMiterJoint in joint_types
    assert LButtJoint in joint_types


# ---------------------------------------------------------------------------
# Integration with JointRuleSolver
# ---------------------------------------------------------------------------


def test_composite_rule_in_solver_creates_composite_joint(Y_beams):
    """JointRuleSolver must apply CompositeJointRule before other rules and register the joint."""
    composite_rule = CompositeJointRule([TopologyRule(JointTopology.TOPO_L, LButtJoint)])
    fallback = TopologyRule(JointTopology.TOPO_L, LMiterJoint)

    model = TimberModel()
    model.add_elements(Y_beams)
    solver = JointRuleSolver([composite_rule, fallback])
    model.connect_adjacent_beams(solver.max_rule_distance)
    errors, unjoined = solver.apply_rules_to_model(model)

    joints = list(model.joints)
    assert len(errors) == 0
    assert len(unjoined) == 0
    assert len(joints) == 1
    assert isinstance(joints[0], CompositeJoint)


def test_composite_rule_falls_back_to_pairwise(Y_beams):
    """When CompositeJointRule can't match, individual pairwise rules should handle the cluster."""
    # CompositeJointRule with no sub-rules — will always fail to match
    composite_rule = CompositeJointRule([])
    fallback = TopologyRule(JointTopology.TOPO_L, LMiterJoint)

    model = TimberModel()
    model.add_elements(Y_beams)
    solver = JointRuleSolver([composite_rule, fallback])
    model.connect_adjacent_beams(solver.max_rule_distance)
    errors, unjoined = solver.apply_rules_to_model(model)

    joints = list(model.joints)
    assert len(errors) == 0
    assert len(unjoined) == 0
    assert len(joints) == 3
    assert all(isinstance(j, LMiterJoint) for j in joints)
