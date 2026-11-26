try:
    import Grasshopper  # type: ignore
    import Rhino  # type: ignore
    import RhinoCodePluginGH.Parameters  # type: ignore
except (ImportError, SyntaxError):
    pass


def warning(component, message):
    """Add a warning message to the component.

    Parameters
    ----------
    component : Grasshopper.Kernel.IGH_Component
        The component instance. Pre-Rhino8 use `self`. Post-Rhino8 use `ghenv.Component`.
    message : str
        The message to display.
    """
    component.AddRuntimeMessage(Grasshopper.Kernel.GH_RuntimeMessageLevel.Warning, message)


def error(component, message):
    """Add an error message to the component.

    Parameters
    ----------
    component : Grasshopper.Kernel.IGH_Component
        The component instance. Pre-Rhino8 use `self`. Post-Rhino8 use `ghenv.Component`.
    message : str
        The message to display.
    """
    component.AddRuntimeMessage(Grasshopper.Kernel.GH_RuntimeMessageLevel.Error, message)


def remark(component, message):
    """Add a remark message to the component.

    Parameters
    ----------
    component : Grasshopper.Kernel.IGH_Component
        The component instance. Pre-Rhino8 use `self`. Post-Rhino8 use `ghenv.Component`.
    message : str
        The message to display.
    """
    component.AddRuntimeMessage(Grasshopper.Kernel.GH_RuntimeMessageLevel.Remark, message)


def message(component, message):
    """Add a text that will appear under the component.

    Parameters
    ----------
    component : Grasshopper.Kernel.IGH_Component
        The component instance. Pre-Rhino8 use `self`. Post-Rhino8 use `ghenv.Component`.
    message : str
        The message to display.
    """
    component.Message = message


def list_input_valid(component, Param, name):
    if not Param:
        component.AddRuntimeMessage(Grasshopper.Kernel.GH_RuntimeMessageLevel.Warning, "Input parameter %s failed to collect data" % name)
    else:
        if all([_ is None for _ in Param]):
            component.AddRuntimeMessage(Grasshopper.Kernel.GH_RuntimeMessageLevel.Warning, "Input parameter %s failed to collect data" % name)
        elif any([_ is None for _ in Param]):
            component.AddRuntimeMessage(Grasshopper.Kernel.GH_RuntimeMessageLevel.Remark, "Input parameter %s contains some Null values" % name)
            return True
        else:
            return True
    return False


def item_input_valid(component, Param, name):
    if not Param:
        component.AddRuntimeMessage(Grasshopper.Kernel.GH_RuntimeMessageLevel.Warning, "Input parameter %s failed to collect data" % name)
    else:
        return True
    return False


def get_leaf_subclasses(cls):
    subclasses = []
    for subclass in cls.__subclasses__():
        if not get_leaf_subclasses(subclass):
            subclasses.append(subclass)
        subclasses.extend(get_leaf_subclasses(subclass))
    return subclasses


def get_createable_joints():
    """Returns the list of creatable joint types.

    TODO: this is currently hardcoded but can be done duynamically, however, a better distinction should be made first between abstract and concrete joints.
    TOOD: a typical way of doing that would be to declare the non-creatable base classes abstract and filter those.
    """
    from compas_timber.connections import BallNodeJoint
    from compas_timber.connections import LButtJoint
    from compas_timber.connections import LFrenchRidgeLapJoint
    from compas_timber.connections import LLapJoint
    from compas_timber.connections import LMiterJoint
    from compas_timber.connections import LTenonMortiseJoint
    from compas_timber.connections import TBirdsmouthJoint
    from compas_timber.connections import TButtJoint
    from compas_timber.connections import TDovetailJoint
    from compas_timber.connections import TLapJoint
    from compas_timber.connections import TOliGinaJoint
    from compas_timber.connections import TStepJoint
    from compas_timber.connections import TTenonMortiseJoint
    from compas_timber.connections import XLapJoint
    from compas_timber.connections import XNotchJoint
    from compas_timber.connections import YButtJoint

    return [
        TButtJoint,
        LButtJoint,
        TButtJoint,
        TStepJoint,
        TBirdsmouthJoint,
        LMiterJoint,
        XLapJoint,
        XNotchJoint,
        TLapJoint,
        LLapJoint,
        LFrenchRidgeLapJoint,
        TDovetailJoint,
        BallNodeJoint,
        LTenonMortiseJoint,
        TTenonMortiseJoint,
        YButtJoint,
        TOliGinaJoint,
    ]


