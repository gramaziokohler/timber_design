from __future__ import annotations

import math

from compas.geometry import Box
from compas.geometry import Line
from compas.geometry import Plane
from compas.geometry import Point
from compas.geometry import Polyline
from compas.geometry import angle_vectors
from compas.geometry import distance_point_plane
from compas.geometry import dot_vectors
from compas.geometry import intersection_line_plane
from compas.geometry import intersection_segment_segment_xy
from compas_arch.elements import LayerRole
from compas_arch.panel_features import LinearService
from compas_arch.panel_features import LinearServiceMode
from compas_arch.panel_features import MEPPenetration
from compas_arch.panel_features import Niche
from compas_timber.elements import Plate
from compas_timber.errors import FeatureApplicationError
from compas_timber.fabrication import Drilling
from compas_timber.fabrication import FreeContour
from compas_timber.fabrication import Lap

from timber_design_populator.connections_2d.beam2d import Beam2D
from timber_design_populator.populator_agents.feature_agent import FeatureAgent
from timber_design_populator.populator_agents.opening_populator_agent import WindowPopulatorAgent


class MEPPenetrationPopulatorAgent(WindowPopulatorAgent):
    """Frames a service penetration in the core and trims each layer by its own outline.

    The surround is framed like a window: header, sill and king studs (plus jack studs
    when ``lintel_posts`` is set).
    """

    FEATURE_TYPE = MEPPenetration
    NAME = "MEPPenetrationPopulatorAgent"

    def _create_frame_polylines(self, opening, layer):
        return _project_to_layer_faces(self.feature.outline_core, layer)

    def compute_outline_for_layer(self, layer):
        outline = _outline_for_layer(self.feature, layer)
        if outline is None:
            return None
        return _project_to_layer_midplane(outline, layer)

    def trim_plate(self, plate: Plate) -> None:
        layer = plate.parent
        outline = _outline_for_layer(self.feature, layer)
        if outline is None:
            return
        # FreeContour needs the outline on a face of the plate. Project it onto this plate's
        # layer face, so plates on any sublayer of a subdivided role layer are cut through.
        outline = _project_to_plane(outline, layer.planes[0], layer.normal)
        plate.add_feature(FreeContour.from_polyline_and_element(outline, plate, depth=plate.thickness, interior=True))


class NichePopulatorAgent(WindowPopulatorAgent):
    """Frames a one-sided niche and cuts it into its side layer.

    The surround is framed like a window: header, sill and king studs (plus jack studs
    when ``lintel_posts`` is set).

    With a ``depth``, the niche is a blind pocket of that depth, cut from the panel face
    into the side layer's outermost plate; the framing layer is not trimmed.

    Without a ``depth`` (``None``), the niche goes through the framing layer: every plate
    on the side layer is cut through, and on the framing layer the surround trims the
    peer framing like an opening does. Only the opposite side layer is left, as the
    back of the niche.
    """

    FEATURE_TYPE = Niche
    NAME = "NichePopulatorAgent"

    @property
    def through_framing(self) -> bool:
        """True if the bound niche has no depth, so it goes through the framing layer."""
        return self.feature is not None and self.feature.depth is None

    @property
    def trimming_layers(self):
        layers = list(super().trimming_layers)
        if self.through_framing:
            # trim the framing layer too, so studs inside the surround are cut away
            layers += [layer for layer in self.element_layers if layer not in layers]
        return layers

    def _create_frame_polylines(self, opening, layer):
        return _project_to_layer_faces(self.feature.outline, layer)

    def compute_outline_for_layer(self, layer):
        if self.through_framing and layer in self.element_layers:
            # the surround's outline, as for an opening
            return super().compute_outline_for_layer(layer)
        if not _is_niche_side_layer(self.feature, layer):
            return None
        return _project_to_layer_midplane(self.feature.outline, layer)

    def trim_plate(self, plate: Plate) -> None:
        layer = plate.parent
        if not _is_niche_side_layer(self.feature, layer):
            return
        if self.through_framing:
            # cut through every plate of the side layer, sublayers included
            outline = _project_to_plane(self.feature.outline, layer.planes[0], layer.normal)
            plate.add_feature(FreeContour.from_polyline_and_element(outline, plate, depth=plate.thickness, interior=True))
            return
        # The recess starts at the panel face, so only the plate whose layer face the outline
        # lies on is cut; plates on inner sublayers of a subdivided side layer are skipped.
        if not any(_lies_on_plane(self.feature.outline, plane) for plane in layer.planes):
            return
        plate.add_feature(FreeContour.from_polyline_and_element(self.feature.outline, plate, depth=self.feature.depth, interior=True))


