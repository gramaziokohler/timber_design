# Class Diagrams

This section provides visual representations of the class hierarchies and relationships in the `timber_design` distribution.

[TOC]

## compas_arch

`compas_arch` extends COMPAS Timber; classes from `compas_timber` and `compas_model` that appear here
(`Element`, `PlateGeometry`, the plate joints) are documented in the
[COMPAS Timber class diagrams](https://gramaziokohler.github.io/compas_timber/latest/contribution/class_diagrams/).

### Elements

```mermaid
classDiagram
      class Element
      class PlateGeometry

      class Panel {
         +plate_geometry : PlateGeometry
         +length : float
         +width : float
         +height : float
         +type
         +attributes
         +debug_info
         +geometry
         +outlines
         +outline_a
         +outline_b
         +thickness : float
         +planes : tuple[Plane, Plane]
         +normal : Vector
         +edge_planes : dict[int, Plane]
         +features : list[PanelFeature]
         +interfaces
         +is_group_element : bool
         +set_extension_plane(edge_index, plane)
         +apply_edge_extensions()
         +remove_blank_extension(edge_index=None)
         +reset()
         +remove_features(features=None) : None
         +compute_aabb(inflate=0.0) : Box
         +compute_obb(inflate=0.0) : Box
         +compute_collision_mesh() : Mesh
         +transformation_to_local()
         +compute_elementgeometry(include_features=True) : Brep
         +from_outline_thickness(outline, thickness, vector=None, openings=None, orientation=None, **kwargs)
         +from_face_thickness(brep, thickness, vector=None, orientation=None, **kwargs)
         +from_brep(brep, orientation=None, **kwargs)
         +from_outlines(outline_a, outline_b, openings=None, recognize_doors=False, horizontal_openings=False, orientation=None, **kwargs)
      }

      class PanelType {
         <<enumeration>>
         WALL
         FLOOR
         ROOF
         GENERIC
      }

      class PanelFeature {
         <<abstract>>
         +panel_feature_type
         +is_joinery
         +geometry : Geometry
         +apply(geometry, panel) : Brep
      }

      class PanelFeatureType {
         <<enumeration>>
         CONNECTION_INTERFACE
         RECESS
         OPENING
         LINEAR
         VOLUMETRIC
         NONE
      }

      class Opening {
         +opening_type
         +outline_a
         +outline_b
         +shape
         +from_outline_panel(outline, panel, opening_type=None, project_horizontal=False, name=None)
      }

      class OpeningType {
         <<enumeration>>
         DOOR
         WINDOW
      }

      class MEPPenetration {
         +outline_interior
         +outline_core
         +outline_exterior
      }

      class LinearService {
         +polyline : Polyline
         +thickness : float
         +routing_mode : LinearServiceMode
      }

      class LinearServiceMode {
         <<enumeration>>
         CORE_DRILLING
         FRAME_NOTCHING
      }

      class Niche {
         +outline : Polyline
         +side : LayerRole
         +depth : float
      }

      class LayerRole {
         <<enumeration>>
         EXTERIOR
         CORE
         INTERIOR
      }

      class PanelConnectionInterface {
         +edge_index
         +interface_role
         +detail_set
         +polyline : Polyline
         +width : float
         +compute_elementgeometry(include_features=False) : Polyline
         +as_plane() : Plane
      }

      class InterfaceRole {
         <<enumeration>>
         MAIN
         CROSS
         NONE
      }

      %% Inheritance relationships
      Element <|-- Panel
      Element <|-- PanelFeature
      PanelFeature <|-- Opening
      PanelFeature <|-- MEPPenetration
      PanelFeature <|-- LinearService
      PanelFeature <|-- Niche
      PanelFeature <|-- PanelConnectionInterface

      %% Composition and usage relationships
      Panel *-- PlateGeometry : delegates to
      Panel o-- PanelFeature : contains
      Panel ..> PanelType : uses
      PanelFeature ..> PanelFeatureType : uses
      Opening ..> OpeningType : uses
      LinearService ..> LinearServiceMode : uses
      Niche ..> LayerRole : uses
      PanelConnectionInterface ..> InterfaceRole : uses
```

### Connections

```mermaid
classDiagram
      class PlateJoint
      class PlateLButtJoint
      class PlateTButtJoint
      class PlateMiterJoint

      class PanelJoint {
         <<abstract>>
         +interface_a : PlanarSurface
         +interface_b : PlanarSurface
         +panels : tuple[Optional[Panel], Optional[Panel]]
         +panel_a : Optional[Panel]
         +panel_b : Optional[Panel]
         +interfaces : Optional[list[PanelConnectionInterface]]
         +create_interfaces() : tuple[PanelConnectionInterface, PanelConnectionInterface]
      }

      class PanelLButtJoint {
         +SUPPORTED_TOPOLOGY = TOPO_EDGE_EDGE
         +main_panel : Panel
         +cross_panel : Panel
      }

      class PanelTButtJoint {
         +SUPPORTED_TOPOLOGY = TOPO_EDGE_FACE
         +main_panel : Panel
         +cross_panel : Panel
      }

      class PanelMiterJoint {
         +SUPPORTED_TOPOLOGY = TOPO_EDGE_EDGE
      }

      %% Inheritance relationships
      PlateJoint <|-- PanelJoint
      PanelJoint <|-- PanelLButtJoint
      PlateLButtJoint <|-- PanelLButtJoint
      PanelJoint <|-- PanelTButtJoint
      PlateTButtJoint <|-- PanelTButtJoint
      PanelJoint <|-- PanelMiterJoint
      PlateMiterJoint <|-- PanelMiterJoint
```

---

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

`populate_elements()` runs: bind each feature's detail set (its own
`detail_set`, else `default_detail_sets[type]`) → build populator model →
expand the sets into detail agents → sort all agents by `priority` (stable) →
repoint agents to its layers → **modify layers** (agents set extension planes,
e.g. connection details) → **generate** → **define outlines** → **extend** →
**split** → **cull** → **machine**.  `join_elements()` resolves each cluster with, in order: the owning
agents' rules on the whole cluster, the populator's `joint_rule_overrides` on
the whole cluster, then both again pair by pair.