def add_gh_param(
    name, io, ghenv, index=None
):  # we could also make beam_names a dict with more info e.g. NickName, Description, Access, hints, etc. this would be defined in joint_options components
    """Adds a parameter to the Grasshopper component.

    Parameters
    ----------
    name : str
        The name of the parameter.
    io : str
        The direction of the parameter. Either "Input" or "Output".
    ghenv : object
        The Grasshopper environment object.

    Returns
    -------
    None

    """
    assert io in ("Output", "Input")
    params = [param.NickName for param in getattr(ghenv.Component.Params, io)]
    if name not in params:
        param = Grasshopper.Kernel.Parameters.Param_GenericObject()
        param.NickName = name
        param.Name = name
        param.Description = name
        param.Access = Grasshopper.Kernel.GH_ParamAccess.item
        param.Optional = True
        if index is None:
            index = getattr(ghenv.Component.Params, io).Count

        registers = dict(Input="RegisterInputParam", Output="RegisterOutputParam")
        getattr(ghenv.Component.Params, registers[io])(param, index)
        ghenv.Component.Params.OnParametersChanged()


def clear_gh_params(ghenv, permanent_param_count=1):
    """Clears all input parameters from the component.

    Parameters
    ----------
    ghenv : object
        The Grasshopper environment object.
    permanent_param_count : int, optional
        The number of parameters that should not be deleted. Default is 1.

    Returns
    -------
    None

    """
    changed = False
    while len(ghenv.Component.Params.Input) > permanent_param_count:
        ghenv.Component.Params.UnregisterInputParameter(ghenv.Component.Params.Input[len(ghenv.Component.Params.Input) - 1], True)
        changed = True
    ghenv.Component.Params.OnParametersChanged()
    return changed


def rename_gh_input(input_name, index, ghenv):
    """Renames a parameter in the Grasshopper component.

    Parameters
    ----------
    ghenv : object
        The Grasshopper environment object.
    input_name : str
        The new name of the parameter.
    index : int
        The index of the parameter to rename.

    Returns
    -------
    None

    """
    param = ghenv.Component.Params.Input[index]
    param.NickName = input_name
    param.Name = input_name
    param.Description = input_name
    ghenv.Component.Params.OnParametersChanged()


def rename_gh_output(output_name, index, ghenv):
    """Renames a parameter in the Grasshopper component.

    Parameters
    ----------
    output_name : str
        The new name of the parameter.
    index : int
        The index of the parameter to rename.
    ghenv : object
        The Grasshopper environment object.

    Returns
    -------
    None

    """
    param = ghenv.Component.Params.Output[index]
    param.NickName = output_name
    param.Name = output_name
    param.Description = output_name
    ghenv.Component.Params.OnParametersChanged()


def manage_dynamic_params(input_names, ghenv, rename_count=0, permanent_param_count=0, keep_connections=True):
    """Clears all input parameters from the component.

    Parameters
    ----------
    input_names : list(str)
        The names of the input parameters.
    ghenv : object
        The Grasshopper environment object.
    rename_count : int, optional
        The number of parameters that should be renamed. Default is 0.
    permanent_param_count : int, optional
        The number of parameters that should not be deleted. Default is 0.

    Returns
    -------
    None

    """
    if not input_names:  # if no names are input
        clear_gh_params(ghenv, permanent_param_count)
        return
    else:
        if keep_connections:
            to_remove = []
            for param in ghenv.Component.Params.Input[permanent_param_count + rename_count :]:
                if param.Name not in input_names:
                    to_remove.append(param)
            for param in to_remove:
                param.IsolateObject()
                ghenv.Component.Params.UnregisterInputParameter(param, True)
            for i, name in enumerate(input_names):
                if i < rename_count:
                    rename_gh_input(name, i + permanent_param_count, ghenv)
                elif name not in [param.Name for param in ghenv.Component.Params.Input]:
                    add_gh_param(name, "Input", ghenv, index=i + permanent_param_count)

        else:
            register_params = False
            if len(ghenv.Component.Params.Input) == len(input_names) + permanent_param_count:  # if param count matches beam_names count
                for i, name in enumerate(input_names):
                    if ghenv.Component.Params.Input[i + permanent_param_count].Name != name:  # if param names don't match
                        register_params = True
                        break
            else:
                register_params = True
            if register_params:
                clear_gh_params(ghenv, permanent_param_count + rename_count)  # we could consider renaming params if we don't want to disconnect GH component inputs
                for i, name in enumerate(input_names):
                    if i < permanent_param_count:
                        continue
                    elif i < rename_count:
                        rename_gh_input(name, i, ghenv)
                    else:
                        add_gh_param(name, "Input", ghenv)


