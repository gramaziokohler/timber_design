# Class Diagrams

This section provides visual representations of the class hierarchies and relationships in the `timber_design` package.

[TOC]

## Populators Subsystem

### Orchestration

`PanelPopulator` is the only writer to its internal model.  It extracts the
panel's layer tree into that model, drives the agents through the pipeline, and
merges the result back under the original panel.  Agents never touch the model:
they return elements, and later find their own elements again through the
`attributes["agent"]` tag on each one (stripped again by `merge_with_model`).

```mermaid
classDiagram

    class PanelPopulator {
        +panel : Panel
        +agents : list[PopulatorAgent]
        +model : TimberModel
        +joint_rule_overrides : list[JointRule]
        +max_distance : float
        +debug_info : DebugInfomation
        +layer_tree : dict[str, Layer]
        +update_panel_from_model(model)
        +populate_elements()
        +join_elements()
        +process_joinery()
        +merge_with_model(model, clear_panel)
    }

    class stud_panel {
        <<function>>
        stud_panel(panel, standard_beam_width, stud_spacing, ...) PanelPopulator
    }

    class Panel {
        +layer_structure : LayerStructure
        +exterior_layer : Layer
        +core_layer : Layer
        +interior_layer : Layer
        +features : list[PanelFeature]
    }

    class Layer {
        +layer_path : tuple
        +sublayers : list[Layer]
        +thickness : float
        +outline_a : Polyline
        +outline_b : Polyline
        +edge_planes : dict
        +center_height : float
    }

    stud_panel ..> PanelPopulator : creates
    PanelPopulator --> Panel : populates
    PanelPopulator "1" *-- "1..*" PopulatorAgent : clones and drives
    PanelPopulator ..> ConnectionSolver2D : finds joint clusters
    PanelPopulator ..> JointRuleSolver : applies panel-level rules
    Panel "1" *-- "1..*" Layer : layer tree
    PopulatorAgent ..> Layer : bound by layer_path
```

`populate_elements()` runs: build populator model → repoint agents to its
layers → **generate** → **define outlines** → **extend** → **split** →
**cull**.  `join_elements()` resolves each cluster with, in order: the owning
agents' rules on the whole cluster, the populator's `joint_rule_overrides` on
the whole cluster, then both again pair by pair.

---

### Populator Agents

```mermaid
classDiagram
    direction TB

    class PopulatorAgent {
        <<abstract>>
        +BEAM_CATEGORY_NAMES : list[str]
        +INTERNAL_JOINT_RULES : list[JointRule]
        +EXTERNAL_JOINT_RULES : list[JointRule]
        +COMPOSITE_RULES : list[CompositeRule]
        +BOUNDARY_TYPE : AgentBoundaryType
        +beam_widths : dict[str, float]
        +internal_rules / external_rules / composite_rules
        +outline_by_layer : dict[Layer, Polyline]
        +element_layers* : list[Layer]
        +trimming_layers* : list[Layer]
        +elements : list
        +clone() PopulatorAgent
        +generate_elements()* dict[Layer, list]
        +beam_width(category) float
        +beam_from_category(centerline, category, layer) Beam2D
        +elements_for_layer(layer) list
        +define_outlines(layers)
        +outline_for_layer(layer) Polyline
        +extend_elements(boundary_outlines, layer)
        +split_element(element) list
        +cull_element(element) bool
        +trim_plate(plate)
        +get_cluster_joint(cluster, max_distance) Joint
    }

    class AgentBoundaryType {
        <<enumeration>>
        EXCLUSIVE
        INCLUSIVE
        NONE
    }

    class LayerAgent {
        <<abstract>>
        +layer_path : tuple
        +layer : Layer
        +generate_layer_elements()* tuple[list, Polyline]
    }

    class FeatureAgent {
        <<abstract>>
        +FEATURE_TYPE : type
        +feature : PanelFeature
        +element_layer_paths : list
        +trimming_layer_paths : list
        +generate_elements_for_layer(layer)* tuple[list, Polyline]
    }

    class EdgePopulatorAgent {
        INCLUSIVE
        edge_stud, top_plate_beam, bottom_plate_beam
    }
    class StudPopulatorAgent {
        NONE
        stud
    }
    class PlatePopulatorAgent {
        NONE
        plate
    }
    class PanelBoundaryPopulatorAgent {
        INCLUSIVE
        no elements
    }
    class OpeningPopulatorAgent {
        EXCLUSIVE
        header, king_stud, jack_stud
    }
    class WindowPopulatorAgent {
        + sill
    }
    class DoorPopulatorAgent {
        split_bottom_plate_beam
    }

    PopulatorAgent <|-- LayerAgent
    PopulatorAgent <|-- FeatureAgent
    PopulatorAgent --> AgentBoundaryType
    LayerAgent <|-- EdgePopulatorAgent
    LayerAgent <|-- StudPopulatorAgent
    LayerAgent <|-- PlatePopulatorAgent
    LayerAgent <|-- PanelBoundaryPopulatorAgent
    FeatureAgent <|-- OpeningPopulatorAgent
    OpeningPopulatorAgent <|-- WindowPopulatorAgent
    OpeningPopulatorAgent <|-- DoorPopulatorAgent
```

