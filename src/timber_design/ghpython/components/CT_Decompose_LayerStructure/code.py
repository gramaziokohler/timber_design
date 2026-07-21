# r: timber_design>=0.1.0
"""Exposes each node in a LayerStructure as a named output path."""

# flake8: noqa
import Grasshopper

from timber_design.ghpython.ghcomponent_helpers import manage_cpython_dynamic_output_params


def _collect(layer_def, parent_name=None):
    """Yield (output_name, path_tuple) for every LayerDefinition in the tree."""
    out_name = (layer_def.name or str(layer_def.layer_path[-1])) if parent_name is None else "{}_{}".format(parent_name, layer_def.layer_path[-1])
    yield out_name, layer_def.layer_path
    for child in layer_def.sublayer_defs:
        yield from _collect(child, out_name)


class DecomposeLayerStructure(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(self, layer_structure):
        if layer_structure is None:
            return

        pairs = []
        for layer_def in layer_structure.layer_defs:
            pairs.extend(_collect(layer_def))

        if not pairs:
            return

        names = [p[0] for p in pairs]
        paths = [p[1] for p in pairs]

        current = [ghenv.Component.Params.Output[i].Name for i in range(ghenv.Component.Params.Output.Count)]
        if current != names:
            manage_cpython_dynamic_output_params(names, ghenv)
            return

        return tuple(paths)
