# 2D Connection Solving (`connections_2d`)

The `timber_design.connections_2d` module provides a self-contained pipeline for detecting beam adjacency, classifying joint topology, and extending beams to boundary outlines in a **2D panel context** (all geometry in the XY plane, `z = 0`).

It is designed to complement — and in many respects replace — the 3D-based `compas_timber.connections.ConnectionSolver` for wall/slab populator workflows, where beams have already been projected into a flat panel plane and topology must be derived from **blank footprints** rather than 3D centreline distances.

---

## Motivation and scope

`compas_timber.connections.ConnectionSolver` operates on 3D centreline geometry.
It finds close beam pairs by proximity in space and classifies their topology (L, T, X) from the relative orientation and distance of centreline endpoints.
That approach works well for free-form assemblies but breaks down in panel workflows for several reasons:

- Beams share a common plane, so "close in 3D" is always true for every beam pair.
- The relevant geometry is the **blank footprint** (the 2D rectangle the beam occupies in the panel), not the centreline.
- Adjacency should be decided by blank-outline **overlap or contact**, not point-to-point distance.
- Additional topologies (face-to-face, Y-junction, K-junction) arise naturally in panel structures and must be distinguished.

`ConnectionSolver2D` addresses all of these by working exclusively on blank outlines and by introducing dot-range tracking for multi-beam cluster analysis.

---

## Key classes

### `Beam2D`

Extends `compas_timber.elements.Beam` with lazy 2D blank geometry:

| Property | Description |
|---|---|
| `blank_outline` | Closed five-point `Polyline` `[bl, br, tr, tl, bl]` (CCW) |
| `blank_polygon` | Four-vertex `Polygon` of the same footprint |
| `edge_a` | Long blank edge on the `−yaxis` side (start → end) |
| `edge_b` | Long blank edge on the `+yaxis` side (start → end) |
| `start_segment` | Short cap at the beam origin |
| `end_segment` | Short cap at the beam terminal end |
| `aabb` | `AABB2D` bounding box (avoids the `ZeroDivisionError` that `Box.from_points` raises for coplanar z=0 points) |

`contains_point(point, tolerance=0.0)` performs a fast axis-aligned test in the beam's local frame, used extensively by the topology classifier.

Blank geometry is cached and automatically invalidated on `transform()`.

---

### `ConnectionSolver2D`

The main solver.  Instantiate with an optional `max_distance` gap (default `0.0`):

```python
solver = ConnectionSolver2D(max_distance=1.0)  # blanks touching within 1 mm count as overlapping
```

#### `find_intersecting_pairs(items)`

Yields `(item_a, item_b)` pairs whose `AABB2D` bounding boxes overlap within `max_distance`.
Accepts any object that exposes an `aabb` property — `Beam2D` instances or higher-level layer-agent objects with their own composite bounding box.

#### `find_topology(beam_a, beam_b) → Beam2DSolverResult | None`

Returns `None` if the blanks do not overlap.  Otherwise classifies the joint in this order:

1. **`TOPO_FACE_FACE`** — parallel beams whose centrelines are on opposite sides of a shared long edge.  Detected by checking whether any long-face edge pair is within `max_distance` and the centrelines straddle it.

2. **Corner containment** — each blank corner (two per end) is tested with `contains_point`.  A corner inside the other blank marks that beam end as involved in the joint.

3. **Outline–outline intersections** — all four edges of each blank outline are crossed against all four of the other.  End-cap crossings (indices 1 and 3 in `blank_outline.lines`) supply end-involvement evidence when corner containment alone is insufficient (e.g. beams that merely *touch* at their caps).

4. **Topology assignment**:
   - Both ends involved → `TOPO_L`
   - One end involved → `TOPO_T` (the end beam is always `beam_a` in the result)
   - No end involved → `TOPO_X`

!!! note "TOPO_T argument order"
    Unlike `compas_timber.connections.ConnectionSolver`, which may assign roles based on argument order, `ConnectionSolver2D.find_topology` always normalises TOPO_T results so that `result.beam_a` is the **end beam** (the one that butts in) regardless of which argument was passed first.

#### `find_joint_candidates(beams) → list[Beam2DSolverResult]`

Combines `find_intersecting_pairs` and `find_topology` into a single call, returning all pairwise results.

#### `find_joint_clusters(beams) → list[Cluster2D]`

Calls `find_joint_candidates` and then groups the results into `Cluster2D` objects using `Cluster2DFinder`.

