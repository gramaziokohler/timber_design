"""Maps compas_timber joint constructor args to GH-friendly inputs, with per-joint-type overrides.

GH joint-rule components build their dynamic parameters from a joint type's constructor signature.
Some joints take constructor args that aren't GH-friendly (e.g. a custom spec object that must be
built from a resolved beam pair and a plane). This module lets such joint types register an
override that (a) renames/hides constructor args for GH display, and (b) converts the raw GH kwargs
into the real constructor kwargs. Joint types with no override fall back to plain introspection.

It also centralizes the GH input-naming policy shared by every joint-rule component's `arg_names()`
(dropping `key`/`frame`, suffixing category labels, hiding elements that aren't known yet for
topology rules, appending `max_distance`), keyed by the actual rule class
(:class:`~timber_design.workflow.DirectRule`/`CategoryRule`/`TopologyRule`) rather than a string tag.
"""

import inspect

from compas_timber.connections import ButtJoint
from compas_timber.connections import CutPlaneSpec

from timber_design.workflow import CategoryRule
from timber_design.workflow import DirectRule
from timber_design.workflow import TopologyRule

_OVERRIDES = {}
_RESERVED_NAMES = ("key", "frame")


class JointArgOverride(object):
    """Base class for a per-joint-type GH arg mapping override.

    Subclass and override the methods below, then register with :func:`register_joint_arg_override`.
    """

    def gh_arg_names(self, default_names, rule_type):
        """Return the arg names to expose as GH inputs for the given `rule_type`.

        Parameters
        ----------
        default_names : list(str)
            The joint constructor's parameter names, in order, as found by plain introspection.
        rule_type : type
            The :class:`~timber_design.workflow.JointRule` subclass (`DirectRule`, `CategoryRule`,
            or `TopologyRule`) the calling GH component builds.

        """
        return default_names

    def build_kwargs(self, gh_kwargs, main_beam=None, cross_beam=None):
        """Convert GH-collected kwargs into the real joint constructor kwargs.

        Parameters
        ----------
        gh_kwargs : dict
            The kwargs collected from GH component inputs, keyed by the names returned from
            :meth:`gh_arg_names`.
        main_beam, cross_beam
            The resolved elements the joint will be created between, if known.

        """
        return gh_kwargs


def register_joint_arg_override(*joint_types):
    """Class decorator registering a :class:`JointArgOverride` instance for one or more joint types."""

    def decorator(override_cls):
        override = override_cls()
        for joint_type in joint_types:
            _OVERRIDES[joint_type] = override
        return override_cls

    return decorator


def _get_override(joint_type):
    for cls in joint_type.__mro__:
        if cls in _OVERRIDES:
            return _OVERRIDES[cls]
    return None


def _default_arg_names(joint_type):
    return [name for name in inspect.signature(joint_type.__init__).parameters if name != "self"]


def get_gh_arg_names(joint_type, rule_type, expose_extra_kwargs=True):
    """Return the GH input names for `joint_type` in a `rule_type` joint-rule component.

    Applies, in order: any registered override's renaming/hiding, dropping reserved names
    (`key`/`frame`), the `rule_type`-specific policy (category-label suffixing for `CategoryRule`;
    hiding the not-yet-known main/cross elements for `TopologyRule`), and finally appends
    `"max_distance"`.

    Parameters
    ----------
    joint_type : type
        The `compas_timber` joint class.
    rule_type : type
        `DirectRule`, `CategoryRule`, or `TopologyRule` from `timber_design.workflow`.
    expose_extra_kwargs : bool, optional
        If `False`, only the leading element-role names are returned (no other constructor kwargs).
        Used by components that don't support additional dynamic joint kwargs.

    """
    default_names = _default_arg_names(joint_type)
    override = _get_override(joint_type)
    names = override.gh_arg_names(default_names, rule_type) if override else default_names
    names = [name for name in names if name not in _RESERVED_NAMES]

    if rule_type is TopologyRule:
        names = names[2:]
    elif rule_type is CategoryRule:
        names = list(names)
        for i in range(min(2, len(names))):
            names[i] += "_category"

    if not expose_extra_kwargs:
        names = names[:2]

    return names + ["max_distance"]


def build_joint_kwargs(joint_type, gh_kwargs, main_beam=None, cross_beam=None):
    """Convert GH-collected kwargs into the real constructor kwargs for `joint_type`."""
    override = _get_override(joint_type)
    if override is None:
        return gh_kwargs
    return override.build_kwargs(gh_kwargs, main_beam=main_beam, cross_beam=cross_beam)


@register_joint_arg_override(ButtJoint)
class CutPlaneSpecOverride(JointArgOverride):
    """Exposes `butt_plane`/`back_plane` (Plane) instead of `butt_plane_spec`/`back_plane_spec` (CutPlaneSpec).

    Only meaningful when the main/cross beam pair is explicitly known (`rule_type is DirectRule`),
    since :meth:`~compas_timber.connections.CutPlaneSpec.from_butt_plane`/`.from_back_plane` need
    both beams to encode a world-coordinate plane. For category/topology rules the beam pair isn't
    known at GH-authoring time, so the raw and renamed names are both hidden there and the joint's
    own default plane behavior applies.
    """

    _RENAMES = {"butt_plane_spec": "butt_plane", "back_plane_spec": "back_plane"}

    def gh_arg_names(self, default_names, rule_type):
        if rule_type is DirectRule:
            return [self._RENAMES.get(name, name) for name in default_names]
        return [name for name in default_names if name not in self._RENAMES]

    def build_kwargs(self, gh_kwargs, main_beam=None, cross_beam=None):
        kwargs = dict(gh_kwargs)
        if "butt_plane" in kwargs:
            plane = kwargs.pop("butt_plane")
            if plane is not None:
                kwargs["butt_plane_spec"] = CutPlaneSpec.from_butt_plane(main_beam, cross_beam, plane)
        if "back_plane" in kwargs:
            plane = kwargs.pop("back_plane")
            if plane is not None:
                kwargs["back_plane_spec"] = CutPlaneSpec.from_back_plane(main_beam, cross_beam, plane)
        return kwargs