class LinearServicePopulatorAgent(FeatureAgent):
    """Machines the framing a manually routed service runs through.

    The agent creates no elements. It works on the beams of its trimming layers (the
    core, as bound by :func:`~timber_design_populator.stud_panel`): every beam the
    service path crosses gets a hole or notch the size of the service, depending on
    the feature's routing mode. Sheathing is not cut.

    - :attr:`~compas_arch.panel_features.LinearServiceMode.CORE_DRILLING` drills a hole
      through the beam along the service path, on the core's mid-plane.
    - :attr:`~compas_arch.panel_features.LinearServiceMode.FRAME_NOTCHING` cuts a
      :class:`~compas_timber.fabrication.Lap` notch into the beam's interior face, as deep
      and as wide as the service.

    A warning is reported (as a feature error in the populator's ``debug_info``) when a
    hole is larger than :attr:`MAX_DRILLING_RATIO` or a notch deeper than
    :attr:`MAX_NOTCH_RATIO` of the beam's depth through the panel. The defaults follow
    the common rules for studs: holes up to 40% and notches up to 25% of the depth.
    """

    FEATURE_TYPE = LinearService
    NAME = "LinearServicePopulatorAgent"
    MAX_DRILLING_RATIO = 0.4
    MAX_NOTCH_RATIO = 0.25

    def __init__(
        self,
        feature: LinearService = None,
        element_layers=None,
        trimming_layers=None,
        internal_joint_overrides=None,
        external_joint_overrides=None,
        composite_joint_overrides=None,
    ):
        super().__init__(feature, element_layers, trimming_layers, internal_joint_overrides, external_joint_overrides, composite_joint_overrides)
        self._interior_direction = None

    def generate_elements_for_layer(self, layer):
        return [], None

    def repoint_to_layer_tree(self, tree):
        super().repoint_to_layer_tree(tree)
        self._interior_direction = _interior_direction(tree)

    def machine_element(self, element) -> list:
        if self.feature is None or not isinstance(element, Beam2D):
            return []
        diameter = self.feature.thickness
        warnings = []
        for point, direction in _crossings(self.feature.polyline, element):
            if self.feature.routing_mode == LinearServiceMode.FRAME_NOTCHING:
                warning = self._notch(element, point, direction, diameter)
            else:
                warning = self._drill(element, point, direction, diameter)
            if warning:
                warnings.append(warning)
        return warnings

    def _drill(self, beam, point, direction, diameter):
        # a line along the service, long enough to pass through the beam
        reach = beam.width + beam.height
        line = Line(point - direction * reach, point + direction * reach)
        beam.add_feature(_ServiceDrillingProxy(line, beam, diameter))
        if diameter > self.MAX_DRILLING_RATIO * beam.height:
            return FeatureApplicationError(
                line,
                beam.blank,
                "{} {:.1f} hole is more than {:.0%} of the beam depth {:.1f}.".format(beam.attributes.get("category", "beam"), diameter, self.MAX_DRILLING_RATIO, beam.height),
            )
        return None

    def _notch(self, beam, point, direction, diameter):
        if self._interior_direction is None:
            return FeatureApplicationError(point, beam.blank, "Cannot notch: the panel's interior side is unknown.")
        axis = beam.centerline.direction.unitized()
        # the notch spans the service's footprint along the beam
        sin_angle = abs(math.sin(angle_vectors(axis, direction)))
        length = diameter / max(sin_angle, 1e-3)
        plane = Plane(point + axis * (length / 2.0), axis)
        ref_side_index = _ref_side_facing(beam, self._interior_direction)
        beam.add_feature(_ServiceLapProxy(plane, beam, length, diameter, ref_side_index))
        if diameter > self.MAX_NOTCH_RATIO * beam.height:
            return FeatureApplicationError(
                point,
                beam.blank,
                "{} {:.1f} notch is more than {:.0%} of the beam depth {:.1f}.".format(beam.attributes.get("category", "beam"), diameter, self.MAX_NOTCH_RATIO, beam.height),
            )
        return None


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


