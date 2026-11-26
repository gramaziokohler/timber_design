"""Built-in panel types, and reading and writing panel types as JSON files."""

from __future__ import annotations

import os

from compas.data import json_dump
from compas.data import json_load
from timber_design_arch.elements import LayerDefinition
from timber_design_arch.elements import LayerRole
from timber_design_arch.elements import LayerStructure
from timber_design_arch.panel_features import LinearService
from timber_design_arch.panel_features import MEPPenetration
from timber_design_arch.panel_features import Niche
from timber_design_arch.panel_features import Opening

from timber_design_populator.detail_sets import FramedNicheDetailSet
from timber_design_populator.detail_sets import FramedOpeningDetailSet
from timber_design_populator.detail_sets import FramedPenetrationDetailSet
from timber_design_populator.detail_sets import LinearServiceDetailSet
from timber_design_populator.populator_agents.edge_agent import EdgeAgent
from timber_design_populator.populator_agents.plate_agent import PlateAgent
from timber_design_populator.populator_agents.stud_agent import StudAgent

from . import dataholz
from .panel_type import PanelType


def framed_detail_sets():
    """The detail sets of a framed panel: framed openings, penetrations and niches, and linear services.

    Returns
    -------
    dict[type, :class:`~timber_design_populator.DetailAgentSet`]
    """
    return {
        Opening: FramedOpeningDetailSet(),
        MEPPenetration: FramedPenetrationDetailSet(),
        Niche: FramedNicheDetailSet(),
        LinearService: LinearServiceDetailSet(),
    }


def stud_wall_type(
    layer_structure=None,
    name="stud_wall",
    standard_beam_width=None,
    stud_spacing=None,
    stud_width=None,
    edge_stud_width=None,
    top_plate_beam_width=None,
    bottom_plate_beam_width=None,
    standard_beam_width_increment=None,
    joint_rule_overrides=None,
    default_detail_sets=None,
    max_distance=None,
    exterior_sheeting_thickness=None,
    interior_sheeting_thickness=None,
):
    """A generic stud wall for any cross-section with a core: framing in the core, one plate on each other role layer.

    The cross-section is *layer_structure*, or else built from the sheeting thicknesses (see
    :func:`stud_wall_layers`).  The exterior and interior role layers, when it has them, each get a
    :class:`~timber_design_populator.PlateAgent`; the core gets an
    :class:`~timber_design_populator.EdgeAgent` and a :class:`~timber_design_populator.StudAgent`.
    Features are built with :func:`framed_detail_sets`.  This is what
    :func:`~timber_design_populator.stud_panel` builds.

    Parameters
    ----------
    layer_structure : :class:`~timber_design_arch.elements.LayerStructure`, optional
        The cross-section.  Default: :func:`stud_wall_layers` of the sheeting thicknesses.
    name : str, optional
    standard_beam_width, stud_spacing, stud_width, edge_stud_width, top_plate_beam_width, bottom_plate_beam_width, standard_beam_width_increment, joint_rule_overrides, default_detail_sets, max_distance : optional
        See :func:`~timber_design_populator.stud_panel`.  ``stud_spacing=0``: no studs.
    exterior_sheeting_thickness, interior_sheeting_thickness : float, optional
        Without *layer_structure*: the thicknesses of the exterior and interior sheeting layers.
        Not allowed with *layer_structure*.

    Returns
    -------
    :class:`PanelType`
    """
    if layer_structure is None:
        layer_structure = stud_wall_layers(exterior_sheeting_thickness, interior_sheeting_thickness)
    elif exterior_sheeting_thickness or interior_sheeting_thickness:
        raise ValueError("Give a stud wall either a layer structure or sheeting thicknesses, not both.")
    core = layer_structure.get_path_for_role(LayerRole.CORE)
    if core is None:
        raise ValueError("A stud wall needs a core layer to frame.")
    agents = []
    for role in (LayerRole.EXTERIOR, LayerRole.INTERIOR):
        path = layer_structure.get_path_for_role(role)
        if path is not None:
            agents.append(PlateAgent(tuple(path)))
    agents.append(
        EdgeAgent(
            tuple(core),
            standard_beam_width_increment=standard_beam_width_increment,
            edge_stud_width=edge_stud_width,
            top_plate_beam_width=top_plate_beam_width,
            bottom_plate_beam_width=bottom_plate_beam_width,
        )
    )
    if stud_spacing is None or stud_spacing:
        agents.append(StudAgent(tuple(core), stud_width=stud_width, stud_spacing=stud_spacing))
    detail_sets = framed_detail_sets()
    detail_sets.update(default_detail_sets or {})
    return PanelType(
        name,
        layer_structure,
        agents=agents,
        default_detail_sets=detail_sets,
        standard_beam_width=standard_beam_width,
        joint_rule_overrides=joint_rule_overrides,
        max_distance=max_distance,
    )


