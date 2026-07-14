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
        +orientation : Vector
        +root_layer_def : LayerConfig
        +default_feature_configs : dict
        +instance_feature_configs : list
        +standard_beam_width : float
        +get_populator_panel() Panel
        +resolve_beam_widths()
        +create_populator_model() TimberModel
        +create_feature_agents() list[FeatureAgent]
        +create_populator() PanelPopulator
        -_iter_agent_configs()
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
        +name : str
        +layer_index : int
        +parent_layer : Layer
        +sublayer_list : list[Layer]
        +agents : list[PopulatorAgent]
        +thickness : float
        +center_height : float
        +outline_a : Polyline
        +outline_b : Polyline
        +elements : list
        +from_panel_and_range(panel, range_a, range_b, ...)$
    }

    class LayerConfig {
        +thickness : float
        +name : str
        +agent_configs : list[LayerAgentConfig]
        +sublayers : list[LayerConfig]
        +position : float
        +resulting_layer : Layer
        +model_from_panel(panel) TimberModel
    }

    class ConnectionSolver2D {
        +find_intersecting_pairs(beams) list
        +find_intersecting_agent_pairs(agents) list
        +find_topology(beam_a, beam_b) Beam2DSolverResult
        +find_beam_contacts(beam, others) list[BeamContact]
        +find_all_contacts(beams) list[BeamContact]
        +cluster_contacts(contacts) list[Beam2DCluster]
    }

    PanelPopulatorConfig --> PanelPopulator : creates
    PanelPopulatorConfig "1" *-- "1..*" LayerConfig : holds (root_layer_def + sublayers)
    LayerConfig --> Layer : creates via model_from_panel
    PanelPopulator "1" *-- "1..*" Layer : owns
    PanelPopulator --> ConnectionSolver2D : uses
    Layer "1" *-- "1..*" PopulatorAgent : has registered
    LayerConfig --> LayerAgentConfig : carries
```

---

### Populator Config Factories

`PanelPopulatorConfig` is the single concrete config class.  The
`stud_panel()` **factory function** (not a subclass) builds the right
`LayerConfig` stack and agent configs for a standard stud-framed wall panel
and returns a `PanelPopulatorConfig`.  Custom configs are made by
instantiating `PanelPopulatorConfig` directly with a `layer_defs` list.

```mermaid
classDiagram

    class PanelPopulatorConfig {
        +panel : Panel
        +orientation : Vector
        +root_layer_def : LayerConfig
        +default_feature_configs : dict[type, FeatureAgentConfig]
        +instance_feature_configs : list
        +standard_beam_width : float
        +get_populator_panel() Panel
        +resolve_beam_widths()
        +create_populator_model() TimberModel
        +create_feature_agents() list[FeatureAgent]
        +create_populator() PanelPopulator
    }

    class stud_panel {
        <<factory function>>
        panel
        standard_beam_width
        stud_spacing
        stud_width
        standard_beam_width_increment
        edge_stud_width
        top_plate_beam_width
        bottom_plate_beam_width
        orientation
        sheeting_outside
        sheeting_inside
        lintel_posts
        split_bottom_plate_beam
        internal_joint_overrides
        external_joint_overrides
        default_feature_configs
        instance_feature_configs
    }

    stud_panel ..> PanelPopulatorConfig : returns
    PanelPopulatorConfig ..> LayerConfig : holds (root + sublayers)
    PanelPopulatorConfig ..> LayerAgentConfig : reads via default_feature_configs
```

---

### Layer and LayerConfig

`LayerConfig` is a pure data blueprint with no geometry.  `Layer` is the
resolved runtime object — it *is* a `Panel` (sliced from the source panel) and
also holds the list of agents registered on it.  The definition tree supports
nested `sublayers` for composite cross-sections; `thickness=None` on a leaf
causes fill-remaining resolution against the parent.

There is **no** `is_framing_layer` flag.  Feature agents (openings, etc.) point
at the specific layers they frame on via `framing_layer_defs` on their config,
and at the layers they trim through via `trimming_layer_defs`.

```mermaid
classDiagram

    class LayerConfig {
        +thickness : float | None
        +name : str
        +agent_configs : list[LayerAgentConfig]
        +sublayers : list[LayerConfig]
        +position : float
        +resulting_layer : Layer
        +model_from_panel(panel) TimberModel
    }

    class Layer {
        +name : str
        +layer_index : int
        +parent_layer : Layer
        +sublayer_list : list[Layer]
        +agents : list[PopulatorAgent]
        +thickness : float
        +center_height : float
        +outline_a : Polyline
        +outline_b : Polyline
        +elements : list
        +iter_subtree()
        +from_panel_and_range(panel, range_a, range_b, ...)$
    }

    LayerConfig "0..*" --> LayerConfig : sublayers
    LayerConfig --> LayerAgentConfig : carries agent_configs
    Layer "1" *-- "0..*" PopulatorAgent : registered agents
    LayerConfig --> Layer : produces via model_from_panel
