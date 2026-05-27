# Class Diagrams

This section provides visual representations of the class hierarchies and relationships in the `timber_design` package.

[TOC]

## Populators Subsystem

### Orchestration

`PanelPopulatorConfig` holds all parameters for one panel type, resolves the layer stack from `LayerConfig` blueprints, and produces a ready-to-use `PanelPopulator`.

```mermaid
classDiagram

    class PanelPopulatorConfig {
        +panel : Panel
        +layer_defs : list[LayerConfig]
        +default_feature_configs : dict
        +instance_feature_configs : list
        +standard_beam_width : float
        +create_populator() PanelPopulator
        +get_populator_panel() Panel
        +create_layers(populator_panel) list[Layer]
        +create_feature_agents(layers) list[FeatureAgent]
        +resolve_beam_dimensions(layers, agents)
        +layers_from_panel_and_thicknesses(panel, thicknesses, layer_defs)$
    }

    class PanelPopulator {
        +panel : Panel
        +layers : list[Layer]
        +feature_agents : list[FeatureAgent]
        +original_panel : Panel
        +transformation_to_populator : Transformation
        +model : TimberModel
        +agents : list[LayerAgent]
        +populate_elements()
        +generate_elements()
        +extend_elements()
        +trim_elements()
        +add_elements_to_model()
        +join_elements()
        +create_agent_joints()
        +create_cross_agent_joints()
        +process_joinery()
        +merge_with_model(model, clear_panel)
    }

    class Layer {
        +panel : Panel
        +name : str
        +layer_index : int
        +is_framing_layer : bool
        +agents : list[LayerAgent]
        +thickness : float
        +center_height : float
        +elements : list
    }

    class LayerConfig {
        +thickness : float
        +name : str
        +is_framing_layer : bool
        +agent_configs : list[LayerAgentConfig]
        +sublayers : list[LayerConfig]
    }

    class ConnectionSolver2D {
        +find_intersecting_pairs(beams) list
        +find_intersecting_agent_pairs(agents) list
        +find_topology(beam_a, beam_b) Beam2DSolverResult
    }

    PanelPopulatorConfig --> PanelPopulator : creates
    PanelPopulatorConfig "1" *-- "1..*" LayerConfig : holds
    PanelPopulatorConfig --> Layer : creates via layers_from_panel_and_thicknesses
    PanelPopulator "1" *-- "1..*" Layer : owns
    PanelPopulator --> ConnectionSolver2D : uses
    Layer "1" *-- "1..*" LayerAgent : has registered
    LayerConfig --> LayerAgentConfig : carries
```

---

### Populator Configs

`PanelPopulatorConfig` is a concrete base class.  Convenience subclasses
(`StudPanelPopulatorConfig`, `RecessPanelPopulatorConfig`) pre-build the
`layer_defs` list for common framing systems.  Custom configs can also be
created by instantiating `PanelPopulatorConfig` directly with a `layer_defs`
list.

```mermaid
classDiagram

    class PanelPopulatorConfig {
        +panel : Panel
        +layer_defs : list[LayerConfig]
        +default_feature_configs : dict[type, LayerAgentConfig]
        +instance_feature_configs : list
        +standard_beam_width : float
        +create_populator() PanelPopulator
        +create_layers(populator_panel) list[Layer]
        +layers_from_panel_and_thicknesses(panel, thicknesses, defs)$
        -_resolve_thicknesses(root)
        -_infer_from_children(layer_def)
        -_distribute_to_children(layer_def)
    }

    class StudPanelPopulatorConfig {
        +standard_beam_width : float
        +stud_spacing : float
        +standard_beam_width_increment : float
        +edge_beam_min_width : float
        +stud_direction : Vector
        +sheeting_outside : float
        +sheeting_inside : float
        +lintel_posts : bool
        +split_bottom_plate_beam : bool
        +beam_width_overrides : dict
        +joint_rule_overrides : list
    }

    class RecessPanelPopulatorConfig {
        +standard_beam_width : float
        +recess_beam_width : float
        +recess_beam_height : float
        +edge_beam_min_width : float
        +standard_beam_width_increment : float
        +sheeting_outside : float
        +sheeting_inside : float
        +sheeting_recess : float
        +beam_width_overrides : dict
        +joint_rule_overrides : list
    }

    PanelPopulatorConfig <|-- StudPanelPopulatorConfig
    PanelPopulatorConfig <|-- RecessPanelPopulatorConfig
    PanelPopulatorConfig ..> LayerConfig : creates / reads
    PanelPopulatorConfig ..> LayerAgentConfig : reads default_feature_configs
```

---

### Layer and LayerConfig

`LayerConfig` is a pure data blueprint with no geometry.  `Layer` is the
resolved runtime object that holds geometry (a sliced panel) and the list of
agents registered on it.  The definition tree supports nested `sublayers` for
composite cross-sections; `thickness=None` on a leaf causes fill-remaining
resolution against the parent.

