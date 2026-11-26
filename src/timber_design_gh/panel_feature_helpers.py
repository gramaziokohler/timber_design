"""Panel feature definitions for the Grasshopper panel components.

A feature component outputs a *definition*: the feature's world-space geometry and its
parameters. A panel component turns each definition into an actual
:class:`~timber_design_arch.panel_features.PanelFeature` while it creates the panel, via
:func:`add_feature_definitions`. Since the panel is created fresh on every solve, features
never accumulate, and they are in place before any populator is configured from the panel.

Panel features store their geometry in the panel's local frame: the feature frame is
``Frame.worldXY()`` and the outlines are in panel-local coordinates, where local z runs
through the panel thickness (z=0 on ``outline_a``, z=thickness on ``outline_b``).

Features do not depend on the panel's layers, so a panel can get its layers (e.g. from a panel
type) after its features.  Outlines are placed on the panel faces (exterior on ``outline_a``,
interior on ``outline_b``) or its mid-plane; the populator's detail sets project them onto the
actual layers.

Nothing here depends on Rhino, so it can be used and tested outside Grasshopper.
"""

from compas.geometry import Frame
from compas.geometry import Point
from compas.geometry import Polyline
from compas.geometry import centroid_points
from compas.geometry import is_point_in_polygon_xy
from timber_design_arch.elements import LayerRole
from timber_design_arch.panel_features import LinearService
from timber_design_arch.panel_features import MEPPenetration
from timber_design_arch.panel_features import Niche
from timber_design_arch.panel_features import Opening
from timber_design_arch.panel_features import OpeningType

TOLERANCE = 1e-6


# ------------------------------------------------------------------
# Geometry helpers
# ------------------------------------------------------------------


def to_panel_local(polyline, panel):
    """Return a copy of a model-space *polyline* in *panel*'s local coordinates."""
    return polyline.transformed(panel.transformation_to_local())


def project_to_local_z(polyline, z):
    """Return a copy of a panel-local *polyline* flattened onto the local plane at height *z*."""
    return Polyline([Point(point[0], point[1], z) for point in polyline.points])


def side_z(panel, role):
    """Local z of the panel face on the side of *role*: 0 for exterior (``outline_a``), the thickness for interior."""
    return panel.thickness if LayerRole(role) == LayerRole.INTERIOR else 0.0


def _check_closed(polyline, what):
    if not polyline.is_closed:
        raise ValueError("{} outline must be closed.".format(what))


def _unwrap(obj):
    """CPython Grasshopper may pass custom Python objects wrapped in a GH_Goo."""
    return getattr(obj, "Value", obj)


# ------------------------------------------------------------------
# Definitions
# ------------------------------------------------------------------


class PanelFeatureDefinition(object):
    """World-space description of a panel feature, turned into a feature per panel.

    Subclasses implement :meth:`feature_for_panel` and :attr:`polylines`.

    Every definition may carry a ``detail_set`` that builds the features it creates, in place of
    the populator's default for the feature type.  It is attached to every feature made from the
    definition (the populator expands a clone, so sharing it is safe).
    """

    detail_set = None

    def _set_detail_set(self, detail_set):
        self.detail_set = _unwrap(detail_set)

    @property
    def polylines(self):
        """list[:class:`compas.geometry.Polyline`]: The world-space geometry, for preview and placement checks."""
        raise NotImplementedError

    def feature_for_panel(self, panel):
        """Create the feature for *panel*, in the panel's local frame.

        Parameters
        ----------
        panel : :class:`timber_design_arch.elements.Panel`
            The panel.  Its layers are not used.

        Returns
        -------
        :class:`timber_design_arch.panel_features.PanelFeature`
        """
        raise NotImplementedError

    def warnings_for_panel(self, panel):
        """Non-fatal problems with applying this definition to *panel*."""
        return []

    def lies_on_panel(self, panel):
        """True if this definition belongs to *panel*.

        The centre of the geometry must fall inside the panel outline, and every point must
        be within one panel thickness of the panel, so features drawn on neighbouring or
        perpendicular panels are not picked up.
        """
        points = [p for pl in self.polylines for p in to_panel_local(pl, panel).points]
        thickness = panel.thickness
        if any(p[2] < -thickness or p[2] > 2 * thickness for p in points):
            return False
        polygon = panel.plate_geometry.outline_a.points[:-1]
        return is_point_in_polygon_xy(centroid_points(points), polygon)


class OpeningDefinition(PanelFeatureDefinition):
    """A window or door opening cut through every layer of the panel.

    Parameters
    ----------
    outline : :class:`compas.geometry.Polyline`
        Closed world-space outline, drawn on or parallel to the panel.
    opening_type : :class:`timber_design_arch.panel_features.OpeningType`, optional
        Window (default) or door.
    project_horizontal : bool, optional
        Extrude sloped openings horizontally instead of along the panel normal.
    """

    def __init__(self, outline, opening_type=None, project_horizontal=False, detail_set=None):
        _check_closed(outline, "Opening")
        self._set_detail_set(detail_set)
        self.outline = outline
        self.opening_type = opening_type or OpeningType.WINDOW
        self.project_horizontal = bool(project_horizontal)

    @property
    def polylines(self):
        return [self.outline]

    def feature_for_panel(self, panel):
        # from_outline_panel transforms its input in place, so give it a copy
        return Opening.from_outline_panel(self.outline.copy(), panel, opening_type=self.opening_type, project_horizontal=self.project_horizontal)