```

---

### Populator Agents

`PopulatorAgent` is the abstract base.  `LayerAgent` and `FeatureAgent` are the
two specializations — `LayerAgent` is bound to exactly one `Layer`,
`FeatureAgent` spans multiple layers (e.g. an opening that frames on one or
more framing layers and cuts through sheathing layers).

The base owns the common element / outline / trim machinery so the subclasses
declare only what differs — `LayerAgent` adds nothing more than its single
`layer` reference and a `beam_from_category` convenience; `FeatureAgent` swaps
the flat element list for a per-layer bucket and a per-layer outline.

```mermaid
classDiagram

    class PopulatorAgent {
        <<abstract>>
        +BEAM_CATEGORY_NAMES : list[str]$
        +INTERNAL_JOINT_RULES : list[CategoryRule]$
        +EXTERNAL_JOINT_RULES : list[CategoryRule]$
        +BOUNDARY_TYPE : AgentBoundaryType$
        +beam_widths : dict[str, float]
        +internal_rules : list[CategoryRule]
        +external_rules : list[CategoryRule]
        +external_overrides : list[CategoryRule]
        +elements : list[Beam2D | Plate]
        +outline : Polyline
        +joint_defs : list[DirectRule]
        +aabb : AABB2D
        +outline_for_layer(layer) Polyline
        +elements_for_layer(layer) list
        +set_elements_for_layer(layer, elements)
        +beam_from_category(centerline, category, layer) Beam2D
        +trim_beam(beam, layer) list[Beam2D]
        +trim_plate(plate) list[Plate]
        +trim_agent_elements(other_agent, layer)
        +trim_elements()
        +cull_beam_segment(beam) bool
        +cull_element_at_point(point, layer) bool
        +create_joint_candidates() list
        +create_joint_defs()
        +generate_elements()*
        +extend_elements()
        +is_on_layer(layer) bool
        -_trim_layers() list[Layer]
        -_agent_layers() list[Layer]
    }

    class LayerAgent {
        <<abstract>>
        +layer : Layer
        +layer_index : int
        +layer_center_height : float
        +panel : Panel
        +beam_from_category(centerline, category, layer)
    }

    class FeatureAgent {
        <<abstract>>
        +FEATURE_TYPE : type$
        +feature : PanelFeature
        +element_layers : list[Layer]
        +trimming_layers : list[Layer]
        +registered_layers : list[Layer]
        -_elements_by_layer : dict[int, list]
        -_outline_by_layer : dict[int, Polyline]
        +outline_for_layer(layer) Polyline
        +elements_for_layer(layer) list
        +set_elements_for_layer(layer, elements)
        +register_on_layer(layer)
        +generate_elements()
        +generate_elements_for_layer(layer)*
        -_trim_layers() list[Layer]
    }

    class EdgePopulatorAgent {
        +BOUNDARY_TYPE = INCLUSIVE
        +BEAM_CATEGORY_NAMES = ["edge_stud", "top_plate_beam", "bottom_plate_beam"]
        +standard_beam_width_increment : float
        +generate_elements()
        +create_joint_defs()
    }

    class StudPopulatorAgent {
        +BEAM_CATEGORY_NAMES = ["stud"]
        +stud_spacing : float
        +generate_elements()
    }

    class PlatePopulatorAgent {
        +BEAM_CATEGORY_NAMES : ["<layer-name>_plate"]
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
        +extend_elements()
        +trim_plate(plate)
    }

    class AgentBoundaryType {
        +NONE = "none"$
        +INCLUSIVE = "inclusive"$
        +EXCLUSIVE = "exclusive"$
    }

    PopulatorAgent <|-- LayerAgent
    PopulatorAgent <|-- FeatureAgent
    LayerAgent <|-- EdgePopulatorAgent
    LayerAgent <|-- StudPopulatorAgent
    LayerAgent <|-- PlatePopulatorAgent
    FeatureAgent <|-- OpeningPopulatorAgent

    PopulatorAgent --> AgentBoundaryType : uses
    PopulatorAgent "1" *-- "0..*" Beam2D : owns
    FeatureAgent --> Layer : registers on
