from __future__ import annotations

from collections import namedtuple
from typing import TYPE_CHECKING
from typing import Optional
from typing import Union

from compas.data import Data
from compas.geometry import Box
from compas.geometry import Frame
from compas.geometry import Plane
from compas.geometry import Point
from compas.geometry import Polyline
from compas.geometry import Transformation
from compas.geometry import Vector
from compas_model.elements import Element
from compas_timber.base import MODEL_CACHE
from compas_timber.base import clear_element_cache
from compas_timber.elements.plate_geometry import PlateGeometry
from compas_timber.elements.plate_geometry import RigidPlacement
from compas_timber.elements.plate_geometry import global_outlines_to_local
from compas_timber.utils import StrEnum

if TYPE_CHECKING:
    from .panel import Panel  # noqa: F401


class LayerRole(StrEnum):
    """The role of a root layer in a panel's cross-section.

    A :class:`LayerStructure` has at most one root layer per role.  Sublayers carry the
    role of the root layer they subdivide.

    Values are explicit (not ``auto()``) so they are the same on every Python version
    and serialize identically in CPython and Rhino.

    Attributes
    ----------
    EXTERIOR : literal("exterior")
    CORE : literal("core")
    INTERIOR : literal("interior")
    """

    EXTERIOR = "exterior"
    CORE = "core"
    INTERIOR = "interior"


LayerSlot = namedtuple("LayerSlot", ["layer_path", "role", "name", "start", "end"])
LayerSlot.__doc__ = """A :class:`LayerDefinition` resolved to absolute offsets for a given panel thickness.

``start`` and ``end`` are measured from the panel's ``outline_a`` face towards ``outline_b``.
See :meth:`LayerStructure.resolve`.
"""


