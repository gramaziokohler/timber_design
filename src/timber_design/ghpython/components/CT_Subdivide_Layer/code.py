# r: timber_design>=0.1.0
"""Subdivides a node in a LayerStructure tree at a given path."""

# flake8: noqa
import Grasshopper
import System

from compas_timber.elements.layer import LayerDef
from compas_timber.elements.layer import LayerStructure


def _deep_copy_def(d):
    return LayerDef(
        name=d.name,
        thickness=d.thickness,
        sublayer_defs=[_deep_copy_def(s) for s in d.sublayer_defs],
    )


def _deep_copy_structure(ls):
    return LayerStructure(layer_defs=[_deep_copy_def(d) for d in ls.layer_defs])


def _navigate(root_structure, path_indices):
    """Navigate the LayerDef tree inside *root_structure* and return the target LayerDef."""
    if not path_indices:
        raise IndexError("Path must have at least one index.")
    defs = root_structure.layer_defs
    node = defs[path_indices[0]]
    for idx in path_indices[1:]:
        if not node.sublayer_defs:
            raise IndexError("Path index {} out of range: node has no sublayer_defs.".format(idx))
        node = node.sublayer_defs[idx]
    return node


class SubdivideLayer(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(
        self,
        path,
        layer_structure,
        thicknesses: System.Collections.Generic.List[object],
        names: System.Collections.Generic.List[object],
    ):
        if layer_structure is None or path is None or not thicknesses:
            return None

        if hasattr(path, "Indices"):
            path_indices = tuple(int(i) for i in path.Indices)
        else:
            path_indices = tuple(int(i) for i in path)

        thicknesses = [float(t) if t is not None else None for t in thicknesses]
        names = list(names) if names else []

        root_copy = _deep_copy_structure(layer_structure)
        target_def = _navigate(root_copy, path_indices)

        target_def.sublayer_defs = [
            LayerDef(name=names[i] if i < len(names) else None, thickness=t)
            for i, t in enumerate(thicknesses)
        ]

        # Re-assign paths so the output structure has correct layer_path on every def
        root_copy._assign_paths(root_copy.layer_defs, ())

        return root_copy