class MEPPenetrationDefinition(PanelFeatureDefinition):
    """A service penetration with its own outline per layer role.

    The core outline defines the surround framing, and each layer's sheathing is trimmed
    by its own outline. The interior and exterior outlines are placed on their panel face,
    the core outline on the mid-plane.

    Parameters
    ----------
    outline_core : :class:`compas.geometry.Polyline`
        Closed world-space outline through the core layer.
    outline_interior, outline_exterior : :class:`compas.geometry.Polyline`, optional
        Closed world-space outlines for the interior and exterior layers. Default to the
        core outline.
    """

    def __init__(self, outline_core, outline_interior=None, outline_exterior=None, detail_set=None):
        self._set_detail_set(detail_set)
        self.outline_core = outline_core
        self.outline_interior = outline_interior or outline_core
        self.outline_exterior = outline_exterior or outline_core
        for name, outline in (("Core", self.outline_core), ("Interior", self.outline_interior), ("Exterior", self.outline_exterior)):
            _check_closed(outline, "MEP penetration {}".format(name.lower()))

    @property
    def polylines(self):
        return [self.outline_interior, self.outline_core, self.outline_exterior]

    def feature_for_panel(self, panel):
        z_interior = side_z(panel, LayerRole.INTERIOR)
        z_core = panel.thickness / 2.0
        z_exterior = side_z(panel, LayerRole.EXTERIOR)
        return MEPPenetration(
            Frame.worldXY(),
            project_to_local_z(to_panel_local(self.outline_interior, panel), z_interior),
            project_to_local_z(to_panel_local(self.outline_core, panel), z_core),
            project_to_local_z(to_panel_local(self.outline_exterior, panel), z_exterior),
        )


class NicheDefinition(PanelFeatureDefinition):
    """A one-sided recess, cut to *depth* into the sheathing on *side*, or through the framing.

    Parameters
    ----------
    outline : :class:`compas.geometry.Polyline`
        Closed world-space outline, drawn on or parallel to the panel.
    side : :class:`timber_design_arch.elements.LayerRole` | str
        :attr:`LayerRole.EXTERIOR` or :attr:`LayerRole.INTERIOR`.
    depth : float, optional
        Depth of the recess, measured from the panel face. ``None`` (default) takes the
        niche through the side layer and the framing layer.
    """

    def __init__(self, outline, side, depth=None, detail_set=None):
        _check_closed(outline, "Niche")
        self._set_detail_set(detail_set)
        side = LayerRole(side)
        if side not in Niche.SIDES:
            raise ValueError("Niche side must be one of: {}.".format(", ".join(s.value for s in Niche.SIDES)))
        if depth is not None and depth <= 0:
            raise ValueError("Niche depth must be greater than zero, or None to go through the framing layer.")
        self.outline = outline
        self.side = side
        self.depth = depth

    @property
    def polylines(self):
        return [self.outline]

    def feature_for_panel(self, panel):
        # on the panel face of its side, where the recess starts
        z = side_z(panel, self.side)
        return Niche(Frame.worldXY(), project_to_local_z(to_panel_local(self.outline, panel), z), self.side, self.depth)


class LinearServiceDefinition(PanelFeatureDefinition):
    """A manually routed service run, placed on the panel's mid-plane (the populator moves it into the core).

    Parameters
    ----------
    polyline : :class:`compas.geometry.Polyline`
        World-space service path, drawn on or parallel to the panel.
    thickness : float
        Diameter of the service.
    detail_set : :class:`~timber_design_populator.detail_sets.DetailAgentSet`, optional
        How to build the service, e.g. ``LinearServiceDetailSet(mode="notching")``.  Unset: the
        populator's default.
    """

    def __init__(self, polyline, thickness, detail_set=None):
        self._set_detail_set(detail_set)
        if not thickness or thickness <= 0:
            raise ValueError("Linear service thickness must be greater than zero.")
        self.polyline = polyline
        self.thickness = thickness

    @property
    def polylines(self):
        return [self.polyline]

    def feature_for_panel(self, panel):
        z = panel.thickness / 2.0
        return LinearService(Frame.worldXY(), project_to_local_z(to_panel_local(self.polyline, panel), z), self.thickness)


# ------------------------------------------------------------------
# Applying definitions
# ------------------------------------------------------------------


def add_feature_definitions(panel, definitions):
    """Add a feature to *panel* for every definition that lies on it.

    The panel's layers are not used, so they may be set before or after.

    Parameters
    ----------
    panel : :class:`timber_design_arch.elements.Panel`
    definitions : list[:class:`PanelFeatureDefinition`]
        Definitions that do not lie on *panel* are skipped, so the same list can be given
        to every panel.

    Returns
    -------
    tuple[list, int, list[str]]
        The added features, the number of skipped definitions, and warning messages.
    """
    added = []
    skipped = 0
    messages = []
    for definition in definitions or []:
        definition = _unwrap(definition)
        if definition is None:
            continue
        if not isinstance(definition, PanelFeatureDefinition):
            messages.append("Not a panel feature definition: {!r}".format(definition))
            continue
        if not definition.lies_on_panel(panel):
            skipped += 1
            continue
        try:
            feature = definition.feature_for_panel(panel)
        except Exception as e:
            messages.append("Could not add {}: {}".format(type(definition).__name__, e))
            continue
        feature.detail_set = definition.detail_set
        panel.add_feature(feature)
        added.append(feature)
        messages.extend(definition.warnings_for_panel(panel))
    return added, skipped, messages