---

### Populator Agents

One base class; one module per agent.  Panel-wide agents are given to the
populator, detail agents (`IS_DETAIL = True`) are created by detail sets.

```mermaid
classDiagram
    direction TB

    class PopulatorAgent {
        +IS_DETAIL : bool
        +PRIORITY : int
        +BEAM_CATEGORY_NAMES : list[str]
        +INTERNAL_JOINT_RULES : list[JointRule]
        +EXTERNAL_JOINT_RULES : list[JointRule]
        +COMPOSITE_RULES : list[CompositeRule]
        +BOUNDARY_TYPE : AgentBoundaryType
        +element_layer_paths : list[tuple]
        +trimming_layer_paths : list[tuple]
        +feature : PanelFeature
        +priority : int
        +beam_widths : dict[str, float]
        +internal_rules / external_rules / composite_rules
        +outline_by_layer : dict[Layer, Polyline]
        +element_layers : list[Layer]
        +trimming_layers : list[Layer]
        +layer : Layer
        +elements : list
        +clone() PopulatorAgent
        +modify_layers(layer_tree) list
        +generate_elements() dict[Layer, list]
        +generate_elements_for_layer(layer) tuple[list, Polyline]
        +beam_width(category) float
        +beam_from_category(centerline, category, layer) Beam2D
        +elements_for_layer(layer) list
        +define_outlines(layers)
        +outline_for_layer(layer) Polyline
        +extend_elements(boundary_outlines, layer)
        +split_element(element) list
        +cull_element(element) bool
        +trim_plate(plate)
        +machine_element(element) list
        +get_cluster_joint(cluster, max_distance) Joint
    }

    class AgentBoundaryType {
        <<enumeration>>
        EXCLUSIVE
        INCLUSIVE
        NONE
    }

    class EdgeAgent {
        INCLUSIVE, priority -10
        edge_stud, top_plate_beam, bottom_plate_beam
    }
    class StudAgent {
        NONE
        stud
    }
    class PlateAgent {
        NONE
        plate
    }
    class LayerBoundaryAgent {
        INCLUSIVE, priority -10
        no elements
    }
    class VoidFramingDetailAgent {
        EXCLUSIVE
        frame_outline_a, frame_outline_b, boundary
        header, king_stud, jack_stud, sill
    }
    class LayerCutDetailAgent {
        EXCLUSIVE
        layer, outline_a, outline_b, depth
        cut_beams, bottom_offset
        splits beams, cuts plates
    }
    class ServiceDrillingDetailAgent {
        path, diameter
        machine_element() drills
    }
    class ServiceNotchDetailAgent {
        path, diameter, side
        machine_element() notches
    }
    class LayerExtensionDetailAgent {
        priority -100
        edge_index, extensions, messages
        modify_layers() moves layer edges
    }
    class BackingStudDetailAgent {
        positions, direction, width
        backing_stud
    }

    PopulatorAgent --> AgentBoundaryType
    PopulatorAgent <|-- EdgeAgent
    PopulatorAgent <|-- StudAgent
    PopulatorAgent <|-- PlateAgent
    PopulatorAgent <|-- LayerBoundaryAgent
    PopulatorAgent <|-- VoidFramingDetailAgent
    PopulatorAgent <|-- LayerCutDetailAgent
    PopulatorAgent <|-- ServiceDrillingDetailAgent
    PopulatorAgent <|-- ServiceNotchDetailAgent
    PopulatorAgent <|-- LayerExtensionDetailAgent
    PopulatorAgent <|-- BackingStudDetailAgent
```