def _crossings(polyline, beam, tol=1e-6):
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


def _interior_direction(tree):
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


def _ref_side_facing(beam, direction):
    """Index of the long reference side of *beam* whose normal points most along *direction*."""
    return max(range(4), key=lambda i: dot_vectors(beam.ref_sides[i].normal, direction))


def _outline_for_layer(feature, layer):
    """The outline of *feature* for the role of *layer*, or ``None`` for layers without a role."""
    role = getattr(layer, "role", None)
    if role == LayerRole.INTERIOR:
        return feature.outline_interior
    if role == LayerRole.CORE:
        return feature.outline_core
    if role == LayerRole.EXTERIOR:
        return feature.outline_exterior
    return None


def _is_niche_side_layer(feature: Niche, layer) -> bool:
    """True if *layer* belongs to the role layer the niche is cut into (sublayers included)."""
    return layer is not None and getattr(layer, "role", None) == feature.side


def _lies_on_plane(polyline: Polyline, plane: Plane, tol: float = 1e-3) -> bool:
    return all(abs(distance_point_plane(point, plane)) < tol for point in polyline.points)


def _project_to_plane(polyline: Polyline, plane: Plane, direction) -> Polyline:
    """Project *polyline* onto *plane* along *direction*."""
    points = []
    for point in polyline.points:
        intersection = intersection_line_plane(Line.from_point_and_vector(point, direction), plane)
        if intersection is None:
            raise ValueError("Could not project feature outline onto the layer face.")
        points.append(intersection)
    return Polyline(points)


def _project_to_layer_faces(outline: Polyline, layer):
    points_a = []
    points_b = []
    for point in outline.points:
        line = Line.from_point_and_vector(point, layer.normal)
        intersection_a = intersection_line_plane(line, layer.planes[0])
        intersection_b = intersection_line_plane(line, layer.planes[1])
        if intersection_a is not None:
            points_a.append(intersection_a)
        if intersection_b is not None:
            points_b.append(intersection_b)
    if len(points_a) != len(outline.points) or len(points_b) != len(outline.points):
        raise ValueError("Could not project feature outline onto both faces of the framing layer.")
    box_a = Box.from_points(points_a)
    box_b = Box.from_points(points_b)
    frame_polyline_a = Polyline([box_a.corner(i) for i in (0, 1, 2, 3, 0)])
    frame_polyline_b = Polyline([box_b.corner(i) for i in (0, 1, 2, 3, 0)])
    return frame_polyline_a, frame_polyline_b


def _project_to_layer_midplane(outline: Polyline, layer):
    center_plane = Plane(layer.outline_a[0] + layer.normal * (layer.thickness / 2), layer.normal)
    points = []
    for point in outline.points:
        intersection = intersection_line_plane(Line.from_point_and_vector(point, layer.normal), center_plane)
        if intersection is None:
            raise ValueError("Could not project feature outline onto the layer midplane.")
        points.append(intersection)
    return Polyline(points)
