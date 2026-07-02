# env: C:\Users\Admin\OneDrive\Documents\01_ETH\04_Repositories\timber_design\src
# flake8: noqa
"""Creates an Model"""

import sys

for _k in list(sys.modules):
    if _k.startswith('timber_design'):
        del sys.modules[_k]

import Grasshopper
import Rhino
import System
from compas.scene import Scene
from compas.tolerance import TOL
from compas.tolerance import Tolerance
from compas_timber.elements import Beam
from compas_timber.elements import Plate
from compas_timber.errors import FeatureApplicationError
from compas_timber.model import TimberModel

from timber_design.ghpython import error
from timber_design.ghpython import warning
from timber_design.workflow import DebugInfomation
from timber_design.workflow import JointRuleSolver

# workaround for https://github.com/gramaziokohler/compas_timber/issues/280
TOL.absolute = 1e-6


class ModelComponent(Grasshopper.Kernel.GH_ScriptInstance):
    @property
    def component(self):
        return ghenv.Component  # type: ignore

    def RunScript(
        self,
        Elements: System.Collections.Generic.List[object],
        JointRules: System.Collections.Generic.List[object],
        Features: System.Collections.Generic.List[object],
        MaxDistance: float,
        CreateGeometry: bool,
    ):
        Elements = Elements or []
        JointRules = JointRules or []
        Features = Features or []

        # CPython GH doesn't auto-unwrap custom Python objects from GH_Goo wrappers
        JointRules = [getattr(j, "Value", j) for j in JointRules]
        Features = [getattr(f, "Value", f) for f in Features]

        if not Elements:
            warning(self.component, "Input parameter Elements failed to collect data")
        if not JointRules:
            warning(self.component, "Input parameter JointRules failed to collect data")
        if not Elements:
            return
        if MaxDistance is None:
            MaxDistance = TOL.ABSOLUTE

        tol = self.get_tol()
        Model = TimberModel(tolerance=tol)
        debug_info = DebugInfomation()

        self.add_elements_to_model(Model, Elements)
        if hasattr(Model, 'connect_adjacent_panels'):
            Model.connect_adjacent_panels(max_distance=MaxDistance)

        JointRules = [j for j in JointRules if j is not None]
        if JointRules:
            solver = JointRuleSolver(JointRules, max_distance=MaxDistance)
            joint_errors, _ = solver.apply_rules_to_model(Model)
            for je in joint_errors:
                debug_info.add_joint_error(je)

        bje = Model.process_joinery()
        if bje:
            debug_info.add_joint_error(bje)

        if Features:
            feature_errors = self.handle_features(Features)
            debug_info.add_feature_error(feature_errors)

        Geometry, errors = self.handle_geometry(Model, CreateGeometry)
        for geo_error in errors:
            debug_info.add_feature_error(geo_error)

        if debug_info.has_errors:
            warning(self.component, "Error found during joint creation. See DebugInfo output for details.")

        return Model, Geometry, debug_info

    def get_tol(self):
        units = Rhino.RhinoDoc.ActiveDoc.GetUnitSystemName(True, True, True, True)
        if units == "m":
            return Tolerance(unit="M", absolute=1e-6, relative=1e-6)
        elif units == "mm":
            return Tolerance(unit="MM", absolute=1e-3, relative=1e-3)
        else:
            error(self.component, f"Unsupported unit: {units}")
            return

    def add_elements_to_model(self, model, elements):
        elements = [e for e in elements if e is not None]
        for element in elements:
            saved_features = list(getattr(element, "_features", []))
            element.reset()
            if saved_features and hasattr(element, "_features"):
                element._features.extend(saved_features)
            model.add_element(element)

    def handle_features(self, features):
        feature_errors = []
        features = [f for f in features if f is not None]
        for f_def in features:
            if not f_def.elements:
                warning(self.component, "Features defined in model must have elements defined. Features without elements will be ignored")
                continue
            for element in f_def.elements:
                try:
                    element.add_features(f_def.feature_from_element(element))
                except FeatureApplicationError as ex:
                    feature_errors.append(ex)
        return feature_errors

    def handle_geometry(self, Model, CreateGeometry):
        scene = Scene()
        errors = []
        for element in Model.elements():
            if CreateGeometry:
                if isinstance(element, Plate):
                    # TimberElement._geometry is not cleared by reset_computed, so element.geometry
                    # returns stale pre-joint geometry for Plates. Force fresh computation so
                    # extension planes set by add_extensions() are reflected in the output.
                    geo = element.compute_modelgeometry()
                else:
                    geo = element.geometry
                scene.add(geo)
                if getattr(element, "debug_info", False):
                    errors.append(element.debug_info)
            else:
                if isinstance(element, Beam):
                    scene.add(element.blank)
                elif isinstance(element, Plate):
                    scene.add(element.blank)
                else:
                    scene.add(element.geometry)
        return scene.draw(), errors
