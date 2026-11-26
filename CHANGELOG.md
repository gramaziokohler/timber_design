# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

* Added `PanelType` (`timber_design_populator.panel_types`): a named, panel-agnostic buildup bundling a `LayerStructure`, the panel-wide agents that build each layer (by layer path, name or role), default detail sets and populator settings, with a `reference` and source-stated `attributes`. `apply(panel)` sets the panel's cross-section; `populator(panel, ...)` builds a `PanelPopulator`. JSON round-trip, `save_panel_type()` / `load_panel_type()`.
* Added `stud_wall_layers()` and the `exterior_sheeting_thickness` / `interior_sheeting_thickness` parameters of `stud_wall_type()`: a stud wall cross-section of sheeting and a core that fills the rest.
* Added the dataholz.eu panel types as JSON files (`timber_design_populator/panel_types/data/`), loaded by name with `load_panel_type()` and listed by `list_panel_type_files()`; `write_panel_type_files()` regenerates them from their factories.
* Added a panel type library: `stud_wall` and, after dataholz.eu, `awrhho05b`, `awrhhi01a`, `awmhhi01a` (`get_panel_type()`, `list_panel_types()`), plus `stud_wall_type()` and `framed_detail_sets()`.
* Added `BoardAgent`: parallel members (battens, cladding, joists) at an on-centre spacing in any in-plane `direction`, on a grid anchored at the panel origin, clipped to the layer outline, with a per-instance `category`.
* Added `CutThroughDetailSet`: openings and penetrations cut through every layer with no framing, for solid timber cores.
* Added `material` and `attributes` to `LayerDefinition`; layers built from a definition carry them in their `attributes`.
* Added the GH panel type components `CT: Stud Wall Panel Type`, `CT: Custom Panel Type` and `CT: Panel Type From JSON`, and `CT: Create Populator` (panel and panel type in, the populator out), and material inputs on `CT: Panel Layer Definition` and `CT: Subdivide Layer`. `CT: Layer Agent` converts vector inputs (a `BoardAgent`'s direction).
* `CompositeRule`: bundles multiple pairwise joint rules into a single `CompositeJoint` for clusters of 3+ elements (TOPO_Y, TOPO_K, etc.).
* `CT_Composite_Joint_Rule` Grasshopper component with TOPO_Y / TOPO_K context menu.
* COMPAS Data serialization (`__data__` / `__from_data__`) for `JointRule`, `DirectRule`, `CategoryRule`, `TopologyRule`, `CompositeRule`.
* `create_instance()` method on `DirectRule`, `CategoryRule`, `TopologyRule`.
* Added `CT: PlateStocks` and `CT: NestPlates` GH components.
* Added `Nesting` input parameter to `CT_BTLx` GH component.
* Migrated the Grasshopper plugin documentation from `compas_timber` (per [compas_timber#825](https://github.com/gramaziokohler/compas_timber/issues/825)): tutorial pages, images, and a new "Grasshopper Plugin" section in the docs navigation. API cross-references now point to the compas_timber documentation site.
* `create_instance()` method on `DirectRule`, `CategoryRule`, `TopologyRule`, `CompositeRule`.
* `pairwise_fallback` parameter on `joints_from_rules_and_clusters`, so a caller driving its own pairwise pass can stop the solver recursing into pairwise sub-clusters. Defaults to `True`, preserving existing behaviour.
* Added a generic panel-populator subsystem (`timber_design_populator`) that frames any `Panel` cross-section with beams and plates. `PanelPopulator` drives its agents through modify layers / generate / extend / split / cull / machine / join stages. Every agent is a `PopulatorAgent` with element and trimming layer paths (`layer=` sets both), one generation hook (`generate_elements_for_layer(layer)`) and a `priority` (lower runs first; equal priorities keep the given order). Panel-wide agents (one module each): `EdgeAgent`, `StudAgent`, `PlateAgent`, `LayerBoundaryAgent`.
* Added `FasciaEdgeAgent`: an `EdgeAgent` that puts an angled fascia (`FasciaBeam`) on every sloped panel edge, rotated so one face lies on the edge plane and higher than the layer is thick; studs butted against it get angled jack rafter cuts from the usual rules. `flush_cuts=True` trims the fascia flush with the layer's faces with longitudinal cuts.
* Added `Beam2D.footprint_frame` / `footprint_width`: the 2D connection logic works on a beam's section in the panel plane, so a beam rotated about its axis (`FasciaBeam`) takes part in topology finding, splitting and extension.
* Added `stud_panel()` factory (`timber_design_populator.stud_panel`) that builds a `PanelPopulator` for a stud-framed wall from the panel's `exterior` / `core` / `interior` layers.
* Added per-agent joint rules (`internal_joint_overrides`, `external_joint_overrides`, `composite_joint_overrides`; an override replaces the default with the same topology and categories, otherwise it is added) and panel-level fallback rules (`joint_rule_overrides`) on `PanelPopulator` / `stud_panel()`.
* Added `max_distance` to `PanelPopulator` / `stud_panel()`, bounding the gap for all joint candidate finding and creation in `join_elements()`.
* Added `PopulatorAgent.clone()` and `PopulatorAgent.beam_width()`. A missing beam width now raises a `ValueError` naming the agent and category.
* Added `Beam2D.to_beam()` (in-place conversion to a plain `Beam`) and `AABB2D.aabb`.
* Added GH components for the panel-populator workflow: `CT: Panel Layer Definition`, `CT: Subdivide Layer`, `CT: Decompose LayerStructure`, `CT: Layer Agent`, `CT: Detail Agent Set`, `CT: Stud Panel`, `CT: Panel Populator`, `CT: Populate Model`.
* Added `CT: Filter Display` GH component to filter and display model elements by layer path or group.
* Added `CT: Panel Viewer` GH component: like `CT: Filter Display`, but resolves `group_filter` elements in the model by guid and lays each group out at world XY in group space, with the corner of its trimmed outline at the origin.
* Added `layer_structure` input to `CT: Panel` to attach a `LayerStructure` to the panel.
* Added `CT: Panel Opening`, `CT: Panel MEP Penetration`, `CT: Panel Niche` and `CT: Panel Linear Service` GH components, which output world-space panel feature definitions.
* Added `ServiceDrillingDetailAgent` and `ServiceNotchDetailAgent`: drill, or lap-notch from a given side, every core beam a service path crosses, and report oversized holes (> 40% of the beam depth) and notches (> 25%) as feature errors.
* Added the `PopulatorAgent.machine_element()` hook, called by `PanelPopulator` after splitting and culling.
* Added a `features` input to `CT: Panel`, `CT: Panel From Outline`, `CT: Panel From Brep`, `CT: Panel From Frame And Dimensions` and `CT: Panel From Top Bottom`. Each panel adds the feature definitions that lie on it, so one list can go to every panel.
* Added the `timber_design_arch` package (merged in from the standalone `compas_arch` repository) as a fourth top-level package in `src/`, shipped in the `timber_design` distribution: `Panel`, `PanelType`, `Layer`, `LayerDefinition`, `LayerRole` and `LayerStructure` (`timber_design_arch.elements`); `PanelJoint`, `PanelLButtJoint`, `PanelTButtJoint`, and `PanelMiterJoint` (`timber_design_arch.connections`); `PanelFeature`, `Opening`, `MEPPenetration`, `LinearService`, `Niche` and `PanelConnectionInterface` (`timber_design_arch.panel_features`); `ArchModel` (`timber_design_arch.model`); and its `compas_pb` serializer plugin. Its tests, API pages and class diagrams came along.
* Added detail sets (`timber_design_populator.detail_sets`, one module per set). Every panel feature is built by exactly one detail set: `feature.detail_set`, or else the populator's default for its type (`default_detail_sets`). A set reads the feature and the panel's layers and expands into detail agents with explicit inputs on every `populate_elements()`. The built-in sets are one possible way to build a feature, not the only one: `FramedOpeningDetailSet` (with `cut_offsets` per layer role), `FramedPenetrationDetailSet`, `FramedNicheDetailSet` and `LinearServiceDetailSet(mode="drilling" | "notching")`, the `stud_panel()` defaults. New behaviour is a new detail agent; a new combination of agents is a new detail set; a new connection detail is a new panel joint / detail set pair.
* Added the detail agents `VoidFramingDetailAgent` (frames a void: header, king/jack studs, optional sill, door bottom-plate handling) and `LayerCutDetailAgent` (cuts one layer and its sublayers: splits and removes beams such as battens inside the cut, and cuts plates through, by a prism, or as a blind pocket). Detail agents (`IS_DETAIL = True`) take explicit inputs and are created by detail sets; given to `PanelPopulator(agents=...)` they are skipped and reported.
* Added the `CT: Detail Agent Set` GH component (lists the feature detail sets), and the `feature_defaults_by_type()` GH helper that keys `default_detail_sets` by the feature types a set builds.
* Added `PanelFeature.detail_set` (e.g. `Opening.from_outline_panel(..., detail_set=FramedOpeningDetailSet(header_width=200))`). Every `PanelPopulator` expands a clone of it in place of its default for the feature's type.
* Added connection details built by panel joints (`timber_design_populator.panel_joints`, one module per joint): `LGenericPanelJoint` (flags `stagger_layers`, `backing_studs`, `backing_stud_width`, `backing_stud_inset`) and `TGenericPanelJoint` (flags `backing_studs`, `backing_stud_width`, `backing_stud_inset`). The joint does all cross-panel calculation with both panels in view and gives each panel's `PanelConnectionInterface` its half as an `LGenericPanelJointDetailSet` / `TGenericPanelJointDetailSet`, in that panel's local frame, so each populator still knows only its own panel. `PanelConnectionInterface` carries its edge, `interface_role` (`MAIN` / `CROSS` on butt joints) and `detail_set`.
* Added `LayerStructure.resolve(thickness)` and `LayerSlot`: a layer structure's slots at absolute offsets, without building layers.
* Added `LayerExtensionDetailAgent` (priority -100: moves layer edges onto given planes before anything is generated; two details moving the same layer edge are reported, and the later one by priority wins) and `BackingStudDetailAgent` (studs on given lines; merges studs closer than one width, drops one next to a parallel panel edge, and removes parallel overlapping regular studs).
* Added the `PopulatorAgent.modify_layers()` hook, called by `PanelPopulator` before element generation; the populator applies the extension planes agents set there.
* The panel joint rule GH components list the joints of `timber_design_arch.connections` and `timber_design_populator.panel_joints`, and offer a joint's flags (e.g. `backing_studs`) as inputs, mapped by name. Added a `detail_set` input to `CT: Panel Opening`, `CT: Panel MEP Penetration`, `CT: Panel Niche` and `CT: Panel Linear Service`.
* `timber_design_populator.populator_agents`, `.detail_sets` and `.panel_joints` export their classes, so agents, sets and joints serialize; layer paths that come back from JSON as lists become tuples.
* Grasshopper tabs: the core components are under `COMPAS Timber`, the panel components under `Timber Arch`, each with contiguous, renumbered subcategories (`COMPAS Timber`: Installation, Elements, Fasteners, Beam Joint Rules, Plate Joint Rules, Features, Model, Show, Fabrication, Utils; `Timber Arch`: Panels, Layers, Features, Panel Joint Rules, Populator, Model).
* Added an optional `orientation` input (the panel's local y-axis) to `CT: Panel From Brep`, `CT: Panel From Outline` and `CT: Panel From Top Bottom`, like `CT: Panel`'s.
* Added `manage_cpython_dynamic_output_params` GH helper.
* Added the "Populating Panels" user guide, the `timber_design_populator` API page and contributor class diagrams to the docs.

### Changed

* `CT: Panel Viewer` no longer re-runs `process_joinery()` on the model it displays: re-running the panel joints reset every layer's edges to the panel envelope, so populated layers (e.g. the corner stagger of `LGenericPanelJoint`) were shown unextended.
* `PanelPopulator(panel, panel_type)` takes the panel and a `PanelType` only: the type supplies the agents, default detail sets, standard beam width, joint rule overrides, max distance and layer structure (`populator.panel_type`). For a populator without a predefined type, make one from the panel's layer structure: `PanelType(name, panel.layer_structure, agents=[...])`. `PanelType.populator(panel)` no longer takes overrides; use `PanelType.derive(...)` for a variant.
* `LayerCutDetailAgent` removes every piece of a beam that overlaps its cut, not only pieces whose centerline midpoint lies inside it: a board or batten straddling an opening edge (the edge running inside its width) no longer runs across the opening. Applies in any board direction.
* GH panel feature definitions no longer read the panel's layers: outlines go on the panel faces (niches) or mid-plane (services), and `FramedNicheDetailSet` and `LinearServiceDetailSet` project them onto the actual layers. A panel can get its layers after its features.

* `StudAgent` is now a `BoardAgent` of category `"stud"` (same parameters, placement and output); `stud_panel()` builds the `stud_wall` panel type for the panel's layers.
* `LayerBoundaryAgent`'s boundary is available as `layer_outer_boundary(layer)`.
* `get_clusters_from_model` no longer calls `connect_adjacent_beams` / `connect_adjacent_plates` internally. Callers must connect the model before calling `apply_rules_to_model`.
* `_joints_from_rules_and_clusters` renamed to `joints_from_rules_and_clusters` (now public).
* `CompositeRule.create_instance` returns a joint (or `None`) rather than a `(joint, error)` tuple, and lets `BeamJoiningError` propagate; `try_create_joint` wraps it and registers the joint in the model.
* `CT: Model` no longer saves and re-appends `element._features` around `element.reset()`. `reset()` already drops joinery features and keeps user ones, so the save/restore duplicated every opening on each Grasshopper solve.
* compas_timber dependency: requires a release providing `CompositeJoint`. **TODO:** set the exact version here and in `pyproject.toml` once that release lands — they currently disagree (`pyproject.toml` pins `>=2.1.1`).
* Split the `timber_design` package into three top-level packages in `src/`, all shipped in the `timber_design` distribution: `timber_design_rules` (was `timber_design.workflow`), `timber_design_populator` (was `timber_design.populators` and `timber_design.connections_2d`, now `timber_design_populator.connections_2d`) and `timber_design_gh` (was `timber_design.ghpython`).
* Grasshopper components are split into two packages: `compas_timber` (core components, published as the `compas_timber` Yak package) and `timber_arch` (panel components, a new Yak add-on that requires `compas_timber`).
* Moved the panel GH components from `core` to `populator`: `CT: Panel` and the `CT: Panel From ...` components, the panel joint rules, `CT: Panel Layer Definition`, `CT: Subdivide Layer`, `CT: Decompose LayerStructure`, `CT: Panel Viewer` and `CT: Populate Model`.
* Replaced `invoke build-cpython-ghuser-components` / `yakerize` with `invoke build-gh-components`, `update-gh-headers` and `yakerize-gh`, each taking `--target compas_timber|timber_arch` (`core` and `populator` are still accepted).
* `invoke build-gh-components` writes the `.ghuser` files to `src/timber_design_gh/ghuser/<target>` instead of `dist/ghuser/<target>`.
* Added `invoke install-gh-components`, which builds the components and installs each package into its own folder, `UserObjects/compas_timber` and `UserObjects/timber_arch`, replacing that folder so removed components disappear, and deletes copies older installs left elsewhere in `UserObjects`.
* Bumped the `compas_timber` dependency to `>=3.0, <4.0`.
* Dropped the external `compas_arch` dependency now that the package lives in this repository, and took over its requirements: `compas >=2.15.1, <2.16`, `compas_model == 0.9.2`, `compas_brep >= 0.3.1` and `compas_pb >= 1.2.0, < 2.0`.
* `ConnectionSolver2D.find_topology` gained a `max_distance` parameter used as the containment tolerance, and returns `None` instead of raising when one beam lies entirely inside another.
* `ConnectionSolver2D.find_topology` reports face-to-face overlaps as `TOPO_UNKNOWN` until `TOPO_FACE_FACE` is supported downstream.
* Fixed `Beam2D.get_beam_segment` applying a parented beam's parent transformation twice, which offset segments along the panel normal.
* `CT: Model` adds each panel's layers to the model (and resets them on every solve), so `CT: Populate Model` finds them.
* `PanelPopulator` binds and expands the features' detail sets at the start of every `populate_elements()`, so joint-generated interfaces and the model copy in `CT: Populate Model` are picked up.
* `CT: Populate Model` recreates the panel joints' connection interfaces on its model copy.
* `CT: ShowJointTypes` places labels at `joint.location`.
* `PanelPopulator.populate_elements()` starts a fresh `debug_info`, so errors no longer accumulate across Grasshopper solves.
* MEP penetrations and niches are framed like a window, with a sill (`FramedPenetrationDetailSet`, `FramedNicheDetailSet`).
* A `Niche` without a `depth` goes through the side layer and the framing layer.
* Removed the `openings` curve input from `CT: Panel`, `CT: Panel From Outline`, `CT: Panel From Frame And Dimensions` and `CT: Panel From Top Bottom`. Openings are features now: define them with `CT: Panel Opening` and connect them to `features`.

### Removed

* Removed the `CT: Panel Populator` and `CT: Stud Panel` GH components: build a panel type (`CT: Custom Panel Type`, `CT: Stud Wall Panel Type`) and use `CT: Create Populator`.
* Removed the `layer_structure` input of `CT: Panel`: layers come from the panel type (`CT: Create Populator`).
* Removed the panel-specific code from `CT: Model`: panels enter the model without layers; `CT: Populate Model` gives each its panel type's layers (`PanelPopulator.layer_structure`) before re-running the panel joints and populating.

* `ContainerDefinition` class (dead code).
* `PanelLLayerButtJoint` (from the standalone `compas_arch`). Use `LGenericPanelJoint` (`stagger_layers=True` by default); the populator now does the layer stagger.
* `instance_feature_configs` from `stud_panel()` and `CT: Stud Panel`: give the feature a `detail_set` instead.
* `max_cluster_size` parameter from `get_clusters_from_model`.
* Removed the old wall/slab populator modules (`wall_details.py`, `wall_from_surface.py`, `wall_populator.py`), superseded by the panel-populator subsystem.


## [0.3.1] 2026-07-09

### Added

### Changed

* Fixed `CT: L Topological Joint Rules`, `CT: Direct Joint Rules`, `CT: Joint Rules From List`, and `CT: Category Joints Rules` — selecting `LButtJoint` crashed the component.

### Removed


## [0.3.0] 2026-07-02

### Added

### Changed
* Some icons changed
### Removed


## [0.2.1] 2026-07-01

### Added

* Added `CT: PlateFromBrep` and `CT: BeamFromBox` GH components.
* Added `CT: Panel From Brep`, `CT: Panel From Frame And Dimensions`, `CT: Panel From Outline`, and `CT: Panel From Top and Bottom` GH components for creating panel elements.
* Added `CT: Plate From Frame And Dimensions` GH component.
* Added four panel joint rule GH components: `CT: Edge-to-Edge Topological Panel Joint Rules`, `CT: Edge-to-Face Topological Panel Joint Rules`, `CT: Category Panel Joint Rules`, and `CT: Direct Panel Joint Rules`.
* Added new GH subcategory `06 Panel Joint Rules`.
* Added `connections_2d` module (`timber_design.connections_2d`) with 2D blank-outline-based connection solving for panel structures. Includes `Beam2D`, `AABB2D`, `ConnectionSolver2D`, `Beam2DSolverResult`, `Beam2DPolylineIntersectionResult`, `Cluster2D`, and `Cluster2DFinder`.

### Changed

* Renamed `CT: Beam` to `CT: BeamFromLineCurve`.
* Renumbered GH subcategories: `06 Features` → `07 Features`, `07 Model` → `08 Model`, `08 Show` → `09 Show`, `09 Utils` → `10 Utils`, `10 Fabrication` → `11 Fabrication` to accommodate the new `06 Panel Joint Rules` subcategory.
* Fixed `inspect.getargspec` → `inspect.getfullargspec` in `CT: BTLx From Parameters` and `CT: T Topological Joint Rules` to support annotated class signatures.
* `CT: T Topological Joint Rules` now coerces `step_shape` string inputs (e.g. `"DOUBLE"`) to the expected `StepShapeType` values (e.g. `"double"`) automatically.
* `CT: Model` — removed the `Containers` input (wall/slab populator workflow removed).
* `CT: Model` — added `GH_Goo` unwrapping for `JointRules` and `Features` inputs; CPython GH components do not auto-unwrap custom Python objects, causing rules and features to be silently ignored without this fix.
* `CT: Model` — added `sys.modules` flush at startup to force a fresh import of `timber_design` on every solve, ensuring code changes are picked up without restarting Rhino.
* `CT: Model` — added call to `Model.connect_adjacent_panels()` (guarded with `hasattr` for forward compatibility).
* `CT: Model` — `element.reset()` in `add_elements_to_model` now saves and restores `_features` to prevent features added before the model solve (e.g. `FreeContour` openings) from being discarded.
* `CT: Model` — Plate geometry in `CreateGeometry=True` mode now calls `element.compute_modelgeometry()` directly instead of `element.geometry`, bypassing the stale cache that caused pre-joint geometry to be returned after `add_extensions()` modifies extension planes.
* `CT: Model` — fixed `element.shape` → `element.blank` for Plates in `CreateGeometry=False` mode (`Plate` does not have a `shape` attribute).

### Removed

* Removed `CT: Wall`, `CT: Slab`, and `CT: WallConfigSet` GH components.


## [0.2.0] 2026-04-01

### Added

### Changed

* Fixed import of `Cluster` since analyzers module got replaced.
* Use `get_clusters_from_joint_candidates` instead of the removed `MaxNCompositeAnalyzer` to get the clusters from the joint candidates.

### Removed


## [0.1.0] 2026-03-25

### Added

* Migrated over the components and design workflow module from COMPAS Timber.

### Changed

* Renamed `OliGinaJoint` to `TOliGinaJoint` and `TenonMortiseJoint`to `LTenonMortiseJoint` and `TTenonMortiseJoint`for consistency wrt to the supported topology.

### Removed
