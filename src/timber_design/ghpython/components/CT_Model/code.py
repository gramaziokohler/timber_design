# r: timber_design>=0.1.0
"""Creates a TimberModel from elements and joint rules."""

import Grasshopper
import Rhino
import System
from compas.scene import Scene
from compas.tolerance import TOL
from compas.tolerance import Tolerance

from compas_timber.elements import Beam
from compas_timber.elements import Panel
from compas_timber.elements import Layer
from compas_timber.elements import Plate
from compas_timber.errors import FeatureApplicationError
from compas_timber.model import TimberModel
from compas_timber.connections import PanelJoint

from timber_design.ghpython import error
from timber_design.ghpython import warning
from timber_design.workflow import DebugInfomation
from timber_design.workflow import JointRuleSolver

TOL.absolute = 1e-6


class Script_Instance(Grasshopper.Kernel.GH_ScriptInstance):
    @property
    def component(self):
        return ghenv.Component  # type: ignore

    def RunScript(self,
            Elements: list[object],
            JointRules: list[object],
            Features: list[object],
            MaxDistance,
            CreateGeometry):

        if not Elements:
            warning(self.component, "Input parameter Elements failed to collect data")
            return
        if not JointRules:
            warning(self.component, "Input parameter JointRules failed to collect data")
        if MaxDistance is None:
            MaxDistance = TOL.ABSOLUTE

        tol = self.get_tol()
        Model = TimberModel(tolerance=tol)
        debug_info = DebugInfomation()

        self.add_elements_to_model(Model, Elements)
        self.join_elements(Model, JointRules, debug_info, MaxDistance)
        self.handle_features(Features, debug_info)

        Geometry = self.get_geometry(Model, CreateGeometry, debug_info)
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
            warning(self.component, f"Unsupported unit: {units}, some unexpected results may occur")
            return Tolerance(unit= None, absolute=1e-6, relative=1e-6)

    def add_elements_to_model(self, model, elements):
        elements = [e for e in elements if e is not None]
        for element in elements:
            element.reset_joinery()
            model.add_element(element)
            if isinstance(element, Panel):
                element.merge_layer_tree(model)

    def join_elements(self, Model, JointRules, debug_info, MaxDistance=None):
        if not JointRules:
            return
        solver = JointRuleSolver(JointRules, max_distance=MaxDistance)
        Model.connect_adjacent_beams(max_distance=solver.max_distance)
        Model.connect_adjacent_plates(max_distance=solver.max_distance)
        Model.connect_adjacent_panels(max_distance=solver.max_distance)
        joint_errors, _ = solver.apply_rules_to_model(Model)
        for je in joint_errors:
            debug_info.add_joint_error(je)
        bje = Model.process_joinery()
        if bje:
            debug_info.add_joint_error(bje)

    def handle_features(self, features, debug_info):
        if not features:
            return
        features = [f for f in features if f is not None]
        for f_def in features:
            if not f_def.elements:
                warning(self.component, "Features without elements will be ignored")
                continue
            for element in f_def.elements:
                try:
                    element.add_features(f_def.feature_from_element(element))
                except FeatureApplicationError as ex:
                    debug_info.add_feature_error(ex)

    def get_geometry(self, Model, CreateGeometry, debug_info):
        scene = Scene()
        for element in Model.elements():
            if element.children:
                continue
            if CreateGeometry:
                scene.add(element.geometry)
                if getattr(element, "debug_info", False):
                    debug_info.add_feature_error(element.debug_info)
            else:
                if isinstance(element, Beam):
                    scene.add(element.blank)
                elif isinstance(element, Plate):
                    scene.add(element.shape)
                else:
                    scene.add(element.geometry)
        return scene.draw()