class Layer(RigidPlacement, Element):
    """A resolved cross-section layer of a :class:`~compas_arch.elements.Panel`.

    A ``Layer`` represents a slice of a parent panel between two
    through-thickness levels, measured from the ``outline_a`` face.  It is a
    first-class model element that owns its own
    :class:`~compas_timber.elements.PlateGeometry` and lives as a child of the
    parent panel in the model tree.

    Like :class:`~compas_arch.elements.Panel` and
    :class:`~compas_timber.elements.Plate`, a ``Layer`` is constructed directly
    from a :class:`~compas_timber.elements.PlateGeometry` -- it holds no
    reference to whatever produced that geometry. Use
    :meth:`from_parent_start_end` to build a ``Layer`` by interpolating the
    outlines of a parent :class:`~compas_arch.elements.Panel` or another
    ``Layer`` between two through-thickness levels.

    Parameters
    ----------
    plate_geometry : :class:`~compas_timber.elements.PlateGeometry`
        Geometry of this layer slice.
    start_offset : float
        Starting offset from the panel's ``outline_a`` face, measured along the
        panel's thickness direction.
    name : str, optional
        Human-readable identifier.
    role : :class:`LayerRole` | str, optional
        The role of the root layer this layer belongs to.  Sublayers carry their root
        layer's role.  ``None`` for layers outside any role layer.
    sublayers : list[:class:`Layer`], optional
        Child layers to attach immediately.  Equivalent to setting :attr:`sublayers`
        after construction.
    layer_path : tuple[int, ...], optional
        Position in the parent panel's layer tree.  See :attr:`layer_path`.
    frame : :class:`~compas.geometry.Frame`, optional
        The coordinate system (frame) of this layer, relative to its parent. Defaults to worldXY.

    Attributes
    ----------
    plate_geometry : :class:`~compas_timber.elements.PlateGeometry`
        Geometry of this layer slice.
    start_offset : float
        Starting offset of this layer from the panel's ``outline_a`` face, measured
        along the panel's thickness direction.
    sublayers : list[:class:`Layer`]
        Ordered child layers.  Derived from the model tree when in a model; falls back
        to the stored list when standalone.
    layer_path : tuple[int, ...] or None
        Position in the parent panel's layer tree, e.g. ``(1,)`` for the second root
        layer or ``(1, 0)`` for its first child.
    role : :class:`LayerRole` or None
        The role of the root layer this layer belongs to.
    thickness : float
        Layer thickness, taken from :attr:`plate_geometry`.
    outline_a, outline_b : :class:`~compas.geometry.Polyline`
        World-space outlines of the two main faces.
    planes : tuple[:class:`~compas.geometry.Plane`, :class:`~compas.geometry.Plane`]
        World-space planes of the two main faces.
    normal : :class:`~compas.geometry.Vector`
        World-space normal of the layer.
    edge_planes : dict[int, :class:`~compas.geometry.Plane`]
        World-space edge planes by edge index.
    """

    MODEL_CACHE = MODEL_CACHE + ("_planes",)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    @property
    def __data__(self):
        data = {}
        data["frame"] = Frame.from_transformation(self.transformation)
        data["plate_geometry"] = self.plate_geometry
        data["start_offset"] = self.start_offset
        data["name"] = self.name
        data["layer_path"] = list(self.layer_path) if self.layer_path is not None else None
        data["role"] = self.role.value if self.role is not None else None
        data.update(self.attributes)
        return data

    # ------------------------------------------------------------------
    # Constructor
    # ------------------------------------------------------------------

    def __init__(
        self,
        plate_geometry: PlateGeometry,
        start_offset: float,
        name: Optional[str] = None,
        sublayers: Optional[list] = None,
        layer_path: Optional[tuple] = None,
        frame: Optional[Frame] = None,
        role: Optional[Union[LayerRole, str]] = None,
        **kwargs,
    ):
        super(Layer, self).__init__(
            transformation=Transformation.from_frame(frame if frame is not None else Frame.worldXY()),
            name=name,
            **kwargs,
        )
        self.plate_geometry = plate_geometry
        self.start_offset = start_offset
        self.layer_path = tuple(layer_path) if layer_path is not None else None
        self.role = LayerRole(role) if role is not None else None
        self.debug_info = []
        self._sublayers = []
        self._planes = None
        self.attributes = {}
        self.attributes.update(kwargs)

        if sublayers:
            self.sublayers = sublayers

    @classmethod
    def from_parent_start_end(
        cls,
        host: Union[Panel, Layer],
        start_offset: float,
        end_offset: float,
        name: Optional[str] = None,
        sublayers: Optional[list] = None,
        layer_path: Optional[tuple] = None,
        role: Optional[Union[LayerRole, str]] = None,
        **kwargs,
    ) -> Layer:
        """Construct a ``Layer`` by interpolating the outlines of *host* between two through-thickness levels.

        Parameters
        ----------
        host : :class:`~compas_arch.elements.Panel` or :class:`Layer`
            The panel (for root layers) or enclosing layer (for sublayers) to
            interpolate outlines from.  Not stored: the resulting ``Layer`` holds
            no reference back to *host*.
        start_offset, end_offset : float
            See :class:`Layer`.
        name, sublayers, layer_path, role : optional
            See :class:`Layer`.

        Returns
        -------
        :class:`Layer`
        """
        outline_a, outline_b = cls.get_outlines_from_parent(host, start_offset, end_offset)
        frame, local_outline_a, local_outline_b = global_outlines_to_local(outline_a, outline_b, orientation=[0, 1, 0])
        plate_geometry = PlateGeometry(local_outline_a, local_outline_b)
        return cls(
            plate_geometry,
            start_offset,
            name=name,
            sublayers=sublayers,
            layer_path=layer_path,
            frame=frame,
            role=role,
            **kwargs,
        )

    def __repr__(self):
        return "Layer(name={}, thickness={})".format(self.name, self.thickness)

    def __str__(self):
        return "Layer(name={}, thickness={})".format(self.name, self.thickness)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def sublayers(self):
        if self.model is not None:
            return [c for c in self.children if isinstance(c, Layer)]
        return self._sublayers

    @sublayers.setter
    def sublayers(self, layers):
        self._sublayers = list(layers) if layers else []
        if self.model is not None:
            self.merge_sublayer_tree(self.model)

    @property
    def thickness(self):
        return self.plate_geometry.thickness

    @property
    def outline_a(self):
        return self.plate_geometry.outline_a.transformed(self.modeltransformation)

    @property
    def outline_b(self):
        return self.plate_geometry.outline_b.transformed(self.modeltransformation)

    @property
    def outlines(self):
        return (self.outline_a, self.outline_b)

    @property
    def planes(self):
        if not self._planes:
            local_planes = (Plane.worldXY(), Plane(Point(0, 0, self.thickness), Vector(0, 0, 1)))
            self._planes = (
                local_planes[0].transformed(self.modeltransformation),
                local_planes[1].transformed(self.modeltransformation),
            )
        return self._planes

    @property
    def normal(self):
        return Vector(0, 0, 1).transformed(self.modeltransformation)

    @property
    def edge_planes(self):
        return {i: plane.transformed(self.modeltransformation) for i, plane in self.plate_geometry.edge_planes.items()}

    @property
    def center_height(self):
        """Z coordinate of the layer's mid-thickness in model space."""
        return self.outline_a[0][2] + self.thickness / 2

    @property
    def geometry(self):
        return self.modelgeometry

    @geometry.setter
    def geometry(self, _):
        raise AttributeError("Geometry is a computed property and cannot be set directly.")

    # ------------------------------------------------------------------
    # Methods
    # ------------------------------------------------------------------
    def reset(self):
        """Resets the element to its initial state by removing extensions and debug_info."""
        self.plate_geometry.reset()  # reset outline_a and outline_b
        self.debug_info = []
        for sublayer in self.sublayers:
            sublayer.reset()
        clear_element_cache(self)

    def define_sublayers(self, thicknesses: list, names: Optional[list] = None) -> list:
        """Subdivide this layer into child layers by thickness.

        Parameters
        ----------
        thicknesses : list[float | None]
            Thickness of each sublayer, ordered from :attr:`start_offset` towards the
            far face of this layer.  At most one entry may be ``None``; that slot absorbs whatever thickness
            remains after the other entries are summed.  If no ``None`` is present
            and the sum of entries is less than :attr:`thickness`, an extra layer
            is appended at the end with the remaining thickness.
            The sum of all explicit (non-``None``) values must not exceed
            :attr:`thickness`.
        names : list[str | None], optional
            Names for the sublayers.  When given, length must match *thicknesses*
            (before any auto-appended remainder layer).

        Returns
        -------
        list[:class:`Layer`]
            The newly created sublayers (also stored in :attr:`sublayers`).
        """
        none_count = sum(1 for t in thicknesses if t is None)
        if none_count > 1:
            raise ValueError("At most one None is allowed in thicknesses.")
        if names is not None and len(names) != len(thicknesses):
            raise ValueError("Length of names ({}) must match length of thicknesses ({}).".format(len(names), len(thicknesses)))

        sum_defined = sum(t for t in thicknesses if t is not None)
        remaining = self.thickness - sum_defined
        if remaining < -1e-6:
            raise ValueError("Sum of defined thicknesses ({:.6f}) exceeds layer thickness ({:.6f}).".format(sum_defined, self.thickness))

        if none_count == 1:
            thicknesses = [remaining if t is None else t for t in thicknesses]
        elif remaining > 1e-6:
            thicknesses = list(thicknesses) + [remaining]
            if names is not None:
                names = list(names) + [None]

        current_level = self.start_offset
        new_sublayers = []
        for i, t in enumerate(thicknesses):
            new_sublayers.append(
                Layer.from_parent_start_end(
                    self,
                    current_level,
                    current_level + t,
                    name=names[i] if names is not None else None,
                    role=self.role,
                )
            )
            current_level += t

        self.sublayers = new_sublayers  # use setter to wire up
        return new_sublayers

    def merge_sublayer_tree(self, model):
        for element in self._sublayers:
            if element not in model.elements():
                model.add_element(element, parent=self)
            element.merge_sublayer_tree(model)

    def transformation_to_local(self):
        """Transformation from model space to this layer's local space."""
        return self.modeltransformation.inverse()

    def set_extension_plane(self, edge_index: int, plane: Plane):
        """Set an extension plane for an edge.  Propagates to all sublayers."""
        self.plate_geometry.set_extension_plane(edge_index, plane.transformed(self.transformation_to_local()))
        for sublayer in self.sublayers:
            sublayer.set_extension_plane(edge_index, plane)

    def apply_edge_extensions(self):
        """Move edge vertices onto the extension planes, then recurse to sublayers."""
        self.plate_geometry.apply_edge_extensions()
        for sublayer in self.sublayers:
            sublayer.apply_edge_extensions()

    def remove_blank_extension(self, edge_index: Optional[int] = None):
        """Remove any extension plane for the given edge index.  Propagates to all sublayers."""
        self.plate_geometry.remove_blank_extension(edge_index)
        for sublayer in self.sublayers:
            sublayer.remove_blank_extension(edge_index)

    # ------------------------------------------------------------------
    # compas_model.elements.Element abstract method implementations
    # ------------------------------------------------------------------

    def compute_aabb(self, inflate: float = 0.0) -> Box:
        vertices = self.outline_a.points + self.outline_b.points
        box = Box.from_points(vertices)
        box.xsize += inflate
        box.ysize += inflate
        box.zsize += inflate
        return box

    def compute_obb(self, inflate: float = 0.0) -> Box:
        obb = self.plate_geometry.compute_aabb(inflate)
        obb.transform(self.modeltransformation)
        return obb

    def compute_collision_mesh(self):
        return self.obb.to_mesh()

    def compute_modeltransformation(self):
        if not self.model:
            return self.transformation
        return super().compute_modeltransformation()

    def compute_modelgeometry(self):
        if not self.model:
            return self.elementgeometry.transformed(self.transformation)
        return super().compute_modelgeometry()

    def compute_elementgeometry(self, include_features: bool = True):
        # NOTE: features are not applied at the layer level; panel-level features are handled by Panel only.
        return self.plate_geometry.compute_shape()

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def get_outlines_from_parent(parent: Union[Panel, Layer], start_offset: float, end_offset: float):
        """Interpolate *parent*'s local outlines at the given panel-absolute levels.

        *parent* is either the :class:`~compas_arch.elements.Panel` (for root
        layers) or the enclosing :class:`Layer` (for sublayers).
        """
        parent_start = getattr(parent, "start_offset", 0.0)  # Panel has no start_offset: it starts at 0.
        relative_start = start_offset - parent_start
        relative_end = end_offset - parent_start

        local_outline_a = parent.plate_geometry.outline_a
        local_outline_b = parent.plate_geometry.outline_b

        offset_a = relative_start / parent.thickness
        if offset_a:
            layer_outline_a = Polyline([pt_a * (1.0 - offset_a) + pt_b * offset_a for pt_a, pt_b in zip(local_outline_a.points, local_outline_b.points)])
        else:
            layer_outline_a = local_outline_a

        offset_b = relative_end / parent.thickness
        layer_outline_b = Polyline([pt_a * (1.0 - offset_b) + pt_b * offset_b for pt_a, pt_b in zip(local_outline_a.points, local_outline_b.points)])
        return layer_outline_a, layer_outline_b


