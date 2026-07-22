# r: timber_design>=0.1.0
"""Filters and displays elements from a TimberModel."""

import Grasshopper
import System
from compas.scene import Scene

from compas_timber.elements import Beam
from compas_timber.elements import Layer
from compas_timber.elements import Panel
from compas_timber.base import TimberElement


class FilterDisplay(Grasshopper.Kernel.GH_ScriptInstance):
    @property
    def component(self):
        return ghenv.Component  # type: ignore

    def RunScript(self,
            Model,
            layer_filter: System.Collections.Generic.List[object],
            group_filter: System.Collections.Generic.List[object],
            display_level: str,
            group_space: bool,
            CreateGeometry: bool):
        if Model is None:
            return None

        layer_paths = []
        layer_filter = layer_filter or []
        for l in layer_filter:
            if isinstance(l, Layer):
                layer_paths.append(l.layer_path)
            if isinstance(l, Grasshopper.Kernel.Data.GH_Path):
                layer_paths.append(tuple([i for i in l.Indices]))
            if isinstance(l, str):
                lps = set()
                for layer in Model.layers:
                    if layer.name == l:
                        lps.add(layer.layer_path)
                layer_paths.extend(list(lps))

        Model.process_joinery()

        geometry = get_filtered_geometry(Model, group_filter, layer_paths, display_level, group_space, create_geometry=CreateGeometry)

        return convert_geometry(geometry)


def convert_geometry(geometries):
    scene = Scene()
    for g in geometries:
        scene.add(g)
    return scene.draw()

def get_element_geometry(element, create_geometry):
    if isinstance(element, Beam) and not create_geometry:
        return element.blank
    return element.modelgeometry


def get_filtered_geometry(model, group_filters, layer_paths, display_level, group_space, create_geometry):
    geometries = []
    if group_filters:
        for gf in group_filters:
            gf_elements = get_filtered_element_and_children(gf, layer_paths, display_level)
            for element in gf_elements:
                geometry = get_element_geometry(element, create_geometry)
                if group_space:
                    geometries.append(geometry.transformed(gf.modeltransformation.inverse()))
                else:
                    geometries.append(geometry)
    else:
        for e in model.elements():
            if is_display_level(e, display_level) and is_on_layer(e, layer_paths):
                geometries.append(get_element_geometry(e, create_geometry))


    return geometries


def get_filtered_element_and_children(element, layer_paths, display_level):
    elements = []
    def walk(e):
        if is_display_level(e, display_level) and is_on_layer(e, layer_paths):
            elements.append(e)
        for c in e.children:
            walk(c)
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
