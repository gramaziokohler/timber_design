"""Cross-panel geometry for the panel joints that build connection details.

Everything is computed in one panel's local frame (its populator space): the joint sees both
panels, and hands each one its half in its own coordinates.
"""

from __future__ import annotations

from compas.geometry import Plane
from compas.geometry import Point
from compas.geometry import Vector
from compas.geometry import closest_point_on_line
from compas.geometry import dot_vectors
from compas.geometry import intersection_plane_plane
from compas_arch.elements import LayerRole
from compas_timber.utils import get_polyline_segment_perpendicular_vector

STAGGER_ROLES = (LayerRole.EXTERIOR, LayerRole.CORE, LayerRole.INTERIOR)


def layer_stagger(panel, partner, edge_index, main):
    """The extension of each of *panel*'s role layers at *edge_index*, against *partner*'s layers.

    Each pair of same-role layers is butt-jointed on its own, like a plate L-butt: the layer that
    *butts* stops at the near face of the partner's layer, the layer that *passes* runs on to its
    far face.  The core of the main panel butts; on the exterior and interior it is the other
    way round, so the cladding layers wrap the corner.

    Parameters
    ----------
    panel, partner : :class:`~compas_arch.elements.Panel`
        In a model, with their layers.
    edge_index : int
        *panel*'s edge at the joint.
    main : bool
        Whether *panel* is the joint's main panel.

    Returns
    -------
    tuple[list[dict], list[str]]
        ``{"layer_path": tuple, "plane": Plane}`` per layer, planes in *panel*'s local frame,
        and a message per role layer missing on either panel.
    """
    to_local = panel.modeltransformation.inverse()
    extensions = []
    messages = []
    for role in STAGGER_ROLES:
        layer = panel.layer_for_role(role)
        partner_layer = partner.layer_for_role(role)
        if layer is None or partner_layer is None:
            messages.append("both panels need a {} layer; it is missing on {} panel.".format(role.value, "this" if layer is None else "the partner"))
            continue
        outline = layer.outline_a.transformed(to_local)
        partner_planes = [plane.transformed(to_local) for plane in partner_layer.planes]
        butts = main if role == LayerRole.CORE else not main
        extensions.append({"layer_path": layer.layer_path, "plane": _butt_plane(outline, edge_index, partner_planes, butts)})
    return extensions, messages


def _butt_plane(outline, edge_index, partner_planes, butts):
    """The partner layer face this layer's edge moves to: the near one if it butts, the far one if it passes."""
    outward = get_polyline_segment_perpendicular_vector(outline, edge_index)
    segment = outline.lines[edge_index]
    normal = partner_planes[0].normal
    sign = 1.0 if dot_vectors(normal, outward) >= 0 else -1.0

    def reach(plane):  # how far out past this edge the plane lies
        return sign * dot_vectors(Vector.from_start_end(segment.midpoint, plane.point), normal)

    near, far = sorted(partner_planes, key=reach)
    return near if butts else far


def backing_stud_lines(panel, partner, inset=0.0):
    """Where backing studs go in *panel*'s core: centred on each line where a face of *partner* meets it.

    Returns
    -------
    tuple[list[:class:`~compas.geometry.Point`], :class:`~compas.geometry.Vector`] or None
        A point on each stud line (at the core's mid-height) and the stud direction, in *panel*'s
        local frame; ``None`` when *panel* has no core or *partner* is parallel to it.
    """
    core = panel.core_layer
    if core is None:
        return None
    to_local = panel.modeltransformation.inverse()
    outline = core.outline_a.transformed(to_local)
    z = outline.points[0][2] + core.thickness / 2.0
    center_plane = Plane([0, 0, z], [0, 0, 1])
    faces = [plane.transformed(to_local) for plane in partner.planes]
    traces = [intersection_plane_plane(face, center_plane) for face in faces]
    if any(trace is None for trace in traces):
        return None

    direction = Vector.from_start_end(*traces[0]).unitized()
    across = direction.cross(Vector(0, 0, 1))  # in the panel plane, perpendicular to the studs
    if dot_vectors(across, faces[0].normal) < 0:
        across = -across  # now points from the first face towards the second
    points = outline.points[:-1]
    center = Point(*[sum(p[i] for p in points) / len(points) for i in range(2)] + [z])
    positions = []
    for trace, inward in zip(traces, (across, -across)):
        closest = closest_point_on_line(center, trace)
        positions.append(Point(*(Vector(*closest) + inward * inset)))
    return positions, direction
