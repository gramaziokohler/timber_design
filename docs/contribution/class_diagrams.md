# Class Diagrams

This section provides visual representations of the class hierarchies and relationships in the `timber_design` package.

[TOC]

## Populators Subsystem

### Orchestration

`PanelPopulatorConfig` combines configuration data and factory behaviour into a single object.
Call `create_populator(panel)` to get a ready-to-use `PanelPopulator`.

```mermaid
classDiagram

    class PanelPopulator {
        +original_panel : Panel
        +panel : Panel
        +transformation_to_populator : Transformation
        +agents : list[PopulatorAgent]
        +model : TimberModel
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

    class PanelPopulatorConfig {
        <<abstract>>
        +panel : Panel
        +default_feature_configs : dict
        +create_populator_from_panel(panel, feature_configs) PanelPopulator
        +create_populator(feature_configs) PanelPopulator
        +create_populator_agents(layers)* list
        -_prepare_panels(panel) tuple
        -_get_projected_orientation(panel) Vector
    }

    class ConnectionSolver2D {
        +max_distance : float
        +find_intersecting_pairs(beams) : list
        +find_intersecting_agent_pairs(agents) : list
        +find_topology(beam_a, beam_b) : Beam2DSolverResult
    }

    PanelPopulatorConfig --> PanelPopulator : creates
    PanelPopulator --> ConnectionSolver2D : uses
    PanelPopulator "1" *-- "1..*" PopulatorAgent : orchestrates
```

---

### Populator Configs

Each concrete config subclass holds all parameters for one panel type and implements
`create_populator_agents`.  `default_feature_configs` maps panel-feature types to
`PopulatorAgentConfig` instances (no `feature` set) for automatic per-feature agent
creation using MRO-based lookup.

```mermaid
classDiagram

    class PanelPopulatorConfig {
        <<abstract>>
        +panel : Panel
        +default_feature_configs : dict[type, PopulatorAgentConfig]
        +create_populator_from_panel(panel, feature_configs) PanelPopulator
        +create_populator(feature_configs) PanelPopulator
        +create_populator_agents(layers)* list
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
        +create_populator_agents(layers) list
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
        +create_populator_agents(layers) list
    }

    %% Inheritance
    PanelPopulatorConfig <|-- StudPanelPopulatorConfig
    PanelPopulatorConfig <|-- RecessPanelPopulatorConfig

    %% Associations
    PanelPopulatorConfig ..> PopulatorAgent : creates
    PanelPopulatorConfig ..> PopulatorAgentConfig : reads default_feature_configs
```

---

### Populator Agents

Each `PopulatorAgent` subclass is responsible for one logical group of framing elements.
The abstract base class defines the trimming, extending, and joint-creation interface.
Every concrete agent declares the feature class it handles via `FEATURE_TYPE`.

```mermaid
classDiagram

    class PopulatorAgent {
        <<abstract>>
        +FEATURE_TYPE : type$
        +BEAM_CATEGORY_NAMES : list[str]$
        +INTERNAL_RULES : list[CategoryRule]$
        +BOUNDARY_TYPE : FeatureBoundaryType$
        +feature : Panel | PanelFeature
        +panel : Panel
        +elements : list[Beam2D | Plate]
        +outline : Polyline
        +rules : list[CategoryRule]
        +beam_dimensions : dict
        +joint_defs : list[DirectRule]
        +aabb : AABB2D
        +resolve_beam_dimensions(frame_thickness, standard_beam_width)
        +beam_from_category(centerline, category) Beam2D
        +generate_elements()*
        +extend_elements(other_agents)
        +trim_beam(beam) list[Beam2D]
        +trim_elements_with_agent(agent)
        +cull_beam_segment(beam) bool
        +cull_element_at_point(point) bool
        +create_joint_candidates(model) list
        +create_internal_joint_defs(model)
        +apply_to_plate(plate)
    }

    class EdgePopulatorAgent {
        +FEATURE_TYPE = Panel
        +BEAM_CATEGORY_NAMES = ["edge_stud", "top_plate_beam", "bottom_plate_beam"]
        +BOUNDARY_TYPE = INCLUSIVE
        +generate_elements()
        +create_internal_joint_defs(model)
    }

    class StudPopulatorAgent {
        +FEATURE_TYPE = Panel
        +BEAM_CATEGORY_NAMES = ["stud"]
        +generate_elements()
    }

    class PlatePopulatorAgent {
        +FEATURE_TYPE = Panel
        +BEAM_CATEGORY_NAMES = ["inside_plate", "outside_plate"]
        +generate_elements()
    }

    class OpeningPopulatorAgent {
        +FEATURE_TYPE = Opening
        +BEAM_CATEGORY_NAMES = ["header", "sill", "king_stud", "jack_stud"]
        +BOUNDARY_TYPE = EXCLUSIVE
        +opening_type : str
        +lintel_posts : bool
        +split_bottom_plate_beam : bool
        +header : Beam2D
        +sill : Beam2D
        +king_studs : list[Beam2D]
        +jack_studs : list[Beam2D]
        +left_king_stud : Beam2D
        +right_king_stud : Beam2D
        +generate_elements()
        +extend_elements(other_agents)
        +apply_to_plate(plate)
    }

    class RecessPopulatorAgent {
        +FEATURE_TYPE = Panel
        +BEAM_CATEGORY_NAMES = ["recess"]
        +BOUNDARY_TYPE = INCLUSIVE
        +recess_beam_width : float
        +recess_beam_height : float
        +sheeting_recess : float
        +generate_elements()
        +apply_to_plate(plate)
    }

    class FeatureBoundaryType {
        +NONE = "none"$
        +INCLUSIVE = "inclusive"$
        +EXCLUSIVE = "exclusive"$
    }

    %% Inheritance
    PopulatorAgent <|-- EdgePopulatorAgent
    PopulatorAgent <|-- StudPopulatorAgent
    PopulatorAgent <|-- PlatePopulatorAgent
    PopulatorAgent <|-- OpeningPopulatorAgent
    PopulatorAgent <|-- RecessPopulatorAgent

    %% Associations
    PopulatorAgent --> FeatureBoundaryType : uses
    PopulatorAgent "1" *-- "0..*" Beam2D : owns
```

