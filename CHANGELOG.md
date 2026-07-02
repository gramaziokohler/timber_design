# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

### Changed

### Removed


## [0.3.0] 2026-07-02

### Added

### Changed

### Removed


## [0.2.1] 2026-07-01

### Added

### Changed

### Removed


## [0.3.0] 2026-07-02

### Added

### Changed

### Removed


## [0.2.1] 2026-07-01

### Added

* `CompositeJointRule`: bundles multiple pairwise joint rules into a single `CompositeJoint` for clusters of 3+ elements (TOPO_Y, TOPO_K, etc.).
* `CT_Composite_Joint_Rule` Grasshopper component with TOPO_Y / TOPO_K context menu.
* COMPAS Data serialization (`__data__` / `__from_data__`) for `JointRule`, `DirectRule`, `CategoryRule`, `TopologyRule`, `CompositeJointRule`.
* `create_instance()` method on `DirectRule`, `CategoryRule`, `TopologyRule`.

### Changed

* `get_clusters_from_model` no longer calls `connect_adjacent_beams` / `connect_adjacent_plates` internally. Callers must connect the model before calling `apply_rules_to_model`.
* `_joints_from_rules_and_clusters` renamed to `joints_from_rules_and_clusters` (now public).
* compas_timber dependency bumped to >=2.1.2.
* Added `CT: PlateFromBrep` and `CT: BeamFromBox` GH components.
* Added `CT: Panel From Brep`, `CT: Panel From Frame And Dimensions`, `CT: Panel From Outline`, and `CT: Panel From Top and Bottom` GH components for creating panel elements.
* Added `CT: Plate From Frame And Dimensions` GH component.
* Added four panel joint rule GH components: `CT: Edge-to-Edge Topological Panel Joint Rules`, `CT: Edge-to-Face Topological Panel Joint Rules`, `CT: Category Panel Joint Rules`, and `CT: Direct Panel Joint Rules`.
* Added new GH subcategory `06 Panel Joint Rules`.

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

