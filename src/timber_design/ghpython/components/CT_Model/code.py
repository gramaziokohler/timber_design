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

    def RunScript(self,
            Elements: System.Collections.Generic.List[object],
            Populators: System.Collections.Generic.List[object],
            JointRules: System.Collections.Generic.List[object],
            Features: System.Collections.Generic.List[object],
            MaxDistance: float,
            CreateGeometry: bool):
        # this used to be default behavior in Rhino7.. I think..
        Elements = Elements or []
        Populators = Populators or []
        JointRules = JointRules or []
        Features = Features or []

        if not Elements:
            warning(self.component, "Input parameter Elements failed to collect data")
        if not JointRules:
            warning(self.component, "Input parameter JointRules failed to collect data")
        if not Elements:  # shows beams even if no joints are found
            return
        if MaxDistance is None:
            MaxDistance = TOL.ABSOLUTE  # compared to calculted distance, so shouldn't be just 0.0

        tol = self.get_tol()
        Model = TimberModel(tolerance=tol)
        debug_info = DebugInfomation()

        JointRules = [j for j in JointRules if j is not None]
        solver = JointRuleSolver(JointRules, max_distance=MaxDistance) if JointRules else None

        ##### 1. Add elements (panels carry their pre-defined layer structure) #####
        self.add_elements_to_model(Model, Elements)

        ##### 2. Panel joinery FIRST #####
        # Connect adjacent panels, promote panel-joint candidates via the rules,
        # then process_panel_joinery() so each PanelJoint extends its per-layer
        # `layer_panels` (and adds interfaces).  This must happen before the
        # populators run so the agents generate against the *final*, extended
        # layer geometry.
        Model.connect_adjacent_panels(max_distance=solver.max_distance if solver else MaxDistance)
        if solver:
            solver.apply_rules_to_model(Model)
        panel_errors = Model.process_panel_joinery()
        for pe in panel_errors:
            debug_info.add_joint_error(pe)

        ##### 3. Populate the (now extended) layers with framing #####
        if Populators:
            self.handle_populators(Populators, Model)

        ##### 4. Beam / plate joinery between the generated elements #####
        if solver:
            Model.connect_adjacent_beams(max_distance=solver.max_distance)
            Model.connect_adjacent_plates(max_distance=solver.max_distance)
            joint_errors, _ = solver.apply_rules_to_model(Model)  # TODO: figure out best way to pass out unjoined_clusters
            for je in joint_errors:
                debug_info.add_joint_error(je)

        ##### 5. Apply extensions + features for non-panel joints #####
        # Panel joinery was already processed in step 2; skip it here so its
        # (non-idempotent) layer extensions are not applied twice.
        bje = Model.process_joinery(include_panels=False)
        if bje:
            debug_info.add_joint_error(bje)

        ##### 6. Handle user features #####
        if Features:
            feature_errors = self.handle_features(Features)
            debug_info.add_feature_error(feature_errors)

        ##### Visualization #####
        Geometry, errors = self.handle_geometry(Model, CreateGeometry)
        for geo_error in errors:
            debug_info.add_feature_error(geo_error)

        ##### Error Handling #####
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

    def handle_populators(self, populators, model, max_distance=None):
        """Run each :class:`~timber_design.populators.PanelPopulator`.

        ``PanelConfigs`` now carries fully-built :class:`PanelPopulator`
        instances (the old ``PanelPopulatorConfig`` was merged into the
        populator).  Each populator builds its own populator-space panel and
        mirrored layers lazily on the first ``populate_elements`` call
        (``PanelPopulator.prepare``), so it reads whatever layer geometry the
        panel has *now* — i.e. after step-2 panel-joinery extensions.  Generated
        framing is then merged back under the matching original-panel layers.
        """
        for pop in populators:
            if pop is None:
                continue
            pop.populate_elements()
            pop.join_elements()
            pop.merge_with_model(model)

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
            # Skip panels and their layers.  These are
            # structural containers, not physical parts — they are represented by
            # the framing (beams) and sheathing (plates) generated inside them.
            # Drawing them too would overlay solid, uncut plate ghosts on top of
            # the real framing.
            # TODO: create UI for deciding level of detail to display 
            if isinstance(element, Panel):
                continue
            if CreateGeometry:
                scene.add(element.geometry)
                if getattr(element, "debug_info", False):
                    errors.append(element.debug_info)
            else:
                if isinstance(element, Beam):
                    scene.add(element.blank)
                elif isinstance(element, Plate):
                    scene.add(element.shape)
                else:
                    scene.add(element.geometry)
        return scene.draw(), errors