def list_input_valid_cpython(ghenv, Param, name):
    if not Param:
        ghenv.Component.AddRuntimeMessage(Grasshopper.Kernel.GH_RuntimeMessageLevel.Warning, "Input parameter %s failed to collect data" % name)
    else:
        if all([_ is None for _ in Param]):
            ghenv.Component.AddRuntimeMessage(Grasshopper.Kernel.GH_RuntimeMessageLevel.Warning, "Input parameter %s failed to collect data" % name)
        elif any([_ is None for _ in Param]):
            ghenv.Component.AddRuntimeMessage(Grasshopper.Kernel.GH_RuntimeMessageLevel.Remark, "Input parameter %s contains some Null values" % name)
            return True
        else:
            return True
    return False


def item_input_valid_cpython(ghenv, Param, name):
    if not Param and Param != 0:
        ghenv.Component.AddRuntimeMessage(Grasshopper.Kernel.GH_RuntimeMessageLevel.Warning, "Input parameter %s failed to collect data" % name)
    else:
        return True
    return False


def add_cpython_gh_param(
    name, io, ghenv, index=None
):  # we could also make beam_names a dict with more info e.g. NickName, Description, Access, hints, etc. this would be defined in joint_options components
    """Adds a parameter to the Grasshopper component.

    Parameters
    ----------
    name : str
        The name of the parameter.
    io : str
        The direction of the parameter. Either "Input" or "Output".
    ghenv : object
        The Grasshopper environment object.

    Returns
    -------
    None

    """
    assert io in ("Output", "Input")
    existing_param_names = []
    for i in range(len(ghenv.Component.Params.Input)):
        existing_param_names.append(ghenv.Component.Params.Input[i].Name)
    if name not in existing_param_names:
        param = RhinoCodePluginGH.Parameters.ScriptVariableParam()
        param.NickName = name
        param.Name = name
        param.Description = name
        param.Access = Grasshopper.Kernel.GH_ParamAccess.item
        param.Optional = True
        if io == "Input":
            if index is None:
                index = ghenv.Component.Params.Input.Count
            ghenv.Component.Params.RegisterInputParam(param, index)
        else:
            if index is None:
                index = ghenv.Component.Params.Output.Count
            ghenv.Component.Params.RegisterOutputParam(param, index)
        ghenv.Component.VariableParameterMaintenance()
        ghenv.Component.Params.OnParametersChanged()


def clear_cpython_gh_params(ghenv, permanent_param_count=1):
    """Clears all input parameters from the component.

    Parameters
    ----------
    ghenv : object
        The Grasshopper environment object.
    permanent_param_count : int, optional
        The number of parameters that should not be deleted. Default is 1.

    Returns
    -------
    None

    """
    changed = False
    while len(ghenv.Component.Params.Input) > permanent_param_count:
        ghenv.Component.Params.UnregisterInputParameter(ghenv.Component.Params.Input[len(ghenv.Component.Params.Input) - 1], True)
        changed = True
    ghenv.Component.VariableParameterMaintenance()
    ghenv.Component.Params.OnParametersChanged()
    return changed


def rename_cpython_gh_input(input_name, index, ghenv):
    """Renames a parameter in the Grasshopper component.

    Parameters
    ----------
    ghenv : object
        The Grasshopper environment object.
    input_name : str
        The new name of the parameter.
    index : int
        The index of the parameter to rename.

    Returns
    -------
    None

    """
    param = ghenv.Component.Params.Input[index]
    param.NickName = input_name
    param.Name = input_name
    param.Description = input_name
    ghenv.Component.VariableParameterMaintenance()
    ghenv.Component.Params.OnParametersChanged()


