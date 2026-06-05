# Panel populator subsystem — layered framing, per-agent overrides, GH workflow

## Summary

This PR rewrites the wall-populator as a generic, layer-based **panel populator**:

- A panel is described by an ordered list of **`LayerConfig`** blueprints (with optional nested `sublayers`).
- Each layer holds **agent configs** that produce framing elements (`LayerAgentConfig`) or react to panel features such as openings (`FeatureAgentConfig`).
- **`PanelPopulatorConfig`** ties it all together and produces a **`PanelPopulator`** that runs a fixed generate → extend → trim → join → process → merge pipeline.
- Two convenience factories — **`stud_panel()`** and **`recess_panel()`** — wire up the common framing systems.
- A new **GH workflow** exposes the whole thing: `CT: PopulatorLayer`, `CT: PopulatorAgent`, `CT: FeatureAgentConfig`, `CT: StudPanel`, `CT: RecessPanel`, `CT: PopulatorConfig` → `CT: Model`.

The intent is to (a) give a single, composable model for any panel cross-section we're likely to need (multi-layer walls, recessed panels, nested insulation cores, etc.), (b) keep the per-pair behaviour of the joint solver where each agent can have its own overrides, and (c) make Grasshopper feel like data flowing through configs into a populator, not like a wall of script.

A fuller migration guide and a complete worked example live in `docs/user_guide/populating_panels.md`; the contributor-facing diagrams are in `docs/contribution/class_diagrams.md`.

---

## Architecture

### Agent hierarchy

```mermaid
classDiagram
    direction TB

    class PopulatorAgent {
        <<abstract>>
        +BEAM_CATEGORY_NAMES: list[str]
        +INTERNAL_JOINT_RULES: list[CategoryRule]
        +EXTERNAL_JOINT_RULES: list[CategoryRule]
        +BOUNDARY_TYPE: AgentBoundaryType
        +beam_widths: dict
        +internal_rules / external_rules: list
        +elements: list
        +outline: Polyline
        +outline_for_layer(layer)
        +elements_for_layer(layer)
        +set_elements_for_layer(layer, elements)
        +trim_beam(beam, layer)
        +trim_plate(plate)
        +trim_agent_elements(other, layer)
        +trim_elements()
        +cull_element_at_point(point, layer)
        +cull_beam_segment(beam)
        +create_joint_candidates()
        +create_joint_defs()
        +generate_elements()*
        +extend_elements()
        +is_on_layer(layer)
    }

    class LayerAgent {
        <<abstract>>
        +layer: Layer
        +layer_index: int
        +layer_center_height: float
        +panel
        +beam_from_category(centerline, category, layer)
    }

    class FeatureAgent {
        <<abstract>>
        +feature: PanelFeature
        +element_layers / trimming_layers: list[Layer]
        +registered_layers: list[Layer]
        -_elements_by_layer: dict
        -_outline_by_layer: dict
        +register_on_layer(layer)
        +generate_elements_for_layer(layer)*
    }

    class EdgePopulatorAgent
    class StudPopulatorAgent
    class PlatePopulatorAgent
    class RecessPopulatorAgent
    class OpeningPopulatorAgent

    PopulatorAgent <|-- LayerAgent
    PopulatorAgent <|-- FeatureAgent
    LayerAgent <|-- EdgePopulatorAgent
    LayerAgent <|-- StudPopulatorAgent
    LayerAgent <|-- PlatePopulatorAgent
    EdgePopulatorAgent <|-- RecessPopulatorAgent
    FeatureAgent <|-- OpeningPopulatorAgent
```

Key shape of the base:

- The `_trim_layers()` hook drives a single, concrete `trim_elements()` on the base class. `LayerAgent` returns `[self.layer]`; `FeatureAgent` returns `element_layers + trimming_layers`. No per-subclass trim override is needed.
- `outline_for_layer(layer)` returns `self.outline` for layer agents and the per-layer boundary for feature agents, so trimming/culling on a given layer uses the correct boundary even when the feature frames on several layers.
- `EdgePopulatorAgent._edge_joint_rule` picks between the geometric miter/butt logic (for sloped edges that need bevel-aware cut planes) and the rule-based path (for perpendicular edges, so `internal_joint_overrides` take effect).

