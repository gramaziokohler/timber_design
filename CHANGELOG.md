# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Changed

#### Panel layers moved to `compas_timber`; populator config classes removed

The cross-section layer model moved upstream into `compas_timber`, and the
configuration layer in `timber_design.populators` was collapsed into the
populator and agents.  This significantly simplifies the populator subsystem
described below (which now reflects the pre-existing, config-based design and is
being updated).

* **`Layer` lives on the `Panel` (`compas_timber`).** `Panel.define_core_layer(start, end)`
  slices the panel into `exterior_layer` / `core_layer` / `interior_layer`
  (degenerate zero-thickness layers are skipped → ``None``).  Each `Layer` *is a*
  `Panel`, participates in the model tree (its `modeltransformation` propagates
  through the hierarchy), and is added to the model as a child of its panel.
  `Panel.layer_tree` exposes layers keyed by hierarchical path.
* **`PanelPopulator` replaces `PanelPopulatorConfig`.** It is built directly from
  a panel + a list of agents.  All the `*Config` dataclasses
  (`PanelPopulatorConfig`, `LayerConfig`, `LayerAgentConfig`, `FeatureAgentConfig`,
  `EdgePopulatorAgentConfig`, `StudPopulatorAgentConfig`,
  `OpeningPopulatorAgentConfig`, …) were removed; agents take their parameters
  (beam widths, joint-rule overrides, stud spacing, …) as explicit constructor
  keyword arguments.
* **Populator panel + layer mirroring.** `PanelPopulator` only creates layers on
  its own internal populator-space panel — never on the original.  In a deferred
  `prepare()` step (run on first `populate_elements`) it mirrors the panel's
  layer structure onto the populator panel, re-points each agent at the mirror,
  and rebases feature geometry — so agents generate against the panel's *final*
  layer geometry (after any panel-joinery extensions).
* **Layer-aware merge.** `PanelPopulator.merge_with_model` transforms each
  generated element from populator space into its owning **original-panel layer's**
  local frame and parents it there, so framing is grouped by layer in the model
  tree and moves with the layer.
* **`standard_beam_width` and joint-rule overrides** are resolved on the
  populator: `resolve_beam_widths` fills unset per-category widths, and
  `route_rule_overrides` distributes `CategoryRule` overrides to the agents that
  own each category.
* **`PanelPopulator.populate_elements` / `trim_elements`** are now driven by the
  populator's flat agent list (the per-layer `layer.agents` back-reference was
  removed); `trim_elements` scopes each cut to same-layer peers.

#### Model joinery workflow (`compas_timber` + `CT: Model`)

* **`TimberModel.process_joinery(include_panels=True)`** — new parameter.  Pass
  `include_panels=False` to skip joints that involve a `Panel`, for use after
  `process_panel_joinery` has already extended the panels (panel-joint layer
  extensions are not idempotent and must not be applied twice).
* **`CT: Model` workflow reordered** so panel joinery runs *before* population:
  add elements (with `reset()` for clean re-solves) → `connect_adjacent_panels`
  + promote → `process_panel_joinery` (extend layer_panels) → run populators →
  `connect_adjacent_beams`/`plates` + promote → `process_joinery(include_panels=False)`
  → user features.  This fixes accumulation / double-processing on re-runs.
* **`Panel.model` setter is idempotent** — re-adding a panel to its model no
  longer raises “Element already in the model”; layers already attached are
  skipped.

### Added

#### Panel Populator subsystem (`timber_design.populators`)

A new `timber_design.populators` package replaces the old wall-populator module with a general, layer-based panel framing system.

##### Configs and pipeline

