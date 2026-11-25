"""Geometry and deferred machining shared by the service detail agents.

The deferred cuts build their :class:`~compas_timber.fabrication.Drilling` or
:class:`~compas_timber.fabrication.Lap` only when needed, so the parameters come from the
beam's blank as extended by joinery, and they are not joinery, so they survive the beam
being reset or serialized.
"""

from __future__ import annotations

from compas.geometry import Point
from compas.geometry import dot_vectors
from compas.geometry import intersection_segment_segment_xy
from compas_arch.elements import LayerRole
from compas_timber.fabrication import Drilling
from compas_timber.fabrication import Lap


class _DeferredServiceCut(object):
    """A machining built only when needed, so it uses the beam's blank as extended by joinery.

    Unlike compas_timber's proxies it is never joinery, so it is kept when the element is
    reset or serialized. Subclasses implement :meth:`_build`.
    """

    def __init__(self, beam):
        self.beam = beam
        self._processing = None
        self._building = False

    def __deepcopy__(self, *args, **kwargs):
        return self.unproxified()

    def _build(self):
        raise NotImplementedError

    def unproxified(self):
        if not self._processing:
            self._building = True
            try:
                processing = self._build()
            finally:
                self._building = False
            processing._is_joinery = False
            self._processing = processing
        return self._processing

    def apply(self, geometry, element):
        if self._building:
            # Building the processing can ask for the element's geometry (e.g. to report an
            # error), which applies this cut again: skip it there instead of recursing.
            return geometry
        return self.unproxified().apply(geometry, element)

    def __getattr__(self, attr):
        if attr.startswith("_") and not attr.startswith("__"):
            # never forward this object's own private attributes: they are looked up before
            # __init__ has run (e.g. while copying), and forwarding them would recurse.
            # Dunders such as __jsondump__ are forwarded, so the cut serializes as the processing.
            raise AttributeError(attr)
        return getattr(self.unproxified(), attr)


class _ServiceDrillingProxy(_DeferredServiceCut):
    """A deferred, non-joinery :class:`~compas_timber.fabrication.Drilling` along *line*."""

    def __init__(self, line, beam, diameter):
        super().__init__(beam)
        self.line = line.transformed(beam.transformation_to_local())
        self.diameter = diameter

    def _build(self):
        line = self.line.transformed(self.beam.modeltransformation)
        return Drilling.from_line_and_element(line, self.beam, self.diameter)


class _ServiceLapProxy(_DeferredServiceCut):
    """A deferred, non-joinery :class:`~compas_timber.fabrication.Lap` notch."""

    def __init__(self, plane, beam, length, depth, ref_side_index):
        super().__init__(beam)
        self.plane = plane.transformed(beam.transformation_to_local())
        self.length = length
        self.depth = depth
        self.ref_side_index = ref_side_index

    def _build(self):
        plane = self.plane.transformed(self.beam.modeltransformation)
        return Lap.from_plane_and_beam(plane, self.beam, self.length, self.depth, ref_side_index=self.ref_side_index)


def crossings(polyline, beam, tol=1e-6):
    """Points where the service *polyline* runs through *beam*, with the service direction there.

    The service crosses the beam where it crosses its centerline in the panel plane, and only
    if the service lies within the beam's extent through the panel thickness: a service on the
    core mid-plane does not run through battens or other framing on the sheathing layers.
    """
    zs = [point[2] for point in beam.blank.points]
    z_min, z_max = min(zs) - tol, max(zs) + tol
    centerline = beam.centerline
    result = []
    for segment in polyline.lines:
        if not (z_min <= segment.start.z <= z_max and z_min <= segment.end.z <= z_max):
            continue
        hit = intersection_segment_segment_xy(segment, centerline)
        if hit:
            point = Point(hit[0], hit[1], segment.start.z)
            result.append((point, segment.direction.unitized()))
    return result


def interior_direction(tree):
    """Panel-normal direction from the core towards the interior side, in populator space.

    Uses the root core and interior role layers. Without an interior layer, the interior is
    taken to be the panel's ``outline_b`` side, as for the panel feature definitions.
    """
    roots = [layer for layer in tree.values() if layer.layer_path is not None and len(layer.layer_path) == 1]
    core = next((layer for layer in roots if layer.role == LayerRole.CORE), None)
    if core is None:
        return None
    interior = next((layer for layer in roots if layer.role == LayerRole.INTERIOR), None)
    if interior is None or interior.start_offset > core.start_offset:
        return core.normal
    return core.normal * -1


def ref_side_facing(beam, direction):
    """Index of the long reference side of *beam* whose normal points most along *direction*."""
    return max(range(4), key=lambda i: dot_vectors(beam.ref_sides[i].normal, direction))
