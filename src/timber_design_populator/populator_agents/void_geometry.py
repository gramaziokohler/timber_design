"""Geometry shared by the void agents and the detail sets: frames, boundaries and projections in populator space.

A *frame* is the rectangle a void is framed around on one layer, given as its two face
polylines (``frame_outline_a`` / ``frame_outline_b``, on the layer's two faces).  The functions
here are the ones the replaced opening / MEP / niche agents used, so the detail sets built on
them frame and cut exactly as those agents did.
"""

from __future__ import annotations

from compas.geometry import Box
from compas.geometry import Line
from compas.geometry import Plane
from compas.geometry import Point
from compas.geometry import Polyline
from compas.geometry import distance_point_plane
from compas.geometry import intersection_line_plane
from compas_timber.utils import extend_line_segments
from compas_timber.utils import join_polyline_segments


def frame_through_outlines(outline_a, outline_b, layer):
    """The frame of a void running between two outlines (e.g. an opening's two face outlines) on *layer*.

    Each pair of corresponding points defines a line through the panel; the lines are
    intersected with horizontal planes at the layer's two faces and boxed.

    Returns
    -------
    tuple[:class:`~compas.geometry.Polyline`, :class:`~compas.geometry.Polyline`]
    """
    points_a = []
    points_b = []
    for point_a, point_b in zip(outline_a.points, outline_b.points):
        line = Line(point_a, point_b)
        hit_a = intersection_line_plane(line, Plane(layer.outline_a[0], [0, 0, 1]))
        hit_b = intersection_line_plane(line, Plane(layer.outline_b[0], [0, 0, 1]))
        if hit_a:
            points_a.append(hit_a)
        if hit_b:
            points_b.append(hit_b)
    return _box_polyline(points_a), _box_polyline(points_b)


def frame_on_layer_faces(outline, layer):
    """The frame of a void given by one outline, projected along the layer normal onto *layer*'s faces.

    Returns
    -------
    tuple[:class:`~compas.geometry.Polyline`, :class:`~compas.geometry.Polyline`]
    """
    points_a = []
    points_b = []
    for point in outline.points:
        line = Line.from_point_and_vector(point, layer.normal)
        hit_a = intersection_line_plane(line, layer.planes[0])
        hit_b = intersection_line_plane(line, layer.planes[1])
        if hit_a is not None:
            points_a.append(hit_a)
        if hit_b is not None:
            points_b.append(hit_b)
    if len(points_a) != len(outline.points) or len(points_b) != len(outline.points):
        raise ValueError("Could not project feature outline onto both faces of the framing layer.")
    return _box_polyline(points_a), _box_polyline(points_b)


def _box_polyline(points):
    box = Box.from_points(points)
    return Polyline([box.corner(i) for i in (0, 1, 2, 3, 0)])


def frame_rectangle(frame_outline_a, frame_outline_b, center_height, bottom_offset=0.0):
    """The rectangle between the two face polylines of a frame, at *center_height*.

    Its vertical edges take the inner of the two faces' extents.  *bottom_offset* moves the
    bottom edge down (doors use it to keep their frame clear of the bottom plate).
    """
    a, b = frame_outline_a.points, frame_outline_b.points
    rectangle = Polyline(
        [
            Point(a[0][0], max(a[0][1], b[0][1]), center_height),
            Point(a[1][0], min(a[1][1], b[1][1]), center_height),
            Point(a[2][0], min(a[2][1], b[2][1]), center_height),
            Point(a[3][0], max(a[3][1], b[3][1]), center_height),
            Point(a[4][0], max(a[4][1], b[4][1]), center_height),
        ]
    )
    if bottom_offset:
        for i in (0, 3, 4):
            rectangle.points[i].y -= bottom_offset
    return rectangle


def frame_segments(frame_outline_a, frame_outline_b, center_height, bottom_offset=0.0):
    """The four sides of :func:`frame_rectangle`, the right side flipped to run like the panel's studs."""
    segments = [line for line in frame_rectangle(frame_outline_a, frame_outline_b, center_height, bottom_offset).lines]
    segments[2].flip()
    return segments


def frame_boundary(frame_outline_a, frame_outline_b, center_height, bottom_offset=0.0):
    """The closed boundary outline of a frame: its four sides, extended and joined."""
    segments = frame_segments(frame_outline_a, frame_outline_b, center_height, bottom_offset)
    extend_line_segments(segments, close_loop=True)
    return join_polyline_segments(segments, close_loop=True)[0][0]


def project_to_layer_midplane(outline, layer):
    """*outline* projected along the layer normal onto *layer*'s mid-plane."""
    center_plane = Plane(layer.outline_a[0] + layer.normal * (layer.thickness / 2), layer.normal)
    points = []
    for point in outline.points:
        hit = intersection_line_plane(Line.from_point_and_vector(point, layer.normal), center_plane)
        if hit is None:
            raise ValueError("Could not project feature outline onto the layer midplane.")
        points.append(hit)
    return Polyline(points)


def project_to_plane(outline, plane, direction):
    """*outline* projected onto *plane* along *direction*."""
    points = []
    for point in outline.points:
        hit = intersection_line_plane(Line.from_point_and_vector(point, direction), plane)
        if hit is None:
            raise ValueError("Could not project feature outline onto the layer face.")
        points.append(hit)
    return Polyline(points)


def lies_on_plane(outline, plane, tol=1e-3):
    return all(abs(distance_point_plane(point, plane)) < tol for point in outline.points)