def stud_wall_layers(exterior_sheeting_thickness=None, interior_sheeting_thickness=None, core_material=None, sheeting_material=None):
    """The cross-section of a sheeted stud wall: exterior sheeting, a core that fills the rest, interior sheeting.

    Parameters
    ----------
    exterior_sheeting_thickness, interior_sheeting_thickness : float, optional
        Unset or 0: no sheeting on that side.
    core_material, sheeting_material : str, optional

    Returns
    -------
    :class:`~timber_design_arch.elements.LayerStructure`
        Exterior first.  The core has no fixed thickness, so the wall fits any panel thicker
        than its sheeting.
    """
    defs = []
    if exterior_sheeting_thickness:
        defs.append(LayerDefinition("exterior", exterior_sheeting_thickness, role=LayerRole.EXTERIOR, material=sheeting_material))
    defs.append(LayerDefinition("core", None, role=LayerRole.CORE, material=core_material))
    if interior_sheeting_thickness:
        defs.append(LayerDefinition("interior", interior_sheeting_thickness, role=LayerRole.INTERIOR, material=sheeting_material))
    return LayerStructure(defs)


def _stud_wall(standard_beam_width=60.0, **kwargs):
    """The library's stud wall: :func:`stud_wall_type` with 60 wide framing by default."""
    return stud_wall_type(standard_beam_width=standard_beam_width, **kwargs)


#: Where the panel types shipped as JSON files live: one ``<name>.json`` per type.
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

#: The built-in types also shipped as JSON files (their factories' defaults), see :func:`write_panel_type_files`.
BUNDLED_TYPES = ("awrhho05b", "awrhhi01a", "awmhhi01a")

#: Factories of the built-in panel types, by name.  Each takes keyword arguments to vary it.
PANEL_TYPES = {
    "stud_wall": _stud_wall,
    "awrhho05b": dataholz.awrhho05b,
    "awrhhi01a": dataholz.awrhhi01a,
    "awmhhi01a": dataholz.awmhhi01a,
}


def list_panel_types():
    """The names of the built-in panel types.

    Returns
    -------
    list[str]
    """
    return sorted(PANEL_TYPES)


def get_panel_type(name, **kwargs):
    """A built-in panel type by name.

    Parameters
    ----------
    name : str
        One of :func:`list_panel_types`.
    kwargs : dict, optional
        Passed to the type's factory, e.g. ``stud_spacing=400``.

    Returns
    -------
    :class:`PanelType`
    """
    if name not in PANEL_TYPES:
        raise KeyError("No built-in panel type {!r}; there are: {}.".format(name, ", ".join(list_panel_types())))
    return PANEL_TYPES[name](**kwargs)


def list_panel_type_files():
    """The panel types shipped as JSON files, by name.

    Returns
    -------
    dict[str, str]
        Name -> file path.
    """
    if not os.path.isdir(DATA_DIR):
        return {}
    return {os.path.splitext(f)[0]: os.path.join(DATA_DIR, f) for f in sorted(os.listdir(DATA_DIR)) if f.endswith(".json")}


def write_panel_type_files(directory=None):
    """Write the JSON file of every type in :data:`BUNDLED_TYPES`, from its factory's defaults.

    Run it after changing one of those factories, to update the shipped files.

    Parameters
    ----------
    directory : str, optional
        Default: :data:`DATA_DIR`.

    Returns
    -------
    list[str]
        The files written.
    """
    directory = directory or DATA_DIR
    if not os.path.isdir(directory):
        os.makedirs(directory)
    paths = []
    for name in BUNDLED_TYPES:
        path = os.path.join(directory, name + ".json")
        save_panel_type(get_panel_type(name), path)
        paths.append(path)
    return paths


def save_panel_type(panel_type, filepath):
    """Write *panel_type* to a JSON file, e.g. to share a type made in Grasshopper."""
    json_dump(panel_type, filepath, pretty=True)


def load_panel_type(filepath):
    """Read a panel type from a JSON file written by :func:`save_panel_type`.

    Parameters
    ----------
    filepath : str
        The file, or the name of a shipped type (see :func:`list_panel_type_files`).

    Returns
    -------
    :class:`PanelType`
    """
    if not os.path.isfile(filepath) and filepath in list_panel_type_files():
        filepath = list_panel_type_files()[filepath]
    panel_type = json_load(filepath)
    if not isinstance(panel_type, PanelType):
        raise TypeError("{} holds a {}, not a PanelType.".format(filepath, type(panel_type).__name__))
    return panel_type