```mermaid
classDiagram

    class LayerConfig {
        +thickness : float | None
        +name : str
        +is_framing_layer : bool
        +agent_configs : list[LayerAgentConfig]
        +sublayers : list[LayerConfig]
    }

    class Layer {
        +panel : Panel
        +name : str
        +layer_index : int
        +is_framing_layer : bool
        +agents : list[LayerAgent]
        +thickness : float
        +center_height : float
        +elements : list
        +from_panel_and_range(panel, a, b, ...)$
    }

    LayerConfig "0..*" --> LayerConfig : sublayers
    LayerConfig --> LayerAgentConfig : carries agent_configs
    Layer "1" *-- "0..*" LayerAgent : registered agents
    PanelPopulatorConfig --> LayerConfig : reads (deep copy)
    PanelPopulatorConfig --> Layer : produces
```

---

### Populator Agents

`LayerAgent` is bound to exactly one `Layer`.  `FeatureAgent` extends it for
agents that span multiple layers (e.g. openings that cut through the full panel
cross-section).  Both types expose the same `elements_for_layer` /
`set_elements_for_layer` API so the orchestrator code is uniform.

```mermaid
classDiagram

    class LayerAgent {
        <<abstract>>
        +BEAM_CATEGORY_NAMES : list[str]$
        +INTERNAL_RULES : list[CategoryRule]$
        +EXTERNAL_RULES : list[CategoryRule]$
        +BOUNDARY_TYPE : AgentBoundaryType$
        +layer : Layer
        +layer_index : int
        +panel : Panel
        +elements : list[Beam2D | Plate]
        +outline : Polyline
        +internal_rules : list[CategoryRule]
        +external_rules : list[CategoryRule]
        +beam_dimensions : dict
        +joint_defs : list[DirectRule]
        +aabb : AABB2D
        +elements_for_layer(layer) list
        +set_elements_for_layer(layer, elements)
        +resolve_beam_dimensions(width, thickness)
        +beam_from_category(centerline, category, layer) Beam2D
        +generate_elements()*
        +extend_elements(other_agents)
        +trim_beam(beam) list[Beam2D]
        +_trim_element_list(elements) list
        +trim_within_layer(other_agent, layer)
        +trim_cross_layer(other_agent)
        +trim_other_layers(layers)
        +cull_beam_segment(beam) bool
        +cull_element_at_point(point) bool
        +create_joint_candidates(model, elements) list
        +create_internal_joint_defs(model, elements)
        +apply_to_plate(plate)
    }

    class FeatureAgent {
        <<abstract>>
        +feature : PanelFeature
        +registered_layers : list[Layer]
        -_elements_by_layer : dict[int, list]
        +elements_for_layer(layer) list
        +set_elements_for_layer(layer, elements)
        +register_on_layer(layer)
        +generate_elements(layers)*
        +generate_elements_for_layer(layer)*
        +trim_other_layers(layers)
    }

    class EdgePopulatorAgent {
        +BOUNDARY_TYPE = INCLUSIVE
        +BEAM_CATEGORY_NAMES = ["edge_stud", "top_plate_beam", "bottom_plate_beam"]
        +generate_elements()
        +create_internal_joint_defs(model, elements)
    }

    class StudPopulatorAgent {
        +BEAM_CATEGORY_NAMES = ["stud"]
        +generate_elements()
    }

    class PlatePopulatorAgent {
        +BEAM_CATEGORY_NAMES = ["plate"]
        +generate_elements()
    }

    class OpeningPopulatorAgent {
        +BOUNDARY_TYPE = EXCLUSIVE
        +FEATURE_TYPE = Opening
        +BEAM_CATEGORY_NAMES = ["header", "sill", "king_stud", "jack_stud"]
        +opening_type : str
        +lintel_posts : bool
        +split_bottom_plate_beam : bool
        +header : Beam2D
        +sill : Beam2D
        +king_studs : list[Beam2D]
        +jack_studs : list[Beam2D]
        +generate_elements_for_layer(layer) list
        +extend_elements(other_agents)
        +trim_cross_layer(other_agent)
        +apply_to_plate(plate)
    }

    class RecessPopulatorAgent {
        +BOUNDARY_TYPE = INCLUSIVE
        +BEAM_CATEGORY_NAMES = ["recess"]
        +recess_beam_width : float
        +recess_beam_height : float
        +sheeting_recess : float
        +generate_elements()
        +trim_cross_layer(other_agent)
        +apply_to_plate(plate)
    }

    class AgentBoundaryType {
        +NONE = "none"$
        +INCLUSIVE = "inclusive"$
        +EXCLUSIVE = "exclusive"$
    }

    LayerAgent <|-- FeatureAgent
    LayerAgent <|-- EdgePopulatorAgent
    LayerAgent <|-- StudPopulatorAgent
    LayerAgent <|-- PlatePopulatorAgent
    LayerAgent <|-- RecessPopulatorAgent
    FeatureAgent <|-- OpeningPopulatorAgent

    LayerAgent --> AgentBoundaryType : uses
    LayerAgent "1" *-- "0..*" Beam2D : owns
    FeatureAgent --> Layer : registers on
```

