# r: timber_design>=0.1.0
"""Creates an Model"""

import Grasshopper
import Rhino
import System
from compas.scene import Scene
from compas.tolerance import TOL
from compas.tolerance import Tolerance

# from timber_design.workflow import WallPopulator - breaks the GH Component
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

# workaround for https://github.com/gramaziokohler/compas_timber/issues/280
TOL.absolute = 1e-6


class ModelComponent(Grasshopper.Kernel.GH_ScriptInstance):
    @property
    def component(self):
        return ghenv.Component  # type: ignore

    def RunScript(self,
            Elements: System.Collections.Generic.List[object],
            JointRules: System.Collections.Generic.List[object],
            Features: System.Collections.Generic.List[object],
            MaxDistance: float,
            CreateGeometry: bool):

        # parse inputs
        if not Elements:
            warning(self.component, "Input parameter Elements failed to collect data")
            return
        if not JointRules:
            warning(self.component, "Input parameter JointRules failed to collect data")            
        if MaxDistance is None:
            MaxDistance = TOL.ABSOLUTE  # compared to calculted distance, so shouldn't be just 0.0

        # setup model
        tol = self.get_tol()
        Model = TimberModel(tolerance=tol)
        debug_info = DebugInfomation()

        #process model
        self.add_elements_to_model(Model, Elements)
        self.join_elements(Model, JointRules, debug_info, MaxDistance)
        self.handle_features(Features, debug_info)

        # get outputs
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
            error(self.component, f"Unsupported unit: {units}")
            return

    def add_elements_to_model(self, model, elements):
        """Add input elements to the model, resetting prior-solve state.

        Grasshopper persists the same element objects across solves, so any
        joinery state applied on a previous run (blank extensions, joint-applied
        features, and — for panels — connection interfaces) must be cleared
        before re-processing, otherwise it accumulates.  ``Element.reset()`` /
        ``Panel.reset()`` removes joinery features and extensions while keeping
        user-defined, non-joinery features (e.g. panel openings), so it is safe
        to reset panels too.
        """
        elements = [e for e in elements if e is not None]
        for element in elements:
            element.reset()
            model.add_element(element)
            if isinstance(element, Panel):
                self._register_panel_layers(model, element)

    def _register_panel_layers(self, model, panel):
        """Add panel layers to model tree as children so populate_elements can extract them."""
        def _add_layer(layer, parent):
            model.add_element(layer, parent=parent)
            for sublayer in layer.sublayers:
                _add_layer(sublayer, layer)
        for root_layer in panel.layers:
            _add_layer(root_layer, panel)


    def join_elements(self, Model, JointRules, debug_info, MaxDistance=None):
        """Join the timber elements, ignoring PanelJoints"""
        if not JointRules:
            return

        solver = JointRuleSolver(JointRules, max_distance=MaxDistance)
        Model.connect_adjacent_beams(max_distance=solver.max_distance)
        Model.connect_adjacent_plates(max_distance=solver.max_distance)
        Model.connect_adjacent_panels(max_distance=solver.max_distance)
        joint_errors, _ = solver.apply_rules_to_model(Model)  # TODO: figure out best way to pass out unjoined_clusters
        for je in joint_errors:
            debug_info.add_joint_error(je)

        # Apply extensions + features
        bje = Model.process_joinery()
        if bje:
            debug_info.add_joint_error(bje)

    def handle_features(self, features, debug_info):
        if not features:
            return
        features = [f for f in features if f is not None]
        for f_def in features:
            if not f_def.elements:
                warning(self.component, "Features defined in model must have elements defined. Features without elements will be ignored")
                continue

            for element in f_def.elements:
                try:
                    element.add_features(f_def.feature_from_element(element))
                except FeatureApplicationError as ex:
                    debug_info.add_feature_error(ex)

    def get_geometry(self, Model, CreateGeometry, debug_info):
        scene = Scene()
        for element in Model.elements():
            # TODO: create UI for deciding level of detail to display 
            if isinstance(element, Panel):
                continue
            if isinstance(element, Layer):
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
