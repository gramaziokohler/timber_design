# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

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

### Changed

* Renamed `CT: Beam` to `CT: BeamFromLineCurve`.

### Removed

* `ContainerDefinition` class (dead code).
* `max_cluster_size` parameter from `get_clusters_from_model`.


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