def rename_cpython_gh_output(output_name, index, ghenv):
    """Renames a parameter in the Grasshopper component.

    Parameters
    ----------
    output_name : str
        The new name of the parameter.
    index : int
        The index of the parameter to rename.
    ghenv : object
        The Grasshopper environment object.

    Returns
    -------
    None

    """
    param = ghenv.Component.Params.Output[index]
    param.NickName = output_name
    param.Name = output_name
    param.Description = output_name
    ghenv.Component.VariableParameterMaintenance()
    ghenv.Component.Params.OnParametersChanged()


def manage_cpython_dynamic_params(input_names, ghenv, rename_count=0, permanent_param_count=0, keep_connections=True):
    """Clears all input parameters from the component.

    Parameters
    ----------
    input_names : list(str)
        The names of the input parameters.
    ghenv : object
        The Grasshopper environment object.
    rename_count : int, optional
        The number of parameters that should be renamed. Default is 0.
    permanent_param_count : int, optional
        The number of parameters that should not be deleted. Default is 0.

    Returns
    -------
    None

    """
    if not input_names:  # if no names are input
        clear_cpython_gh_params(ghenv, permanent_param_count)
        return
    else:
        if keep_connections:
            to_remove = []
            for i in range((permanent_param_count + rename_count), len(ghenv.Component.Params.Input)):
                if ghenv.Component.Params.Input[i].Name not in input_names:
                    to_remove.append(ghenv.Component.Params.Input[i])
            for param in to_remove:
                ghenv.Component.Params.UnregisterInputParameter(param, True)

            for i, name in enumerate(input_names):
                if i < rename_count:
                    rename_cpython_gh_input(name, i + permanent_param_count, ghenv)
                else:
                    add_cpython_gh_param(name, "Input", ghenv, index=i + permanent_param_count)

        else:
            register_params = False
            if len(ghenv.Component.Params.Input) == len(input_names) + permanent_param_count:  # if param count matches beam_names count
                for i, name in enumerate(input_names):
                    if ghenv.Component.Params.Input[i + permanent_param_count].Name != name:  # if param names don't match
                        register_params = True
                        break
            else:
                register_params = True
            if register_params:
                clear_cpython_gh_params(ghenv, permanent_param_count + rename_count)  # we could consider renaming params if we don't want to disconnect GH component inputs
                for i, name in enumerate(input_names):
                    if i < permanent_param_count:
                        continue
                    elif i < rename_count:
                        rename_cpython_gh_input(name, i, ghenv)
                    else:
                        add_cpython_gh_param(name, "Input", ghenv, index=i + permanent_param_count)
    ghenv.Component.VariableParameterMaintenance()


def manage_cpython_dynamic_output_params(output_names, ghenv, permanent_param_count=0):
    """Synchronizes output parameters to match the given names.

    Removes outputs not in output_names, adds missing ones, preserves existing connections.

    Parameters
    ----------
    output_names : list(str)
        The names of the output parameters.
    ghenv : object
        The Grasshopper environment object.
    permanent_param_count : int, optional
        The number of leading output parameters that should not be modified. Default is 0.

    """
    to_remove = []
    for i in range(permanent_param_count, len(ghenv.Component.Params.Output)):
        if ghenv.Component.Params.Output[i].Name not in output_names:
            to_remove.append(ghenv.Component.Params.Output[i])

    for param in to_remove:
        param.IsolateObject()
        ghenv.Component.Params.UnregisterOutputParameter(param, True)

    for i, name in enumerate(output_names):
        if name not in [ghenv.Component.Params.Output[j].Name for j in range(len(ghenv.Component.Params.Output))]:
            add_cpython_gh_param(name, "Output", ghenv, index=i + permanent_param_count)

    ghenv.Component.VariableParameterMaintenance()
    ghenv.Component.ExpireSolution(True)


