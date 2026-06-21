# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

* Added `CT: PlateFromBrep` and `CT: BeamFromBox` GH components.
* Added `connections_2d` module (`timber_design.connections_2d`) with 2D blank-outline-based connection solving for panel structures. Includes `Beam2D`, `AABB2D`, `ConnectionSolver2D`, `Beam2DSolverResult`, `Beam2DPolylineIntersectionResult`, `Cluster2D`, and `Cluster2DFinder`.

### Changed

* Renamed `CT: Beam` to `CT: BeamFromLineCurve`.

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