---

### Agent Configs

Each `LayerAgent` subclass has a matching config dataclass.  `FeatureAgentConfig`
adds `get_agent_from_feature` for agents that are driven by a
`PanelFeature`; it passes `layer=None` to the constructor because the agent
discovers its layers at generation time.

```mermaid
classDiagram

    class LayerAgentConfig {
        +AGENT_TYPE : type$
        +beam_width_overrides : dict
        +joint_rule_overrides : list[CategoryRule]
        +get_agent_from_layer(layer) LayerAgent
    }

    class FeatureAgentConfig {
        +get_agent_from_feature(feature) FeatureAgent
    }

    class EdgePopulatorAgentConfig {
        +AGENT_TYPE = EdgePopulatorAgent$
        +standard_beam_width_increment : float
        +edge_beam_min_width : float
    }

    class StudPopulatorAgentConfig {
        +AGENT_TYPE = StudPopulatorAgent$
        +stud_spacing : float
    }

    class PlatePopulatorAgentConfig {
        +AGENT_TYPE = PlatePopulatorAgent$
    }

    class OpeningPopulatorAgentConfig {
        +AGENT_TYPE = OpeningPopulatorAgent$
        +FEATURE_TYPE = Opening$
        +lintel_posts : bool
        +split_bottom_plate_beam : bool
    }

    class RecessPopulatorAgentConfig {
        +AGENT_TYPE = RecessPopulatorAgent$
        +recess_beam_width : float
        +recess_beam_height : float
        +sheeting_recess : float
    }

    LayerAgentConfig <|-- FeatureAgentConfig
    LayerAgentConfig <|-- EdgePopulatorAgentConfig
    LayerAgentConfig <|-- StudPopulatorAgentConfig
    LayerAgentConfig <|-- PlatePopulatorAgentConfig
    LayerAgentConfig <|-- RecessPopulatorAgentConfig
    FeatureAgentConfig <|-- OpeningPopulatorAgentConfig

    EdgePopulatorAgentConfig <|-- RecessPopulatorAgentConfig
```

---

### 2D Geometry

`Beam2D` extends compas_timber's `Beam` with a lazy 2D blank outline used for
all intersection and topology detection operations. `AABB2D` is a lightweight
2D bounding box that avoids the `ZeroDivisionError` that `compas.geometry.Box`
raises on flat z=0 geometry.

```mermaid
classDiagram

    class Beam {
        +frame : Frame
        +length : float
        +width : float
        +height : float
        +centerline : Line
        +ref_sides : list[Frame]
        +from_centerline(centerline, width, height)$
    }

    class Beam2D {
        +edge_a : Line
        +edge_b : Line
        +start_segment : Line
        +end_segment : Line
        +blank_outline : Polyline
        +blank_polygon : Polygon
        +aabb : AABB2D
        +contains_point(point, tolerance) bool
        +get_beam_segment(start_length, end_length) Beam2D
        +transform(transformation)
        -_blank_outline : Polyline
        -_blank_polygon : Polygon
    }

    class AABB2D {
        +xmin : float
        +xmax : float
        +ymin : float
        +ymax : float
        +points : list[Point]
        +from_points(points)$
    }

    Beam <|-- Beam2D
    Beam2D ..> AABB2D : computes
```

---

### Connection Solver and Intersection Utilities

`ConnectionSolver2D` uses blank-outline endpoint containment to classify beam
pairs into L, T, X, or face-to-face topologies.
`BeamOutlineIntersectionData` stores the entry/exit dot positions where an
agent outline crosses a beam blank, used by `trim_beam` to split beams at
agent boundaries.

```mermaid
classDiagram

    class ConnectionSolver2D {
        +find_intersecting_pairs(beams) list
        +find_intersecting_agent_pairs(agents) list
        +find_topology(beam_a, beam_b) Beam2DSolverResult
    }

    class Beam2DSolverResult {
        +beam_a : Beam2D
        +beam_b : Beam2D
        +distance : float
        +topology : JointTopology
        +location : Point
    }

    class BeamOutlineIntersectionData {
        +start_dot : float
        +end_dot : float
        +internal_dots : list[float]
        +all_dots : list[float]
        +average_dot : float
    }

    class JointTopology {
        +TOPO_L = 1$
        +TOPO_T = 2$
        +TOPO_X = 3$
        +TOPO_FACE_FACE = 9$
    }

    ConnectionSolver2D ..> Beam2DSolverResult : returns
    ConnectionSolver2D ..> AABB2D : uses for overlap tests
    ConnectionSolver2D ..> BeamOutlineIntersectionData : uses via find_beam_outline_crossings
    Beam2DSolverResult --> JointTopology : classifies
```