```

---

### Agent Configs

Each agent subclass has a matching config dataclass.  All configs descend from
`PopulatorAgentConfig`, which carries the per-agent joint-rule overrides (split
into `internal_joint_overrides` and `external_joint_overrides`) and the
`beam_widths` dict.  Subclasses add **explicit per-category width fields**
(`edge_stud_width`, `stud_width`, `header_width`, …) rather than a generic
overrides dict; `_agent_kwargs()` is the single seam that turns config fields
into the agent's explicit constructor keyword arguments.

```mermaid
classDiagram

    class PopulatorAgentConfig {
        <<abstract>>
        +AGENT_TYPE : type$
        +internal_joint_overrides : list[CategoryRule]
        +external_joint_overrides : list[CategoryRule]
        +beam_widths : dict[str, float]
        +fill_beam_widths(standard_beam_width)
        -_agent_kwargs() dict
    }

    class LayerAgentConfig {
        <<abstract>>
        +get_agent_from_layer(layer, standard_beam_width) LayerAgent
    }

    class FeatureAgentConfig {
        <<abstract>>
        +feature : PanelFeature
        +framing_layer_defs : list[LayerConfig]
        +trimming_layer_defs : list[LayerConfig]
        +get_agent_from_feature(feature, element_layers, trimming_layers, standard_beam_width) FeatureAgent
    }

    class EdgePopulatorAgentConfig {
        +AGENT_TYPE = EdgePopulatorAgent$
        +standard_beam_width_increment : float
        +edge_stud_width : float
        +top_plate_beam_width : float
        +bottom_plate_beam_width : float
    }

    class StudPopulatorAgentConfig {
        +AGENT_TYPE = StudPopulatorAgent$
        +stud_spacing : float
        +stud_width : float
    }

    class PlatePopulatorAgentConfig {
        +AGENT_TYPE = PlatePopulatorAgent$
    }

    class OpeningPopulatorAgentConfig {
        +AGENT_TYPE = OpeningPopulatorAgent$
        +FEATURE_TYPE = Opening$
        +lintel_posts : bool
        +split_bottom_plate_beam : bool
        +header_width : float
        +sill_width : float
        +king_stud_width : float
        +jack_stud_width : float
    }

    PopulatorAgentConfig <|-- LayerAgentConfig
    PopulatorAgentConfig <|-- FeatureAgentConfig
    LayerAgentConfig <|-- EdgePopulatorAgentConfig
    LayerAgentConfig <|-- StudPopulatorAgentConfig
    LayerAgentConfig <|-- PlatePopulatorAgentConfig
    FeatureAgentConfig <|-- OpeningPopulatorAgentConfig
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

`ConnectionSolver2D` offers two complementary detection paths:

- the legacy pairwise `find_topology(beam_a, beam_b)` using blank-corner
  containment + edge crossings; and
- an occlusion-aware perimeter walk — `find_beam_contacts(beam, others)` —
  which records the *role* (end vs middle) of each beam at every real contact
  and discards beams hidden behind a nearer one.  `cluster_contacts` then
  groups those contacts on shared **ports** (a beam's end key, or overlapping
  intervals along its long face) into `Beam2DCluster` objects whose topology
  is derived from per-beam roles (Y when every beam meets at an end, K when
  at least one is met through its middle).

`BeamOutlineIntersectionData` stores the entry/exit dot positions where an
outline crosses a beam blank, used by `trim_beam` to split beams at agent
boundaries.

```mermaid
classDiagram

    class ConnectionSolver2D {
        +max_distance : float
        +find_intersecting_pairs(beams) list
        +find_intersecting_agent_pairs(agents) list
        +find_topology(beam_a, beam_b) Beam2DSolverResult
        +find_beam_contacts(beam, others) list[BeamContact]
        +find_all_contacts(beams) list[BeamContact]
        +cluster_contacts(contacts) list[Beam2DCluster]
    }

    class Beam2DSolverResult {
        +beam_a : Beam2D
        +beam_b : Beam2D
        +distance : float
        +topology : JointTopology
        +location : Point
    }

    class BeamContact {
        +beam_a : Beam2D
        +beam_b : Beam2D
        +role_a : "end" | "middle"
        +role_b : "end" | "middle"
        +end_a : "start" | "end" | None
        +end_b : "start" | "end" | None
        +location : Point
        +topology : JointTopology
        +role_for(beam) str
    }

    class Beam2DCluster {
        +contacts : list[BeamContact]
        +beams : list[Beam2D]
        +location : Point
        +topology : JointTopology
    }

    class BeamOutlineIntersectionData {
        +start_dot : float
        +end_dot : float
        +internal_dots : list[float]
        +all_dots : list[float]
        +average_dot : float
    }

    class JointTopology {
        +TOPO_UNKNOWN = 0$
        +TOPO_I = 1$
        +TOPO_L = 2$
        +TOPO_T = 3$
        +TOPO_X = 4$
        +TOPO_Y = 5$
        +TOPO_K = 6$
        +TOPO_EDGE_EDGE = 7$
        +TOPO_EDGE_FACE = 8$
        +TOPO_FACE_FACE = 9$
    }

    ConnectionSolver2D ..> Beam2DSolverResult : returns
    ConnectionSolver2D ..> BeamContact : returns
    ConnectionSolver2D ..> Beam2DCluster : returns
    ConnectionSolver2D ..> AABB2D : uses for overlap tests
    ConnectionSolver2D ..> BeamOutlineIntersectionData : uses via find_beam_outline_crossings
    Beam2DCluster "1" *-- "1..*" BeamContact : groups
    Beam2DSolverResult --> JointTopology : classifies
    BeamContact --> JointTopology : classifies
    Beam2DCluster --> JointTopology : classifies
```