def get_guid_and_geometry(obj):
    """
    Try to get the GUID of a referenced Rhino object, otherwise just return the geometry.
    Simpler logic: treat input as possible GUID, try FindId, else return geometry as is.
    """
    guid = None
    geometry = obj
    rhino_obj = Rhino.RhinoDoc.ActiveDoc.Objects.FindId(obj)
    if rhino_obj:
        guid = obj
        geometry = rhino_obj.Geometry
    return guid, geometry


def curve_to_compas_polyline(obj, closed=False):
    """Convert a Grasshopper curve input (geometry or referenced Rhino object) to a COMPAS Polyline.

    Curves that are not polylines are approximated with straight segments.

    Parameters
    ----------
    obj : Rhino.Geometry.Curve | System.Guid
        The curve, or an object id. Untyped script inputs receive geometry as an id in
        the Grasshopper document (``ghdoc``), which ``rhinoscriptsyntax`` resolves through
        ``scriptcontext.doc``.
    closed : bool, optional
        If True, raise ``ValueError`` when the curve is not closed.

    Returns
    -------
    :class:`compas.geometry.Polyline`
    """
    import rhinoscriptsyntax as rs  # type: ignore
    from compas_rhino.conversions import polyline_to_compas

    geometry = obj
    if not isinstance(obj, (Rhino.Geometry.GeometryBase, Rhino.Geometry.Polyline)):
        geometry = rs.coercecurve(obj)
    if isinstance(geometry, Rhino.Geometry.Polyline):
        polyline = geometry
    else:
        curve = geometry
        if not isinstance(curve, Rhino.Geometry.Curve):
            raise ValueError("Input is not a curve: {}".format(obj))
        success, polyline = curve.TryGetPolyline()
        if not success:
            polyline = curve.ToPolyline(0, 0, 0.1, 0.0, 0.0, 0.0, 0.0, 0.001, 0.001).ToPolyline()
    if closed and not polyline.IsClosed:
        raise ValueError("Curve must be closed.")
    return polyline_to_compas(polyline)


def add_panel_feature_definitions(ghenv, panel, definitions):
    """Add the features of every definition that lies on *panel*, reporting problems on the component.

    The panel's layers are not used: they may be set later, from the panel type (``CT: Populate Model``).

    Parameters
    ----------
    ghenv : object
        The component's ``ghenv``.
    panel : :class:`timber_design_arch.elements.Panel`
    definitions : list[:class:`timber_design_gh.panel_feature_helpers.PanelFeatureDefinition`]

    Returns
    -------
    list[:class:`timber_design_arch.panel_features.PanelFeature`]
        The added features.
    """
    from timber_design_gh.panel_feature_helpers import add_feature_definitions

    if not definitions:
        return []
    added, skipped, messages = add_feature_definitions(panel, definitions)
    for text in messages:
        warning(ghenv.Component, text)
    if skipped:
        remark(ghenv.Component, "{} feature definition(s) do not lie on this panel and were skipped.".format(skipped))
    return added


def resolve_panel_type(ghenv, panel_type):
    """The PanelType given to ``CT: Create Populator``, or ``None`` (with an error on the component).

    Parameters
    ----------
    ghenv : object
        The component's ``ghenv``.
    panel_type : :class:`~timber_design_populator.PanelType`
        From ``CT: Stud Wall Panel Type``, ``CT: Custom Panel Type`` or ``CT: Panel Type From JSON``.

    Returns
    -------
    :class:`~timber_design_populator.PanelType` or None
    """
    from compas.data import json_dumps
    from compas.data import json_loads
    from timber_design_populator import PanelType

    panel_type = getattr(panel_type, "Value", panel_type)
    if isinstance(panel_type, PanelType):
        return panel_type
    if type(panel_type).__name__ == "PanelType" and hasattr(panel_type, "__data__"):
        # made by a component that still holds an earlier import of the module (e.g. after the
        # modules were reloaded): re-create it with the current classes
        return json_loads(json_dumps(panel_type))
    if panel_type is None:
        error(ghenv.Component, "Give a panel type: from CT: Stud Wall Panel Type, CT: Custom Panel Type or CT: Panel Type From JSON.")
    else:
        error(ghenv.Component, "{!r} is not a PanelType: make one with a panel type component (a library type: CT: Panel Type From JSON).".format(panel_type))
    return None