class LayerDefinition(Data):
    """Definition of a single layer slot within a :class:`LayerStructure`.

    ``LayerDefinition`` is the panel-agnostic description of one layer: its name, thickness
    fraction, and optional children.  A :class:`LayerStructure` holds a tree of
    ``LayerDefinition`` objects; when applied to a :class:`~compas_arch.elements.Panel`
    each ``LayerDefinition`` produces one geometry-bearing :class:`Layer` instance.

    Parameters
    ----------
    name : str, optional
        Human-readable identifier.
    thickness : float, optional
        Absolute thickness of this slot measured along the panel's thickness direction.
        When ``None`` the slot absorbs whatever thickness remains after all fixed siblings
        are summed.  At most one sibling at the same level may have ``thickness=None``.
    sublayer_defs : list[:class:`LayerDefinition`], optional
        Child slot definitions for nested layers.
    role : :class:`LayerRole` | str, optional
        The role of this slot.  Only root-level definitions may have a role.  A root
        definition without a role whose name is a role value (``"exterior"``, ``"core"``,
        ``"interior"``) gets that role when added to a :class:`LayerStructure`.

    Attributes
    ----------
    name : str or None
    thickness : float or None
    sublayer_defs : list[:class:`LayerDefinition`]
    role : :class:`LayerRole` or None
    layer_path : tuple[int, ...]
        Position in the :class:`LayerStructure` tree, e.g. ``(1,)`` for the second root
        slot or ``(1, 0)`` for its first child.  Set automatically by
        :class:`LayerStructure` when the structure is built.  Not serialized.
    """

    @property
    def __data__(self):
        return {
            "name": self.name,
            "thickness": self.thickness,
            "sublayer_defs": self.sublayer_defs,
            "role": self.role.value if self.role is not None else None,
        }

    def __init__(self, name=None, thickness=None, sublayer_defs=None, role=None):
        super().__init__()
        self.name = name
        self.thickness = thickness
        self.sublayer_defs = list(sublayer_defs) if sublayer_defs else []
        self.role = LayerRole(role) if role is not None else None
        self.layer_path = ()

    def __repr__(self):
        return "LayerDefinition(name={!r}, thickness={}, path={})".format(self.name, self.thickness, self.layer_path)