* **`LayerConfig` / `Layer`** — `LayerConfig` is a pure-data blueprint (thickness, name, `agent_configs`, optional `sublayers`).  `Layer` *is a* `compas_timber.elements.Panel` (the layer's sliced cross-section) and additionally holds the agents registered on it, a `parent_layer` reference, and a `sublayer_list`.  `LayerConfig.model_from_panel(panel)` resolves fill-remaining (`thickness=None`) thicknesses with a two-pass bottom-up / top-down algorithm, then walks the definition tree to produce a `TimberModel` of `Layer` objects using *outline chaining* — each layer's far boundary is reused as the next layer's near boundary, eliminating floating-point discrepancies at shared faces.
* **`PanelPopulatorConfig`** — top-level config that wraps the user's `layer_defs` list as sublayers of an internal `root_layer_def`, holds `default_feature_configs` / `instance_feature_configs`, and orchestrates the build via these public methods:
  * `get_populator_panel()` — transforms the source panel to flat 2-D populator space.
  * `resolve_beam_widths()` — fills every agent config's `beam_widths` dict with the panel-wide `standard_beam_width`.
  * `create_populator_model()` — runs `resolve_beam_widths()` then delegates to `LayerConfig.model_from_panel`.
  * `create_feature_agents()` — instantiates feature agents from `default_feature_configs` / `instance_feature_configs`, resolving each config's `framing_layer_defs` / `trimming_layer_defs` to concrete `Layer` instances.
  * `create_populator()` — full pipeline that returns a ready-to-run `PanelPopulator`.
  * `route_rule_overrides(rules)` — distributes a list of `CategoryRule` overrides across the right agent configs (see *Joint-rule routing* below).
* **`stud_panel()`** (`populator_configs.stud_panel_config`) — factory returning a `PanelPopulatorConfig` for standard stud-wall framing.  Parameters: `panel`, `standard_beam_width`, `stud_spacing`, `stud_width`, `edge_stud_width`, `top_plate_beam_width`, `bottom_plate_beam_width`, `standard_beam_width_increment`, `orientation`, `sheeting_outside`, `sheeting_inside`, `joint_rule_overrides`, `default_feature_configs`, `instance_feature_configs`.  Opening-specific options (`lintel_posts`, `split_bottom_plate_beam`, `header_width`, `sill_width`, `king_stud_width`, `jack_stud_width`) are now configured on an `OpeningPopulatorAgentConfig` passed via `default_feature_configs[Opening]`.
* **`recess_panel()`** (`populator_configs.recess_panel_config`) — factory returning a `PanelPopulatorConfig` for recessed-frame panels.  Same per-category-width and `joint_rule_overrides` surface as `stud_panel()`, plus `recess_beam_width`, `recess_beam_height`, `sheeting_recess`.
* **`PanelPopulator`** — orchestrates the full population sequence: `populate_elements()` runs generate → extend → trim → add to internal model; `join_elements()` runs within-agent joints then cross-agent joints; `process_joinery()` applies BTLx features; `merge_with_model()` transforms surviving elements back to world space and attaches them to the original panel.

##### Agent hierarchy

* **`PopulatorAgent`** (abstract) — common base for both layer- and feature-bound agents.  Owns the unified element/outline machinery: `elements_for_layer(layer)` / `set_elements_for_layer(layer, elements)` (default: single flat list, overridden by `FeatureAgent` for per-layer buckets); `outline_for_layer(layer)` (default: `self.outline`, overridden by `FeatureAgent` for per-layer outlines); `trim_beam(beam, layer)` / `trim_plate(plate)` / `cull_element_at_point(point, layer)` resolve their boundary via `outline_for_layer(layer)`; `trim_elements()` is a concrete base method that iterates `_trim_layers()` and trims every peer agent's same-layer elements — no per-subclass override required.
* **`LayerAgent`** (abstract) — adds a single `layer` reference and a `beam_from_category` convenience that defaults `layer` to `self.layer`.  Subclasses: `EdgePopulatorAgent`, `StudPopulatorAgent`, `PlatePopulatorAgent`, `RecessPopulatorAgent`, `PanelBoundaryPopulatorAgent`.
* **`FeatureAgent`** (abstract) — for agents that span multiple layers (openings, etc.).  Tracks per-layer elements in `_elements_by_layer` and per-layer outlines in `_outline_by_layer`; overrides `elements_for_layer` / `set_elements_for_layer` / `outline_for_layer` to use those buckets, and overrides `_trim_layers()` to return `element_layers + trimming_layers`.  Subclass: `OpeningPopulatorAgent`.
* **Same-layer trim scoping** — `LayerAgent.trim_elements()` only ever touches the portion of a peer's elements that live on the same layer (via `agent.elements_for_layer(self.layer)`), so a layer agent never cuts framing that belongs to a different layer.
* **Per-layer outline & extension** — `OpeningPopulatorAgent.generate_elements_for_layer` writes its outline into `_outline_by_layer[layer.layer_index]`; `OpeningPopulatorAgent.extend_elements` extends each layer's king/jack studs only against that layer's peer agents, fixing a cross-layer extension leak.
* **Edge corner joints** — `EdgePopulatorAgent._edge_joint_rule` dispatches by geometry: perpendicular (clean vertical) edges use `get_direct_rule_from_elements` so `internal_joint_overrides` apply; sloped/chamfered edges fall through to the geometric `_create_edge_beam_joint_rule` that computes miter/butt cut planes from the bevel.
* **`OpeningPopulatorAgent`** — creates header, sill (windows only), king studs, and optional jack studs (lintel posts) for `Opening` panel features.  Punches through sheathing plates on every layer in its `trimming_layers`.  The corner cull (`_cull_stud`) is now also honored when a stud doesn't cross the opening outline, so studs that overlap a king/jack stud without entering the opening zone are removed.

##### Joint-rule overrides

* Each agent config carries split `internal_joint_overrides` / `external_joint_overrides` lists (`CategoryRule` lists).  These are merged into `self.internal_rules` / `self.external_rules` at agent construction time via `_apply_overrides`, which preserves multiple rules for the same ordered pair when their `joint_type.SUPPORTED_TOPOLOGY` differs (e.g. a `TButtJoint` and an `LButtJoint` for the same `(stud, top_plate_beam)` pair both survive).  Order matters for `TOPO_T` / `TOPO_EDGE_FACE`; other topologies dedup by unordered pair.
* `PanelPopulatorConfig.route_rule_overrides(rules)` lets a caller hand the panel a single rule list; each rule is dispatched to whichever agents own its categories: both categories owned by one agent → `internal_joint_overrides`; one category owned → `external_joint_overrides`; neither → skipped.  `stud_panel()` and `recess_panel()` both forward their `joint_rule_overrides` argument through this method.
* **Cross-agent override precedence** — `PanelPopulator.create_cross_agent_joints` prepends both agents' raw `external_overrides` ahead of their merged rule lists, so a per-agent override always wins against another agent's base rule for the same category pair, regardless of agent ordering.

##### 2-D geometry / topology

* **`Beam2D`** — `Beam` subclass with lazy 2-D blank outline, polygon, and AABB used for all intersection and topology operations.
* **`AABB2D`** — lightweight 2-D bounding box that avoids `ZeroDivisionError` on flat (z=0) geometry.
* **`ConnectionSolver2D`** — classifies beam pairs into TOPO_L / TOPO_T / TOPO_X / TOPO_FACE_FACE using blank-outline endpoint containment.  Used by `create_cross_agent_joints` to feed clusters into `JointRuleSolver`.
* **`find_beam_outline_crossings`** — desync-tolerant walk that opens fresh entries when boundary-coincident crossings are filtered in step 1 (fixes a `'NoneType' has no attribute 'internal_dots'` crash with non-convex outlines).
* **`extend_beam_to_closest_agents(beam, agents, layer=None)`** — accepts an optional layer and resolves each peer's outline via `outline_for_layer(layer)`, so a feature peer contributes only its boundary on the relevant layer.

#### GH components

* **`CT: StudPanel`** — `stud_panel()` wrapper.  Inputs: `panel`, `standard_beam_width`, `stud_spacing`, `stud_width`, `edge_stud_width`, `top_plate_beam_width`, `bottom_plate_beam_width`, `standard_beam_width_increment`, `orientation`, `sheeting_outside`, `sheeting_inside`, `joint_rule_overrides` (list), `default_feature_configs` (list), `instance_feature_configs` (list).
* **`CT: RecessPanel`** — `recess_panel()` wrapper.  Same shape as `CT: StudPanel` with recess-specific inputs.
* **`CT: PopulatorConfig`** — wraps `PanelPopulatorConfig` directly for fully custom layer stacks.  Applies `joint_rule_overrides` via `config.route_rule_overrides(...)` after construction.
* **`CT: PopulatorAgent`** — dynamic configurator for `LayerAgentConfig` subclasses; output nickname selects the agent type at runtime.  Permanent inputs: `internal_joint_overrides`, `external_joint_overrides`.
* **`CT: FeatureAgentConfig`** — dynamic configurator for `FeatureAgentConfig` subclasses.  Permanent inputs: `element_layers`, `trimming_layers`, `internal_joint_overrides`, `external_joint_overrides`.
* **`CT: PopulatorLayer`** — `LayerConfig` wrapper (thickness, name, `agent_configs`, sublayers).
* **`CT: Panel`** — creates a `Panel` from a closed polyline outline, thickness, optional normal vector, and optional `Opening` features.
* **`CT: PlateFromBrep`** — creates a `Plate` from an arbitrary Brep.
* **`CT: BeamFromBox`** — creates a `Beam` from a box-shaped Brep using an oriented bounding box.

#### Other additions

* `JointRuleSolver.max_rule_distance` property — returns the maximum of all per-rule `max_distance` values.
* `get_guid_and_geometry` helper in `ghcomponent_helpers` — tries to resolve a Rhino object reference by GUID before falling back to raw geometry, enabling stable reference tracking across GH recomputes.
* New test modules: `test_agent_intersection`, `test_connection_solver_2d`, `test_panel_populator_workflow`, `test_populators` (the last including a `TestRouteRuleOverrides` suite for the new rule-routing).

### Changed

* **`CT: Model`** — `Containers` input replaced by `PanelConfigs`.  `connect_adjacent_beams`, `connect_adjacent_plates`, and `connect_adjacent_panels` are now called directly in the component.  Panel population calls `create_populator()`, `populate_elements()`, `join_elements()`, `process_joinery()`, and `merge_with_model()` for each config.  The old slab/wall populator wiring is removed.
* **`CT: BeamFromLineCurve`** (was `CT: Beam`) — renamed for clarity.
* **`JointRuleSolver._joints_from_rules_and_clusters`** — made public as `joints_from_rules_and_clusters`; `rules` argument removed (always uses `self.rules`).
* **`get_clusters_from_model`** — `max_cluster_size` parameter removed; new `ignore_joints` flag (default `True`) uses `model.unpromoted_joint_candidates` instead of `model.joint_candidates`, avoiding double-processing of already-joined element pairs.

### Fixed

* **`stud_panel()` no longer leaks state across calls** — `stud_panel()` used to mutate the caller-supplied `OpeningPopulatorAgentConfig`'s `framing_layer_defs` / `trimming_layer_defs` in place.  When the same upstream config was shared between multiple `stud_panel()` invocations (the common GH "list of panels" case), the last call's `LayerConfig` references would win and earlier panels' opening agents pointed at layers whose `resulting_layer` was never set, eventually crashing in `_create_frame_polylines` with `'NoneType' object has no attribute 'planes'`.  `stud_panel()` now shallow-copies both the dict and the opening config before injecting the layer references.

### Removed

* `is_framing_layer` flag on `LayerConfig` / `Layer` — feature configs now declare layer scope explicitly via `framing_layer_defs` / `trimming_layer_defs`.
* `lintel_posts`, `split_bottom_plate_beam` from `stud_panel()` — moved to `OpeningPopulatorAgentConfig`.
* `beam_width_overrides` dict, `edge_beam_min_width` — replaced by explicit per-category width fields on each agent config (`edge_stud_width`, `top_plate_beam_width`, `bottom_plate_beam_width`, `stud_width`, `header_width`, etc.).
* `joint_rule_overrides` on `PanelPopulatorConfig.__init__` — replaced by the `route_rule_overrides(rules)` method.
* `LayerAgent.trim_within_layer`, `trim_cross_layer`, `trim_other_layers`, `_trim_element_list`, `resolve_beam_dimensions`, `apply_to_plate` — consolidated to a single concrete `PopulatorAgent.trim_elements()` driven by the `_trim_layers()` hook.
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

