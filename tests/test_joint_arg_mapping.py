import pytest
from compas.geometry import Line
from compas.geometry import Plane
from compas.geometry import Point
from compas.geometry import Vector
from compas.geometry import cross_vectors
from compas.geometry import dot_vectors
from compas.geometry import length_vector

from compas_timber.connections import LButtJoint
from compas_timber.connections import LMiterJoint
from compas_timber.connections import TButtJoint
from compas_timber.elements import Beam

from timber_design.ghpython.joint_arg_mapping import build_joint_kwargs
from timber_design.ghpython.joint_arg_mapping import get_gh_arg_names
from timber_design.workflow import CategoryRule
from timber_design.workflow import DirectRule
from timber_design.workflow import TopologyRule


@pytest.fixture
def l_beams():
    """main_beam along x, cross_beam along y, meeting at an L corner."""
    w = 0.2
    h = 0.2
    main_beam = Beam.from_centerline(Line(Point(0, 0, 0), Point(1, 0, 0)), w, h)
    cross_beam = Beam.from_centerline(Line(Point(1, 0, 0), Point(1, 1, 0)), w, h)
    return main_beam, cross_beam


def _same_plane(plane_a, plane_b, tol=1e-6):
    """Two planes are geometrically the same if their normals are parallel and one's point lies on the other."""
    if length_vector(cross_vectors(plane_a.normal, plane_b.normal)) > tol:
        return False
    offset = dot_vectors(plane_b.normal, Vector.from_start_end(plane_b.point, plane_a.point))
    return abs(offset) < tol


def test_get_gh_arg_names_direct_renames_plane_specs():
    names = get_gh_arg_names(LButtJoint, DirectRule)
    assert names == ["main_beam", "cross_beam", "mill_depth", "modify_cross", "reject_i", "butt_plane", "back_plane", "max_distance"]


@pytest.mark.parametrize("rule_type", [CategoryRule, TopologyRule])
def test_get_gh_arg_names_non_direct_hides_plane_args(rule_type):
    names = get_gh_arg_names(LButtJoint, rule_type)
    assert "butt_plane" not in names
    assert "back_plane" not in names
    assert "butt_plane_spec" not in names
    assert "back_plane_spec" not in names
    assert names[-1] == "max_distance"


def test_get_gh_arg_names_category_suffixes_first_two():
    names = get_gh_arg_names(LButtJoint, CategoryRule)
    assert names == ["main_beam_category", "cross_beam_category", "mill_depth", "modify_cross", "reject_i", "max_distance"]


def test_get_gh_arg_names_topology_hides_elements():
    names = get_gh_arg_names(LButtJoint, TopologyRule)
    assert names == ["mill_depth", "modify_cross", "reject_i", "max_distance"]


def test_get_gh_arg_names_tbutt_has_no_back_plane():
    # TButtJoint has butt_plane_spec but no back_plane_spec, so renaming/hiding is a no-op for the latter.
    names_direct = get_gh_arg_names(TButtJoint, DirectRule)
    assert "butt_plane" in names_direct
    assert "back_plane" not in names_direct

    names_category = get_gh_arg_names(TButtJoint, CategoryRule)
    assert "butt_plane" not in names_category
    assert "butt_plane_spec" not in names_category
    assert names_category[0] == "main_beam_category"


def test_get_gh_arg_names_expose_extra_kwargs_false_caps_to_two():
    names = get_gh_arg_names(LButtJoint, DirectRule, expose_extra_kwargs=False)
    assert names == ["main_beam", "cross_beam", "max_distance"]

    names = get_gh_arg_names(LButtJoint, CategoryRule, expose_extra_kwargs=False)
    assert names == ["main_beam_category", "cross_beam_category", "max_distance"]


def test_get_gh_arg_names_no_override_applies_rule_policy_only():
    # LMiterJoint(beam_a=None, beam_b=None, cutoff=None, ref_side_miter=False, clean=False, miter_plane=None)
    assert get_gh_arg_names(LMiterJoint, DirectRule) == ["beam_a", "beam_b", "cutoff", "ref_side_miter", "clean", "miter_plane", "max_distance"]
    assert get_gh_arg_names(LMiterJoint, CategoryRule) == ["beam_a_category", "beam_b_category", "cutoff", "ref_side_miter", "clean", "miter_plane", "max_distance"]
    assert get_gh_arg_names(LMiterJoint, TopologyRule) == ["cutoff", "ref_side_miter", "clean", "miter_plane", "max_distance"]


def test_build_joint_kwargs_converts_plane_args_round_trip(l_beams):
    main_beam, cross_beam = l_beams
    butt_plane = Plane(Point(1.0, 0.5, 0.0), Vector(1, 0, 0))  # normal _|_ cross_beam centerline (y-axis)
    back_plane = Plane(Point(0.5, 0.0, 0.0), Vector(0, 1, 0))  # normal _|_ main_beam centerline (x-axis)

    kwargs = build_joint_kwargs(
        LButtJoint,
        {"butt_plane": butt_plane, "back_plane": back_plane, "mill_depth": 0.01},
        main_beam=main_beam,
        cross_beam=cross_beam,
    )

    assert "butt_plane" not in kwargs
    assert "back_plane" not in kwargs
    assert kwargs["mill_depth"] == 0.01  # untouched passthrough kwarg

    assert _same_plane(kwargs["butt_plane_spec"].to_plane(cross_beam), butt_plane)
    assert _same_plane(kwargs["back_plane_spec"].to_plane(main_beam), back_plane)


def test_build_joint_kwargs_no_plane_keys_is_passthrough(l_beams):
    main_beam, cross_beam = l_beams
    kwargs = {"mill_depth": 0.02}
    result = build_joint_kwargs(LButtJoint, kwargs, main_beam=main_beam, cross_beam=cross_beam)
    assert result == kwargs


def test_build_joint_kwargs_no_override_is_passthrough():
    kwargs = {"gap": 0.005}
    assert build_joint_kwargs(LMiterJoint, kwargs) == kwargs