### Configs and the top-level orchestrator

```mermaid
classDiagram
    direction TB

    class PanelPopulatorConfig {
        +panel: Panel
        +orientation: Vector
        +root_layer_def: LayerConfig
        +default_feature_configs: dict
        +instance_feature_configs: list
        +standard_beam_width: float
        +get_populator_panel()
        +resolve_beam_widths()
        +create_populator_model()
        +create_feature_agents()
        +create_populator()
        +route_rule_overrides(rules)
    }
    class LayerConfig {
        +thickness: float | None
        +name: str
        +agent_configs: list
        +sublayers: list
        +position: float
        +resulting_layer: Layer
        +model_from_panel(panel)
    }
    class Layer {
        +layer_index, name
        +parent_layer, sublayer_list
        +outline_a, outline_b
        +thickness, center_height
        +agents: list
        +elements: list
        +from_panel_and_range(panel, a, b)$
    }
    class PopulatorAgentConfig {
        <<abstract>>
        +internal_joint_overrides
        +external_joint_overrides
        +beam_widths: dict
        +fill_beam_widths(width)
    }
    class LayerAgentConfig {
        <<abstract>>
        +get_agent_from_layer(layer)
    }
    class FeatureAgentConfig {
        <<abstract>>
        +framing_layer_defs: list[LayerConfig]
        +trimming_layer_defs: list[LayerConfig]
        +get_agent_from_feature(feature, element_layers, trimming_layers)
    }
    class stud_panel {
        <<factory>>
        returns PanelPopulatorConfig
    }
    class recess_panel {
        <<factory>>
        returns PanelPopulatorConfig
    }

    stud_panel ..> PanelPopulatorConfig
    recess_panel ..> PanelPopulatorConfig
    PanelPopulatorConfig "1" *-- "1..*" LayerConfig : root + sublayers
    LayerConfig "0..*" --> LayerConfig : sublayers
    LayerConfig --> Layer : produces via model_from_panel
    LayerConfig --> LayerAgentConfig : carries
    PanelPopulatorConfig --> FeatureAgentConfig : default + instance configs
    PopulatorAgentConfig <|-- LayerAgentConfig
    PopulatorAgentConfig <|-- FeatureAgentConfig
```

### Pipeline / user workflow

```mermaid
flowchart LR
    classDef element fill:#d4edda,stroke:#28a745,color:#000
    classDef agentcfg fill:#cce5ff,stroke:#004085,color:#000
    classDef layerdef fill:#fff3cd,stroke:#856404,color:#000
    classDef config   fill:#e2d9f3,stroke:#6f42c1,color:#000
    classDef stage    fill:#f8f9fa,stroke:#6c757d,color:#000
    classDef model    fill:#f8d7da,stroke:#721c24,color:#000

    panel(["Panel"]):::element
    opening(["Opening feature"]):::element
    opening -->|"panel.add_feature()"| panel

    plateCfgExt(["PlatePopulatorAgentConfig"]):::agentcfg
    edgeCfg(["EdgePopulatorAgentConfig"]):::agentcfg
    studCfg(["StudPopulatorAgentConfig<br>stud_spacing=625"]):::agentcfg
    plateCfgInt(["PlatePopulatorAgentConfig"]):::agentcfg
    openingCfg(["OpeningPopulatorAgentConfig<br>lintel_posts=True"]):::agentcfg

    subgraph layer_defs[" layer_defs "]
        direction TB
        ldInt["LayerConfig<br>'interior' · 15 mm"]:::layerdef
        ldFrame["LayerConfig<br>'frame' · fill"]:::layerdef
        ldExt["LayerConfig<br>'exterior' · 22 mm"]:::layerdef
        plateCfgInt -->|agent_configs| ldInt
        edgeCfg     -->|agent_configs| ldFrame
        studCfg     -->|agent_configs| ldFrame
        plateCfgExt -->|agent_configs| ldExt
    end

    config["PanelPopulatorConfig<br>standard_beam_width=60"]:::config

    panel      --> |panel| config
    ldInt      --> |layer_defs| config
    ldFrame    --> |layer_defs| config
    ldExt      --> |layer_defs| config
    openingCfg -->|"default_feature_configs[Opening]"| config

    subgraph pop[" PanelPopulator "]
        direction TB
        gen["populate_elements()<br>generate → extend → trim → add"]:::stage
        join["join_elements()<br>within-agent → cross-agent"]:::stage
        proc["process_joinery()"]:::stage
        merge["merge_with_model()"]:::stage
        gen --> join --> proc --> merge
    end

    config -->|"create_populator()"| gen

    model[("TimberModel")]:::model
    merge --> model
```