def describe_panel_type(panel_type):
    """A readable summary of *panel_type*: thickness, source, layers, agents and detail sets."""
    lines = ["{} ({})".format(panel_type.name, "{} thick".format(panel_type.thickness) if panel_type.thickness else "fills the panel")]
    if panel_type.reference:
        lines.append("after: " + ", ".join(str(v) for v in panel_type.reference.values()))

    def walk(defs, depth):
        for d in defs:
            extras = ", ".join("{}: {}".format(k, v) for k, v in sorted(d.attributes.items()))
            text = "{}{} {} {}".format("  " * depth, d.name, d.thickness if d.thickness is not None else "(fill)", d.material or "")
            lines.append((text + (" [{}]".format(extras) if extras else "")).rstrip())
            walk(d.sublayer_defs, depth + 1)

    walk(panel_type.layer_structure.layer_defs, 1)
    for agent in panel_type.agents:
        lines.append("  {} on {}".format(type(agent).__name__, agent.layer_path))
    for feature_type, detail_set in panel_type.default_detail_sets.items():
        lines.append("  {} -> {}".format(feature_type.__name__, type(detail_set).__name__))
    return "\n".join(lines)


def feature_defaults_by_type(defaults):
    """Key populator default detail sets by the feature types they build.

    A detail set declares ``FEATURE_TYPES`` (it may build several).  Later entries win for the
    same type.

    Parameters
    ----------
    defaults : list
        Detail sets, e.g. from ``CT: Detail Agent Set``.

    Returns
    -------
    dict[type, :class:`~timber_design_populator.detail_sets.DetailAgentSet`] or None
    """
    result = {}
    for item in defaults or []:
        item = getattr(item, "Value", item)  # CPython GH does not unwrap custom objects
        if item is None:
            continue
        for feature_type in getattr(item, "FEATURE_TYPES", None) or ():
            result[feature_type] = item
    return result or None


# ------------------------------------------------------------------
# panel joint rules
# ------------------------------------------------------------------

# constructor arguments a joint rule fills itself, not offered as joint flags
_PANEL_JOINT_STANDARD_ARGS = ("panel_a", "panel_b", "topology", "a_segment_index", "b_segment_index", "key", "frame")


def panel_joint_classes(topology=None, max_element_count=None):
    """Concrete panel joints offered by the panel joint rule components, by class name.

    Lists the joints of :mod:`timber_design_arch.connections` (envelope only) and of
    :mod:`timber_design_populator.panel_joints` (which also build a connection detail).

    Parameters
    ----------
    topology : int, optional
        Only joints whose ``SUPPORTED_TOPOLOGY`` is this one.  Unset: any joint with a topology.
    max_element_count : int, optional
        Only joints with this ``MAX_ELEMENT_COUNT``.

    Returns
    -------
    dict[str, type]
    """
    import timber_design_arch.connections as arch_connections
    import timber_design_populator.panel_joints as detail_joints
    from timber_design_arch.connections import PanelJoint

    result = {}
    for module in (arch_connections, detail_joints):
        for name in dir(module):
            cls = getattr(module, name)
            if not (isinstance(cls, type) and issubclass(cls, PanelJoint) and cls is not PanelJoint):
                continue
            supported = getattr(cls, "SUPPORTED_TOPOLOGY", 0)
            if not supported or (topology is not None and supported != topology):
                continue
            if max_element_count is not None and getattr(cls, "MAX_ELEMENT_COUNT", 0) != max_element_count:
                continue
            result[cls.__name__] = cls
    return result


def panel_joint_flag_names(joint_type):
    """The constructor arguments of *joint_type* a rule passes on as joint flags (e.g. ``backing_studs``)."""
    import inspect

    return [name for name in inspect.getfullargspec(joint_type.__init__).args[1:] if name not in _PANEL_JOINT_STANDARD_ARGS]


def kwargs_by_input_name(ghenv, args, names):
    """``{input name: value}`` for the inputs named in *names* that have a value.

    Maps by name, not position, so inputs may be in any order (e.g. after switching joint types).
    """
    accepted = set(names)
    return {param.Name: val for param, val in zip(ghenv.Component.Params.Input, args) if val is not None and param.Name in accepted}