---

### Agent Configs

Each `PopulatorAgent` subclass has a matching `PopulatorAgentConfig` dataclass.
`AGENT_TYPE` is set after both classes are defined to avoid forward references.
The `feature` field and `get_agent_from_feature` method allow the config to act
as a factory for its associated agent.

```mermaid
classDiagram

    class PopulatorAgentConfig {
        +AGENT_TYPE : type$
        +FEATURE_TYPE : type$
        +feature : object
        +beam_width_overrides : dict
        +joint_rule_overrides : list[CategoryRule]
        +get_agent_from_feature(feature) PopulatorAgent
    }

    class EdgePopulatorAgentConfig {
        +AGENT_TYPE = EdgePopulatorAgent
        +standard_beam_width_increment : float
        +edge_beam_min_width : float
    }

    class StudPopulatorAgentConfig {
        +AGENT_TYPE = StudPopulatorAgent
        +stud_spacing : float
    }

    class PlatePopulatorAgentConfig {
        +AGENT_TYPE = PlatePopulatorAgent
        +sheeting_inside : float
        +sheeting_outside : float
    }

    class OpeningPopulatorAgentConfig {
        +AGENT_TYPE = OpeningPopulatorAgent
        +FEATURE_TYPE = Opening
        +lintel_posts : bool
        +split_bottom_plate_beam : bool
    }

    class RecessPopulatorAgentConfig {
        +AGENT_TYPE = RecessPopulatorAgent
        +recess_beam_width : float
        +recess_beam_height : float
        +sheeting_recess : float
    }

    %% Inheritance
    PopulatorAgentConfig <|-- EdgePopulatorAgentConfig
    PopulatorAgentConfig <|-- StudPopulatorAgentConfig
    PopulatorAgentConfig <|-- PlatePopulatorAgentConfig
    PopulatorAgentConfig <|-- OpeningPopulatorAgentConfig
    PopulatorAgentConfig <|-- RecessPopulatorAgentConfig
```

---

### 2D Geometry

`Beam2D` extends compas_timber's `Beam` with a lazy 2D blank outline used for all intersection and topology detection operations. `AABB2D` is a lightweight 2D bounding box that avoids the `ZeroDivisionError` that `compas.geometry.Box` raises on flat z=0 geometry.

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
        -_invalidate_blank_cache()
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

    %% Inheritance
    Beam <|-- Beam2D

    %% Composition
    Beam2D ..> AABB2D : computes
```

---

### Connection Solver and Intersection Utilities

`ConnectionSolver2D` uses blank-outline endpoint containment to classify beam pairs into L, T, X, or face-to-face topologies. `BeamOutlineIntersectionData` stores the entry/exit dot positions where an agent outline crosses a beam blank, used by `trim_beam` to split beams at agent boundaries.

```mermaid
classDiagram

    class ConnectionSolver2D {
        +max_distance : float
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

    %% Associations
    ConnectionSolver2D ..> Beam2DSolverResult : returns
    ConnectionSolver2D ..> AABB2D : uses for overlap tests
    ConnectionSolver2D ..> BeamOutlineIntersectionData : uses via find_beam_outline_crossings
    Beam2DSolverResult --> JointTopology : classifies
```