In Python this collapses to:

```python
config = stud_panel(
    panel=panel,
    standard_beam_width=60,
    stud_spacing=625,
    sheeting_inside=15,
    sheeting_outside=22,
    default_feature_configs={
        Opening: OpeningPopulatorAgentConfig(lintel_posts=True, header_width=120),
    },
)
populator = config.create_populator()
populator.populate_elements()
populator.join_elements()
populator.process_joinery()
populator.merge_with_model(model)
```

---

## Joint-rule overrides

Two complementary surfaces:

1. **Per-agent overrides** — every agent config carries `internal_joint_overrides` and `external_joint_overrides`. These are merged into `INTERNAL_JOINT_RULES` / `EXTERNAL_JOINT_RULES` at agent construction time. The merge keys on **(SUPPORTED_TOPOLOGY, categories)**, so the same `(stud, top_plate_beam)` pair can carry both a `TButtJoint` and an `LButtJoint` — they target different cluster topologies and both survive.
2. **Panel-level routing** — `PanelPopulatorConfig.route_rule_overrides(rules)` (also exposed as the `joint_rule_overrides` argument on `stud_panel()` / `recess_panel()`) dispatches each `CategoryRule` to whichever agents own its categories — both categories on one agent → that agent's `internal_joint_overrides`; one category on each of two agents → both agents' `external_joint_overrides`; neither → skipped. Callers don't need to know which agent owns each pair.

Cross-agent precedence is solved at solve time: `PanelPopulator.create_cross_agent_joints` prepends both agents' *raw* `external_overrides` ahead of their merged rule lists, so a per-agent override always wins against the other agent's base rule for the same pair, regardless of agent ordering.

---

## GH workflow

```mermaid
flowchart LR
    classDef gh fill:#cce5ff,stroke:#004085,color:#000
    classDef rh fill:#d4edda,stroke:#28a745,color:#000

    rhPanel(["Rhino panel<br>(polyline + thickness)"]):::rh
    ctPanel["CT: Panel"]:::gh
    ctLayer["CT: PopulatorLayer"]:::gh
    ctAgent["CT: PopulatorAgent"]:::gh
    ctFeature["CT: FeatureAgentConfig"]:::gh
    ctStud["CT: StudPanel /<br>CT: RecessPanel /<br>CT: PopulatorConfig"]:::gh
    ctModel["CT: Model"]:::gh
    out(["TimberModel"]):::rh

    rhPanel --> ctPanel
    ctPanel -->|panel| ctStud
    ctAgent -->|agent_configs| ctLayer
    ctLayer -->|layer_defs| ctStud
    ctFeature -->|default_feature_configs| ctStud
    ctStud -->|PanelPopulatorConfig| ctModel
    ctModel --> out
```

`CT: StudPanel` / `CT: RecessPanel` are the friendly entry points for the two common framing systems; `CT: PopulatorConfig` is the escape hatch for fully custom layer stacks built from `CT: PopulatorLayer` + `CT: PopulatorAgent` + `CT: FeatureAgentConfig`.

