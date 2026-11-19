# r: timber_design>=0.3.1
"""Filters and displays elements from a TimberModel, optionally in the local space of a group (e.g. a panel)."""

import Grasshopper
import System
from compas.geometry import Translation
from compas.scene import Scene
from compas_timber.base import TimberElement
from compas_timber.elements import Beam
from compas_timber.elements import Layer
from compas_timber.elements import Panel


class PanelViewer(Grasshopper.Kernel.GH_ScriptInstance):
    @property
    def component(self):
        return ghenv.Component  # type: ignore

    def RunScript(
        self,
        Model,
        layer_filter: System.Collections.Generic.List[object],
        group_filter: System.Collections.Generic.List[object],
        display_level: str,
        group_space: bool,
        CreateGeometry: bool,
    ):
        if Model is None:
            return None

        layer_paths = []
        layer_filter = layer_filter or []
        for lf in layer_filter:
            if isinstance(lf, Layer):
                layer_paths.append(lf.layer_path)
            if isinstance(lf, Grasshopper.Kernel.Data.GH_Path):
                layer_paths.append(tuple([i for i in lf.Indices]))
            if isinstance(lf, str):
                lps = set()
                for layer in Model.layers:
                    if layer.name == lf:
                        lps.add(layer.layer_path)
                layer_paths.extend(list(lps))

        groups = []
        for gf in group_filter or []:
            if gf is None:
                continue
            group = resolve_in_model(Model, gf)
            if group is None:
                self.component.AddRuntimeMessage(
                    Grasshopper.Kernel.GH_RuntimeMessageLevel.Warning,
                    "group_filter element {} is not in the Model and is skipped.".format(gf),
                )
                continue
            groups.append(group)

        Model.process_joinery()
        geometry = get_filtered_geometry(Model, groups, layer_paths, display_level, group_space, create_geometry=CreateGeometry)

        return convert_geometry(geometry)


def resolve_in_model(model, element):
    """The instance of `element` that lives in `model`.

    Upstream components hand out their own instances: CT_Populate_Model, for one, works on a JSON
    copy of the model, so a panel or layer wired in from before it is not the one in `Model`.
    Such an instance has no (or the wrong) children, and outside a model a Layer's
    modeltransformation drops its parent panel's frame, so group space lands in the wrong place.
    Looking it up by guid gives the model's own instance.
    """
    if not hasattr(element, "guid"):
        return None
    return model.get_element(str(element.guid))


def convert_geometry(geometries):
    scene = Scene()
    for g in geometries:
        scene.add(g)
    return scene.draw()


def get_element_geometry(element, create_geometry):
    if isinstance(element, Beam) and not create_geometry:
        return element.blank
    return element.modelgeometry


def get_filtered_geometry(model, groups, layer_paths, display_level, group_space, create_geometry):
    geometries = []
    if groups:
        for group in groups:
            to_group = group_space_transformation(group)
            for element in get_filtered_element_and_children(group, layer_paths, display_level):
                geometry = get_element_geometry(element, create_geometry)
                if group_space:
                    geometries.append(geometry.transformed(to_group))
                else:
                    geometries.append(geometry)
    else:
        for e in model.elements():
            if is_display_level(e, display_level) and is_on_layer(e, layer_paths):
                geometries.append(get_element_geometry(e, create_geometry))

    return geometries


def group_space_transformation(group):
    """Model space -> group space, with the group's geometry sitting on world XY at the origin.

    Inverting the group's model transformation alone places the group *frame* at world XY, but
    that frame is not necessarily the corner of the group's geometry: panel joints trim a panel's
    (and its layers') outlines after the frame was defined, so e.g. a panel butting into another
    one starts one panel thickness along its local x-axis. The local bounding-box corner of the
    group's outlines is therefore moved to the origin as well.
    """
    to_local = group.modeltransformation.inverse()
    plate_geometry = getattr(group, "plate_geometry", None)
    if plate_geometry is None:
        return to_local
    points = list(plate_geometry.outline_a.points) + list(plate_geometry.outline_b.points)
    corner = [min(p[i] for p in points) for i in range(3)]
    return Translation.from_vector([-c for c in corner]) * to_local


def get_filtered_element_and_children(element, layer_paths, display_level):
    elements = []

    def walk(e):
        if is_display_level(e, display_level) and is_on_layer(e, layer_paths):
            elements.append(e)
        if e.treenode:
            for c in e.children:
                walk(c)

    if element:
        walk(element)
    return elements


def is_display_level(element, display_level):
    if display_level == "panel" and isinstance(element, Panel):
        return True
    if display_level == "layer" and isinstance(element, Layer):
        return True
    if display_level == "timber" and isinstance(element, TimberElement):
        return True
    return False


def is_on_layer(element, layer_paths):
    if not layer_paths:
        return True

    def walk_up(el):
        if not el:
            return False
        if not isinstance(el, Layer):
            return walk_up(el.parent)
        for lp in layer_paths:
            if len(el.layer_path) >= len(lp) and all(el.layer_path[i] == lp[i] for i in range(len(lp))):
                return True
        return False

    return walk_up(element)
