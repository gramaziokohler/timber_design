# r: timber_design>=0.1.0
"""Filters and displays elements from a TimberModel."""

import Grasshopper
import System
from compas.scene import Scene

from compas_timber.elements import Beam
from compas_timber.elements import Layer
from compas_timber.elements import Panel


class FilterDisplay(Grasshopper.Kernel.GH_ScriptInstance):
    @property
    def component(self):
        return ghenv.Component  # type: ignore

    def RunScript(
        self,
        Model,
        filter_paths: System.Collections.Generic.List[object],
        display_level: str,
        CreateGeometry: bool,
    ):
        if Model is None:
            return None

        return get_geometry(Model, filter_paths, display_level, CreateGeometry)


def get_geometry(model, filter_paths, display_level, create_geometry):
    scene = Scene()

    if filter_paths:
        elements = get_filtered_elements(model, filter_paths)
    else:
        elements = list(model.elements())

    for element in elements:
        is_panel = isinstance(element, Panel)
        is_layer = isinstance(element, Layer)

        if display_level == "panel":
            if not is_panel:
                continue
        elif display_level == "layer":
            if not is_layer:
                continue
        else:
            if is_panel or is_layer:
                continue

        if create_geometry:
            scene.add(element.geometry)
        else:
            if isinstance(element, Beam):
                scene.add(element.blank)
            else:
                scene.add(element.geometry)

    return scene.draw()


def get_filtered_elements(model, filter_paths):
    from compas_model.elements.element import Element
    elements = []
    for fp in filter_paths:
        if isinstance(fp, Layer):
            elements.append(fp)
            lp = fp.layer_path
            for layer in model.layers:
                if layer.layer_path == lp:
                    elements.extend(get_all_children(layer))
        elif isinstance(fp, Element):
            elements.append(fp)
            elements.extend(get_all_children(fp))
        elif isinstance(fp, tuple):
            for layer in model.layers:
                if layer.layer_path == fp:
                    elements.append(layer)
                    elements.extend(get_all_children(layer))
        elif isinstance(fp, str):
            for layer in model.layers:
                if layer.name == fp:
                    elements.append(layer)
                    elements.extend(get_all_children(layer))
    return elements


def get_all_children(element):
    elements = []

    def walk(p):
        for c in p.children:
            elements.append(c)
            walk(c)

    walk(element)
    return elements