Notes:

- **Construction state only.**  An agent's `__data__` is its constructor
  arguments, so `clone()` (`type(agent)(**agent.__data__)`) produces a fresh
  agent that shares only the bound feature.  `PanelPopulator` clones every agent
  it receives.
- **Layers by path.**  Agents store layer paths and are rebound to the live
  layers of the populator model by `repoint_to_layer_tree` at the start of
  every `populate_elements()`.
- **Boundaries.**  `BOUNDARY_TYPE` decides what `cull_element` removes after
  splitting: segments outside an `INCLUSIVE` outline, inside an `EXCLUSIVE`
  one, or nothing.  An agent never trims its own elements.
- **Opening dispatch.**  Binding an `Opening` to a plain
  `OpeningPopulatorAgent` swaps its class to `WindowPopulatorAgent` or
  `DoorPopulatorAgent` according to `opening.opening_type`.
- **Rule overrides.**  `*_joint_overrides` replace a default rule with the same
  topology and categories, and are appended otherwise.
  `EdgePopulatorAgent.get_cluster_joint` computes joints between two of its own
  beams geometrically when either panel edge is sloped.

---

### 2D Geometry

`Beam2D` extends compas_timber's `Beam` with a lazily cached 2D blank outline
used for all intersection and topology detection.  `AABB2D` is a lightweight 2D
bounding box that avoids the `ZeroDivisionError` that `compas.geometry.Box`
raises on flat geometry.

```mermaid
classDiagram

    class Beam {
        +frame : Frame
        +length : float
        +width : float
        +height : float
        +centerline : Line
        +from_centerline(centerline, width, height)$
    }

    class Beam2D {
        +edges : tuple[Line, Line]
        +edge_a : Line
        +edge_b : Line
        +start_segment : Line
        +end_segment : Line
        +blank_outline : Polyline
        +blank_polygon : Polygon
        +aabb : AABB2D
        +contains_point(point, tolerance) bool
        +get_beam_segment(start_length, end_length) Beam2D
        +to_beam()
        +transform(transformation)
    }

    class AABB2D {
        +xmin : float
        +xmax : float
        +ymin : float
        +ymax : float
        +points : list[Point]
        +aabb : AABB2D
        +from_points(points)$
    }

    Beam <|-- Beam2D
    Beam2D ..> AABB2D : computes
```

`to_beam()` swaps the instance's class to `Beam` in place, so joints and model
references stay valid when `merge_with_model` hands the elements back.

---

### Connection Solver

`ConnectionSolver2D` finds beam pairs whose AABBs overlap, classifies each pair
with `find_topology` (blank-corner containment plus edge crossings), and groups
the resulting candidates into clusters with `Cluster2DFinder`.  It also provides
the static helpers the agents use for splitting and extending beams.

```mermaid
classDiagram

    class ConnectionSolver2D {
        +max_distance : float
        +find_intersecting_pairs(beams) list
        +find_topology(beam_a, beam_b, max_distance) Beam2DSolverResult
        +find_joint_candidates(beams) list[Beam2DSolverResult]
        +find_joint_clusters(beams) list[Cluster2D]
        +intersection_beam2d_polyline(beam, polyline)$ list
        +extend_beam_to_polylines(beam, polylines, only_start)$
    }

    class Beam2DSolverResult {
        +beam_a : Beam2D
        +beam_b : Beam2D
        +distance : float
        +topology : JointTopology
        +location : Point
        +elements : tuple
    }

    class Cluster2DFinder {
        +endpoint_tolerance : float
        +find_clusters(results) list[Cluster2D]
    }

    class Cluster2D {
        +topology : JointTopology
        +location : Point
    }

    class Cluster {
        +joints : list
        +elements : list
    }

    class Beam2DPolylineIntersectionResult {
        +start_dot : float
        +end_dot : float
        +internal_dots : list[float]
        +all_dots : list[float]
        +average_dot : float
    }

    ConnectionSolver2D ..> Beam2DSolverResult : returns
    ConnectionSolver2D ..> Cluster2DFinder : uses
    ConnectionSolver2D ..> Beam2DPolylineIntersectionResult : returns
    Cluster2DFinder ..> Cluster2D : creates
    Cluster <|-- Cluster2D
    Cluster2D "1" *-- "1..*" Beam2DSolverResult : groups
```

`find_topology` returns `None` for a beam swallowed entirely by another (a
degenerate stub left over from splitting) and reports face-to-face overlaps as
`TOPO_UNKNOWN` until `TOPO_FACE_FACE` is supported.
