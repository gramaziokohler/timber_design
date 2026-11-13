# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

* Added `CT: PlateStocks` and `CT: NestPlates` GH components.
* Added `Nesting` input parameter to `CT_BTLx` GH component.
* Migrated the Grasshopper plugin documentation from `compas_timber` (per [compas_timber#825](https://github.com/gramaziokohler/compas_timber/issues/825)): tutorial pages, images, and a new "Grasshopper Plugin" section in the docs navigation. API cross-references now point to the compas_timber documentation site.
* Added a generic panel-populator subsystem (`timber_design.populators`) that frames any `Panel` cross-section with beams and plates. `PanelPopulator` drives an ordered list of agents through generate / extend / split / cull / join stages: `LayerAgent`s act on one layer (`EdgePopulatorAgent`, `StudPopulatorAgent`, `PlatePopulatorAgent`, `PanelBoundaryPopulatorAgent`) and `FeatureAgent`s on a panel feature (`OpeningPopulatorAgent`, dispatching to `WindowPopulatorAgent` / `DoorPopulatorAgent` by opening type).
* Added `stud_panel()` factory (`timber_design.populators.stud_panel`) that builds a `PanelPopulator` for a stud-framed wall from the panel's `exterior` / `core` / `interior` layers.
* Added per-agent joint rules (`internal_joint_overrides`, `external_joint_overrides`, `composite_joint_overrides`; an override replaces the default with the same topology and categories, otherwise it is added) and panel-level fallback rules (`joint_rule_overrides`) on `PanelPopulator` / `stud_panel()`.
* Added `max_distance` to `PanelPopulator` / `stud_panel()`, bounding the gap for all joint candidate finding and creation in `join_elements()`.
* Added `PopulatorAgent.clone()` and `PopulatorAgent.beam_width()`. A missing beam width now raises a `ValueError` naming the agent and category.
* Added `CompositeRule`, which bundles several pairwise joint rules into one `CompositeJoint` for clusters of 3+ elements (TOPO_Y, TOPO_K, etc.).
* Added COMPAS Data serialization (`__data__` / `__from_data__`) for `JointRule`, `DirectRule`, `CategoryRule`, `TopologyRule` and `CompositeRule`.
* Added `create_instance()` to `DirectRule`, `CategoryRule`, `TopologyRule` and `CompositeRule`, returning a joint without adding it to a model.
* Added `JointRuleSolver.max_rule_distance`.
* Added `Beam2D.to_beam()` (in-place conversion to a plain `Beam`) and `AABB2D.aabb`.
* Added GH components for the panel-populator workflow: `CT: Panel Layer Definition`, `CT: Subdivide Layer`, `CT: Decompose LayerStructure`, `CT: Layer Agent`, `CT: Feature Agent`, `CT: Stud Panel`, `CT: Panel Populator`, `CT: Populate Model`.
* Added `CT: Composite Joint Rule` GH component with a TOPO_Y / TOPO_K context menu.
* Added `CT: Filter Display` GH component to filter and display model elements by layer path or group.
* Added `layer_structure` input to `CT: Panel` to attach a `LayerStructure` to the panel.
* Added `manage_cpython_dynamic_output_params` GH helper.
* Added the "Populating Panels" user guide, the `timber_design.populators` API page and contributor class diagrams to the docs.

### Changed

* Split `timber_design` into three independently released distributions in a uv workspace under `packages/`: `compas_timber_rules` (was `timber_design.workflow`), `compas_timber_populator` (was `timber_design.populators` and `timber_design.connections_2d`, now `compas_timber_populator.connections_2d`) and `compas_timber_gh` (was `timber_design.ghpython`). The root `timber_design` project is now a private development meta-package.
* Grasshopper components are split into `core` (published as the `compas_timber` Yak package) and `populator` (new `compas_timber_populator` Yak add-on, requires the core package).
* Replaced `invoke build-cpython-ghuser-components` / `yakerize` with `invoke build-gh-components`, `update-gh-headers` and `yakerize-gh`, each taking `--target core|populator`.
* Releases are now per package, triggered by `rules-v*`, `populator-v*` and `gh-v*` tags.
* Bumped the `compas_timber` dependency to `>=3.0.0`.
* `JointRule` now inherits from `compas.data.Data`.
* `get_clusters_from_model` now calls `model.compute_topologies()` instead of `connect_adjacent_beams` / `connect_adjacent_plates` / `connect_adjacent_panels`.
* Renamed `JointRuleSolver._joints_from_rules_and_clusters` to the public `joints_from_rules_and_clusters`, which uses the solver's own rules and gained a `pairwise_fallback` parameter.
* `JointRuleSolver._sort_rules` orders rules Direct → Composite → Category → Topology.
* `ConnectionSolver2D.find_topology` gained a `max_distance` parameter used as the containment tolerance, and returns `None` instead of raising when one beam lies entirely inside another.
* `ConnectionSolver2D.find_topology` reports face-to-face overlaps as `TOPO_UNKNOWN` until `TOPO_FACE_FACE` is supported downstream.
* Fixed `Beam2D.get_beam_segment` applying a parented beam's parent transformation twice, which offset segments along the panel normal.
* `CT: Model` connects adjacent beams and plates before applying joint rules, and no longer re-appends saved features after `element.reset()` (which duplicated openings on every solve).
* `CT: Model` adds each panel's layers to the model (and resets them on every solve), so layer-aware panel joints such as `PanelLLayerButtJoint` and `CT: Populate Model` find them.
* `CT: ShowJointTypes` places labels at `joint.location`.

### Removed

* Removed the old wall/slab populator modules (`wall_details.py`, `wall_from_surface.py`, `wall_populator.py`), superseded by the panel-populator subsystem.
* Removed the `ContainerDefinition` class (dead code).
* Removed the `max_cluster_size` parameter from `get_clusters_from_model`.


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