---

## Notable bug fixes & gotchas worth a reviewer's eye

- **Shared-state bug in `stud_panel()`.** The factory used to mutate the caller-supplied `OpeningPopulatorAgentConfig`'s `framing_layer_defs` / `trimming_layer_defs` in place. When `CT: StudPanel` ran across a list of panels (or several `CT: StudPanel` components shared the same upstream `CT: FeatureAgentConfig`), the *last* call's `LayerConfig` references would win and earlier panels' opening agents pointed at layers whose `resulting_layer` was never set, eventually crashing in `_create_frame_polylines` with `'NoneType' object has no attribute 'planes'`. `stud_panel()` now shallow-copies the dict and the opening config before injecting the layer references.
- **`find_beam_outline_crossings` desync.** The boundary-coincident-crossing filter in step 1 could leave `current_entry` as `None` while the inside/outside walker still thought it was inside, crashing with `'NoneType' object has no attribute 'internal_dots'` on non-convex outlines (opening frames, in particular). The loop now opens a fresh wrap-around entry on demand.
- **Same-layer trim scoping.** `LayerAgent.trim_elements()` only ever touches `agent.elements_for_layer(self.layer)`, so a layer agent can never cut framing on a different layer. The opening agent's `extend_elements` was rebuilt to be strictly per-layer for the same reason.
- **Per-layer outlines on feature agents.** Multi-layer features previously left a single `self.outline` that was overwritten per layer iteration, so trimming/culling on every layer except the last used the wrong boundary. Now stored per layer via `_outline_by_layer` and resolved through `outline_for_layer(layer)`.

---

## Migration notes

For users coming from the previous `stud_panel()` signature:

- `lintel_posts`, `split_bottom_plate_beam`, `header_width`, `sill_width`, `king_stud_width`, `jack_stud_width` → moved to `OpeningPopulatorAgentConfig`, passed via `default_feature_configs[Opening]` (or `instance_feature_configs`).
- `beam_width_overrides={"header": 120, ...}` → set on the relevant agent config directly (e.g. `OpeningPopulatorAgentConfig(header_width=120)`).
- `edge_beam_min_width` → removed; explicit per-category widths cover this.
- `joint_rule_overrides` is still accepted as a flat list at the panel level, and is now dispatched via `route_rule_overrides`.
- `is_framing_layer` on `LayerConfig` → removed; feature configs name their layers via `framing_layer_defs` / `trimming_layer_defs` (the factories wire these up automatically).
- `create_populator_from_panel(panel)` → set `config.panel = panel` (or pass `panel=` to the factory) and call `config.create_populator()`.

---

## Testing

- `tests/test_populators.py` — agent factories, layer-config tree, `TestRouteRuleOverrides` for the new rule-routing.
- `tests/test_panel_populator_workflow.py` — end-to-end stud-wall / opening / recess / multi-panel / sheathing scenarios.
- `tests/test_connection_solver_2d.py` — pairwise topology classifier.
- `tests/test_agent_intersection.py` — `find_beam_outline_crossings` and `extend_beam_to_closest_agents`.
- All modified module files byte-compile cleanly. The suite has not been run end-to-end in this environment — please run `pytest tests/` against your usual venv (`compas_timber` + `Opening` available) before approving.

---

## Out of scope / follow-ups discussed but not in this PR

- **Occlusion-aware perimeter walk in `ConnectionSolver2D`** — design landed in a discussion thread (`find_beam_contacts` / `Beam2DCluster` + port/union-find clustering + role-based Y/K topology), to be implemented in a follow-up PR. Until then the new `LButtJoint` external rules on `StudPopulatorAgent` act as a hack for the "stud meets edge corner" case.
- **Wildcard `*` category + N-ary `CategoryRule`** — sketched in the same thread, on the table once a real Y/K joint is needed.