Notes:

- **Construction state only.**  An agent's `__data__` is its constructor
  arguments, so `clone()` (`type(agent)(**agent.__data__)`) produces a fresh
  agent that shares only the bound feature.  `PanelPopulator` clones every agent
  it receives.
- **Layers by path.**  Agents store layer paths (`layer=` sets both lists) and
  are rebound to the live layers of the populator model by
  `repoint_to_layer_tree` at the start of every `populate_elements()`.
- **Boundaries.**  `BOUNDARY_TYPE` decides what `cull_element` removes after
  splitting: segments outside an `INCLUSIVE` outline, inside an `EXCLUSIVE`
  one, or nothing.  An agent never trims its own elements.
- **Detail agents take explicit inputs.**  They never derive anything from the
  feature (it is only a tag); a detail set derives their frames, boundaries,
  cuts, planes and positions.  `PanelPopulator(agents=...)` skips detail
  agents and reports them.
- **Priority.**  Agents run in order of `priority` (class `PRIORITY` unless
  given), stable, so equal priorities keep their order; detail agents come
  after the panel-wide agents they tie with.  Layer extensions (-100) run
  before anything is generated; the populator reports two agents setting the
  same layer edge (the later one wins).
- **Rule overrides.**  `*_joint_overrides` replace a default rule with the same
  topology and categories, and are appended otherwise.
  `EdgeAgent.get_cluster_joint` computes joints between two of its own beams
  geometrically when either panel edge is sloped.

---

### Detail Sets

A feature states design intent; exactly one detail set decides how it is
built (the feature's `detail_set`, else the populator's default for its type)
and expands into detail agents.  One module per set in
`timber_design_populator/detail_sets/`; the built-in sets are examples and
defaults, not the only options.

```mermaid
classDiagram
    direction TB

    class DetailAgentSet {
        <<abstract>>
        +FEATURE_TYPES : tuple[type]
        +expand(feature, panel, layer_tree, standard_beam_width)* tuple[list, list]
        +clone() DetailAgentSet
        +root_layer(layer_tree, role)$
        +layer_and_sublayers(layer_tree, layer)$
    }
    class FramedOpeningDetailSet {
        lintel_posts, split_bottom_plate_beam
        widths, cut_offsets
    }
    class FramedPenetrationDetailSet
    class FramedNicheDetailSet
    class LinearServiceDetailSet {
        mode : drilling | notching
    }
    class PanelJointDetailSet {
        edge_index, extensions
        backing_positions, backing_direction
        backing_stud_width, messages
    }
    class LGenericPanelJointDetailSet
    class TGenericPanelJointDetailSet

    DetailAgentSet <|-- FramedOpeningDetailSet
    DetailAgentSet <|-- FramedPenetrationDetailSet
    DetailAgentSet <|-- FramedNicheDetailSet
    DetailAgentSet <|-- LinearServiceDetailSet
    DetailAgentSet <|-- PanelJointDetailSet
    PanelJointDetailSet <|-- LGenericPanelJointDetailSet
    PanelJointDetailSet <|-- TGenericPanelJointDetailSet
    FramedOpeningDetailSet ..> VoidFramingDetailAgent : expands into
    FramedOpeningDetailSet ..> LayerCutDetailAgent : one per role layer
    LinearServiceDetailSet ..> ServiceDrillingDetailAgent : drilling
    LinearServiceDetailSet ..> ServiceNotchDetailAgent : notching
    PanelJointDetailSet ..> LayerExtensionDetailAgent : expands into
    PanelJointDetailSet ..> BackingStudDetailAgent : expands into
```

### Panel Joints with Connection Details

A detail joint does all cross-panel calculation in `add_features()`, with both
panels in view, and sets each panel's half (in that panel's local frame) as the
`detail_set` of the panel's `PanelConnectionInterface`.  One module per joint
in `timber_design_populator/panel_joints/`.

```mermaid
classDiagram
    direction TB

    class PanelLButtJoint
    class PanelTButtJoint
    class LGenericPanelJoint {
        +stagger_layers : bool
        +backing_studs : bool
        +backing_stud_width : float
        +backing_stud_inset : float
        +add_features()
    }
    class TGenericPanelJoint {
        +backing_studs : bool
        +backing_stud_width : float
        +backing_stud_inset : float
        +add_features()
    }

    PanelLButtJoint <|-- LGenericPanelJoint
    PanelTButtJoint <|-- TGenericPanelJoint
    LGenericPanelJoint ..> LGenericPanelJointDetailSet : creates per panel
    TGenericPanelJoint ..> TGenericPanelJointDetailSet : creates per panel
    LGenericPanelJointDetailSet --o PanelConnectionInterface : detail_set
```

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