class LayerStructure(Data):
    """Panel-agnostic cross-section definition.

    A ``LayerStructure`` holds a tree of :class:`LayerDefinition` objects describing
    the layer slots.  It is shared across panels; :meth:`attach` creates bound
    :class:`Layer` instances for each specific panel.

    Root definitions can carry a :class:`LayerRole` (exterior, core, interior), which
    enables the matching properties on :class:`~compas_arch.elements.Panel`.  Each role
    may appear on at most one root definition; role layers can be subdivided, and their
    sublayers carry the same role.
    A sibling with ``thickness=None`` absorbs remaining thickness; at most one
    sibling at the same level may do so.

    Parameters
    ----------
    layer_defs : list[:class:`LayerDefinition`], optional
        Root-level layer definitions.  Defaults to a single core slot spanning the full
        panel thickness.

    Raises
    ------
    ValueError
        If a role appears on more than one root definition, or on a sublayer definition.
    """

    @property
    def __data__(self):
        return {"layer_defs": self.layer_defs}

    def __init__(self, layer_defs=None):
        super().__init__()
        self.layer_defs = list(layer_defs) if layer_defs else [LayerDefinition(name="core", role=LayerRole.CORE)]
        self._assign_roles()
        self._assign_paths(self.layer_defs, ())

    def __repr__(self):
        return "LayerStructure(layer_defs={!r})".format(self.layer_defs)

    def _assign_roles(self):
        """Give unroled root definitions named after a role that role, then validate roles."""
        for def_ in self.layer_defs:
            if def_.role is None and def_.name in LayerRole._value2member_map_:
                def_.role = LayerRole(def_.name)
        roles = [def_.role for def_ in self.layer_defs if def_.role is not None]
        duplicates = sorted({role.value for role in roles if roles.count(role) > 1})
        if duplicates:
            raise ValueError("Each layer role may appear on only one root layer definition; repeated: {}.".format(", ".join(duplicates)))
        for def_ in self.layer_defs:
            self._check_no_sublayer_roles(def_.sublayer_defs)

    def _check_no_sublayer_roles(self, defs):
        for def_ in defs:
            if def_.role is not None:
                raise ValueError("Only root layer definitions may have a role; sublayer {!r} has role {!r}.".format(def_.name, def_.role.value))
            self._check_no_sublayer_roles(def_.sublayer_defs)

    def _assign_paths(self, defs, prefix):
        for i, def_ in enumerate(defs):
            def_.layer_path = prefix + (i,)
            if def_.sublayer_defs:
                self._assign_paths(def_.sublayer_defs, prefix + (i,))

    def attach(self, panel):
        """Create and return bound :class:`Layer` instances for *panel*."""
        return self._create_layers(panel, self.layer_defs, 0.0, panel.thickness)

    @staticmethod
    def _sibling_spans(defs, start, total):
        """Yield ``(def, start, end)`` for sibling *defs* filling *total* thickness from *start*."""
        none_count = sum(1 for d in defs if d.thickness is None)
        if none_count > 1:
            raise ValueError("At most one LayerDefinition sibling may have thickness=None.")
        fixed_sum = sum(d.thickness for d in defs if d.thickness is not None)
        if fixed_sum > total + 1e-6:
            raise ValueError("Defined thicknesses ({:.4f}) exceed available thickness ({:.4f}).".format(fixed_sum, total))
        fill = total - fixed_sum

        current = start
        for def_ in defs:
            t = fill if def_.thickness is None else def_.thickness
            yield def_, current, current + t
            current += t

    def _create_layers(self, parent, defs, start, total, role=None):
        layers = []
        for def_, slot_start, slot_end in self._sibling_spans(defs, start, total):
            layer_role = def_.role or role  # sublayers carry the role of the root layer they subdivide
            layer = Layer.from_parent_start_end(parent, slot_start, slot_end, name=def_.name, layer_path=def_.layer_path, role=layer_role)
            if def_.sublayer_defs:
                layer.sublayers = self._create_layers(layer, def_.sublayer_defs, slot_start, slot_end - slot_start, role=layer_role)
            layers.append(layer)
        return layers

    def resolve(self, thickness):
        """Resolve every definition to absolute offsets for a panel of *thickness*, without building layers.

        This is the geometry-free counterpart of :meth:`attach`: the same slot
        arithmetic, so the offsets match the layers :meth:`attach` would create.

        Parameters
        ----------
        thickness : float
            Total panel thickness.  Resolves the ``thickness=None`` fill slot.

        Returns
        -------
        list[:class:`LayerSlot`]
            One slot per definition, depth first, parents before their sublayers.
        """
        slots = []

        def _walk(defs, start, total, role):
            for def_, slot_start, slot_end in self._sibling_spans(defs, start, total):
                slot_role = def_.role or role
                slots.append(LayerSlot(def_.layer_path, slot_role, def_.name, slot_start, slot_end))
                if def_.sublayer_defs:
                    _walk(def_.sublayer_defs, slot_start, slot_end - slot_start, slot_role)

        _walk(self.layer_defs, 0.0, thickness, None)
        return slots

    def get_path_for_role(self, role):
        """Return the :attr:`~LayerDefinition.layer_path` of the root definition with *role*, or ``None``.

        Parameters
        ----------
        role : :class:`LayerRole` | str
        """
        role = LayerRole(role)
        for def_ in self.layer_defs:
            if def_.role == role:
                return def_.layer_path
        return None

    def get_path_for_name(self, name):
        """Return the :attr:`~LayerDefinition.layer_path` of the first definition matching *name*, or ``None``."""
        return self._find_path(self.layer_defs, name, ())

    def _find_path(self, defs, name, prefix):
        for i, def_ in enumerate(defs):
            path = prefix + (i,)
            if def_.name == name:
                return path
            if def_.sublayer_defs:
                result = self._find_path(def_.sublayer_defs, name, path)
                if result is not None:
                    return result
        return None
