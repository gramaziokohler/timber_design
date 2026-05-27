# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

#### Panel Populator subsystem (`timber_design.populators`)

A new `timber_design.populators` package replaces the old wall-populator module with a general, layer-based panel framing system.

* **`LayerConfig` / `Layer`** — `LayerConfig` is a pure-data blueprint (thickness, name, `is_framing_layer`, `agent_configs`, optional `sublayers`).  `Layer` is the resolved runtime object that holds a sliced panel geometry and the agents registered on it.  `PanelPopulatorConfig` resolves fill-remaining (`thickness=None`) thicknesses with a two-pass bottom-up / top-down algorithm and never mutates the original definitions, making configs safe to reuse in Rhino live-update loops.
* **`PanelPopulatorConfig`** — config class that accepts an explicit `layer_defs` list, `default_feature_configs` dict, and an optional `panel`.  Produces a `PanelPopulator` via `create_populator()`.  `layers_from_panel_and_layer_defs` builds `Layer` objects using *outline chaining* — each layer's far boundary is reused as the next layer's near boundary, eliminating floating-point discrepancies at shared faces.
* **`stud_panel()`** (`populator_configs.stud_panel_config`) — factory function returning a `PanelPopulatorConfig` for standard stud-wall framing.  Parameters: `standard_beam_width`, `stud_spacing`, `orientation`, `edge_beam_min_width`, `standard_beam_width_increment`, `sheeting_outside`, `sheeting_inside`, `lintel_posts`, `split_bottom_plate_beam`, `beam_width_overrides`, `joint_rule_overrides`, `default_feature_configs`.
* **`recess_panel()`** (`populator_configs.recess_panel_config`) — factory function returning a `PanelPopulatorConfig` for recessed-frame panels.  Parameters: `recess_beam_width`, `recess_beam_height`, `sheeting_recess`, plus the common edge and sheeting parameters.
* **`PanelPopulator`** — orchestrates the full population sequence: generate → extend → trim → add to internal model → within-agent joints → cross-agent joints → process joinery → merge to world model.
* **`LayerAgent`** (abstract) — bound to one layer; generates elements, trims against neighbours, and creates joint definitions.  Subclasses: `EdgePopulatorAgent`, `StudPopulatorAgent`, `PlatePopulatorAgent`, `RecessPopulatorAgent`, `PanelBoundaryPopulatorAgent`.
* **`FeatureAgent`** (abstract) — extends `LayerAgent` for agents that span multiple layers (e.g. openings).  Tracks per-layer elements in `_elements_by_layer` and exposes them via the unified `elements_for_layer` / `set_elements_for_layer` API.  Subclass: `OpeningPopulatorAgent`.
* **Unified element API** — `LayerAgent.elements_for_layer(layer)` and `set_elements_for_layer(layer, elements)` give both `LayerAgent` and `FeatureAgent` a consistent interface.  `Layer.elements` is a computed property backed by this API, removing all stale `id()`-set comparisons.
* **Trim API** — three named methods: `trim_within_layer(other_agent, layer)`, `trim_cross_layer(other_agent)` (no-op default, overridden in `RecessPopulatorAgent` and `OpeningPopulatorAgent`), and `trim_other_layers(layers)`.  `_trim_element_list(elements)` is the internal trimming primitive.
* **`Beam2D`** — `Beam` subclass with lazy 2-D blank outline, polygon, and AABB used for all intersection and topology operations.
* **`ConnectionSolver2D`** — classifies beam pairs into L / T / X / face-to-face topologies using blank-outline endpoint containment.
* **`OpeningPopulatorAgent`** — creates header, sill (windows only), king studs, and optional jack studs (lintel posts) for `Opening` panel features.  Punches through sheathing plates on non-framing layers.

#### New GH components

* `CT: Panel` — creates a `Panel` from a closed polyline outline, thickness, optional normal vector, and optional `Opening` features.
* `CT: PlateFromBrep` — creates a `Plate` from an arbitrary Brep.
* `CT: BeamFromBox` — creates a `Beam` from a box-shaped Brep using an oriented bounding box.
* `CT: StudPanel` — calls `stud_panel()` with all parameters exposed as GH inputs; returns a `PanelPopulatorConfig` ready to pass to `CT: Model`.
* `CT: RecessPanel` — calls `recess_panel()` with all parameters exposed as GH inputs.
* `CT: PopulatorConfig` — wraps `PanelPopulatorConfig` directly for fully custom layer stacks.
* `CT: PopulatorAgent` — dynamic component that introspects `LayerAgentConfig` subclasses; output nickname selects the agent type at runtime.
* `CT: PopulatorLayer` — wraps `LayerConfig` (thickness, name, agent configs, sublayers, framing flag).

#### Other additions

* `JointRuleSolver.max_rule_distance` property — returns the maximum of all per-rule `max_distance` values.
* `get_guid_and_geometry` helper in `ghcomponent_helpers` — tries to resolve a Rhino object reference by GUID before falling back to raw geometry, enabling stable reference tracking across GH recomputes.
* New test modules: `test_agent_intersection`, `test_connection_solver_2d`, `test_panel_populator_workflow`, `test_populators`.

### Changed

* **`CT: Model`** — `Containers` input replaced by `PanelConfigs`.  `connect_adjacent_beams`, `connect_adjacent_plates`, and `connect_adjacent_panels` are now called directly in the component (previously delegated to `get_clusters_from_model`).  Panel population calls `create_populator()`, `populate_elements()`, `join_elements()`, and `merge_with_model()` for each config.  The old slab/wall populator wiring is removed.
* **`CT: BeamFromLineCurve`** (was `CT: Beam`) — renamed for clarity.
* **`JointRuleSolver._joints_from_rules_and_clusters`** — made public as `joints_from_rules_and_clusters`; `rules` argument removed (always uses `self.rules`).
* **`get_clusters_from_model`** — `max_cluster_size` parameter removed; new `ignore_joints` flag (default `True`) uses `model.unpromoted_joint_candidates` instead of `model.joint_candidates`, avoiding double-processing of already-joined element pairs.

### Removed

* `CT: Slab`, `CT: Wall`, `CT: WallConfigSet` GH components.
* `wall_populator.py`, `wall_from_surface.py`, `wall_details.py` source modules.


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

