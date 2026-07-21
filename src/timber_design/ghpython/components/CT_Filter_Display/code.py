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
            CreateGeometry: bool):
        if Model is None:
            return None

        layer_paths = []
        for l in layer_filter:
            if isinstance(l, Layer):
                layer_paths.append(l.layer_path)
            if isinstance(l, Grasshopper.Kernel.Data.GH_Path):
                layer_paths.append(tuple([i for i in l.Indices]))


        Model.process_joinery()

        elements = get_filtered_elements(Model, group_filter, layer_paths, display_level)


        return get_geometry(elements, CreateGeometry)


def get_geometry(elements, create_geometry):
    scene = Scene()
    for element in elements:
        if create_geometry:
            scene.add(element.modelgeometry)
        else:
            if isinstance(element, Beam):
                scene.add(element.blank)
            else:
                scene.add(element.modelgeometry)

    return scene.draw()


def get_filtered_elements(model, group_filters, layer_paths, display_level):
    elements = []
    if group_filters:
        for gf in group_filters:
            elements.extend(get_filtered_element_and_children(gf, layer_paths, display_level))
    else:
        elements.extend(e for e in model.elements if is_display_level(e, display_level) and is_on_layer(e, layer_paths))
    return elements


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