#### `intersection_beam2d_polyline(beam, outline, limit_to_segments=True) → list[Beam2DPolylineIntersectionResult]`

Walks every edge of `outline` and records how it enters and exits the beam's blank.
Each `Beam2DPolylineIntersectionResult` carries:

- `start_dot` — centreline projection where the outline enters the blank (`None` if the outline started inside)
- `end_dot` — centreline projection where the outline exits the blank (`None` if the outline ended inside)
- `internal_dots` — projections of outline corners that fall inside the blank between the entry and exit

When `limit_to_segments=False`, the two long blank edges are treated as **infinite lines** rather than finite segments, allowing intersections to be found beyond the current beam extents.
This is used by `extend_beam_to_polylines` to project the beam toward a boundary outline it does not yet reach.

#### `extend_beam_to_polylines(beam, outlines, only_start=False, only_end=False)`

Extends `beam` in-place so its ends meet the nearest outlines.
Calls `intersection_beam2d_polyline` with `limit_to_segments=False` on each outline.
Intersections with a negative average dot (behind the beam start) set the new start;
intersections with an average dot beyond the beam length set the new end.
The beam is translated and its `length` updated accordingly.

---

### `Beam2DSolverResult`

Holds the output of a single pairwise topology test:

| Attribute | Description |
|---|---|
| `beam_a`, `beam_b` | The two beams (for TOPO_T, `beam_a` is always the end beam) |
| `topology` | One of the `JointTopology.TOPO_*` constants |
| `location` | Approximate centroid of the intersection zone |
| `dot_range_on_a` | `(min, max)` projection of the intersection onto `beam_a`'s centreline |
| `dot_range_on_b` | `(min, max)` projection of the intersection onto `beam_b`'s centreline |

The dot ranges are the key addition over the base `compas_timber` joint data structure.
They record **how much of each beam's length** is occupied by the intersection zone and are used by `Cluster2DFinder` to decide whether two pairwise results belong to the same multi-beam corner.

---

### `Cluster2DFinder` and `Cluster2D`

`Cluster2DFinder.find_clusters(results)` groups pairwise results into `Cluster2D` objects by connectivity: two results are adjacent if they share a beam and their dot ranges on that beam overlap.

`Cluster2D` subclasses `compas_timber.connections.Cluster` but overrides topology determination using **dot-range endpoint analysis** instead of pairwise topology inheritance:

| Cluster size | Topology rule |
|---|---|
| Single result | Inherits the result's own topology directly |
| Multiple results | `TOPO_Y` if every merged dot range on every shared beam touches at least one endpoint (within `endpoint_tolerance`); `TOPO_K` otherwise |

This lets the solver distinguish a **Y-junction** (three beams all meeting at a common end) from a **K-junction** (two beams framing into the body of a third without a free end at the junction).

---

## Comparison with `compas_timber.connections.ConnectionSolver`

| Aspect | `ConnectionSolver` (compas_timber) | `ConnectionSolver2D` |
|---|---|---|
| Input geometry | 3D centrelines | 2D blank outlines (XY plane) |
| Adjacency test | Centreline endpoint distance | AABB overlap + blank-outline containment |
| Topology detection | Centreline angle and proximity | Blank corner containment + outline crossing |
| FACE_FACE | Not distinguished | Detected via parallel edge alignment |
| Result type | Internal joint candidate | `Beam2DSolverResult` with dot ranges |
| Cluster topology | Derived from pairwise types | Dot-range endpoint analysis (Y vs K) |
| Extra utilities | — | Beam–polyline intersection, beam extension to outlines |
| Element type required | `Beam` | `Beam2D` (for topology methods) |

---

## Usage example

```python
from compas.geometry import Line, Point, Vector
from timber_design.connections_2d import Beam2D, ConnectionSolver2D

def make_beam(x0, y0, x1, y1, width=0.1):
    return Beam2D.from_centerline(
        Line(Point(x0, y0, 0), Point(x1, y1, 0)),
        width=width, height=0.05,
        z_vector=Vector(0, 0, 1),
    )

plate   = make_beam(0, 0, 4, 0, width=0.1)
stud_1  = make_beam(1, -0.5, 1, 0, width=0.1)   # T into plate
stud_2  = make_beam(3, -0.5, 3, 0, width=0.1)   # T into plate

solver = ConnectionSolver2D()
clusters = solver.find_joint_clusters([plate, stud_1, stud_2])

for cluster in clusters:
    print(cluster)
    # Cluster2D(topology=TOPO_T, n_joints=1, n_elements=2)
```
