# Populating Panels

This guide walks through framing a :class:`~compas_timber.elements.Panel` with
beams and plates using `timber_design.populators`.  A runnable version of every
scenario below lives in `examples/panel_population.py`.

All lengths are in the model's native units (mm in the examples).

## Concepts

- **Layers belong to the panel.**  A panel's cross-section is a
  :class:`~compas_timber.elements.LayerStructure` (from `compas_timber`): a tree
  of :class:`~compas_timber.elements.LayerDefinition`s, each with a name, a
  thickness and optional sublayers.  The populator never defines layers itself;
  it frames the ones the panel already has.
- **Agents generate the framing.**  Each agent is responsible for one group of
  elements:
    - **Layer agents** act on a single layer: `EdgePopulatorAgent` (plates and
      edge studs along the outline), `StudPopulatorAgent` (intermediate studs),
      `PlatePopulatorAgent` (a sheathing plate), `PanelBoundaryPopulatorAgent`
      (no elements; it only clips other agents to the panel outline).
    - **Feature agents** react to a panel feature: `OpeningPopulatorAgent`
      frames an :class:`~compas_timber.panel_features.Opening` and becomes a
      `WindowPopulatorAgent` or `DoorPopulatorAgent` depending on the opening's
      type.
- **`PanelPopulator` runs the pipeline** and is the only thing that writes to
  the model.  `stud_panel()` is a factory that builds one with the usual agents.

## Basic stud wall

```python
from compas.geometry import Point, Polyline
from compas_timber.elements import Panel
from compas_timber.model import TimberModel
from timber_design.populators import stud_panel

outline = Polyline([Point(0, 0, 0), Point(4000, 0, 0), Point(4000, 2700, 0), Point(0, 2700, 0), Point(0, 0, 0)])
panel = Panel.from_outline_thickness(outline, 160)

model = TimberModel()
model.add_element(panel)
panel.merge_layer_structure(model)  # the populator reads the layers from the model

populator = stud_panel(panel, standard_beam_width=60, stud_spacing=625)
populator.populate_elements()
populator.join_elements()
populator.process_joinery()
populator.merge_with_model(model)
```

A panel without a `layer_structure` has a single full-thickness layer named
`"core"`, so the result is framing only, grouped under that layer:

- **top_plate_beam** / **bottom_plate_beam**: along the top and bottom edges
- **edge_stud** × 2: along the vertical edges
- **stud** × N: at `stud_spacing` on centre (6 for this panel)

!!! warning "Add the layers to the model"
    `model.add_element(panel)` does not add the panel's layers.  Call
    `panel.merge_layer_structure(model)` before populating, otherwise the
    populator finds no layers to frame.

## Sheathing: defining the cross-section

Give the panel a layer structure whose layers are named `"exterior"`, `"core"`
and `"interior"`.  `stud_panel()` puts a plate on `exterior_layer` and
`interior_layer` (when present) and the framing on `core_layer`.  One sibling
may leave `thickness` unset to absorb the remaining thickness.

```python
from compas_timber.elements import LayerDefinition, LayerStructure

panel = Panel.from_outline_thickness(outline, 200)
panel.layer_structure = LayerStructure(
    layer_defs=[
        LayerDefinition(name="exterior", thickness=22),
        LayerDefinition(name="core"),               # absorbs the remaining 163 mm
        LayerDefinition(name="interior", thickness=15),
    ]
)
```

In Grasshopper, build the structure with `CT: Panel Layer Definition`, refine
it with `CT: Subdivide Layer`, and connect it to `CT: Panel`'s `layer_structure`
input.

## Openings

Openings are :class:`~compas_timber.panel_features.Opening` features on the
panel.  `stud_panel()` registers a default `OpeningPopulatorAgent` that frames
on the core layer and cuts its outline through every layer, so sheathing plates
get the hole too.

```python
from compas_timber.panel_features import Opening, OpeningType

window = Polyline([Point(800, 900, 0), Point(2000, 900, 0), Point(2000, 2200, 0), Point(800, 2200, 0), Point(800, 900, 0)])
panel.add_feature(Opening.from_outline_panel(window, panel, opening_type=OpeningType.WINDOW))
```

A window gets a **header**, a **sill** and two **king_stud**s; a door gets no
sill.  Studs that cross the opening are cut at its boundary and the inner
pieces removed, and studs that coincide with a king or jack stud are dropped.

To customise the framing, pass your own prototype under
`default_feature_configs`.  `stud_panel()` copies it and sets its layers for
you:

```python
from timber_design.populators import OpeningPopulatorAgent

populator = stud_panel(
    panel,
    standard_beam_width=60,
    stud_spacing=625,
    default_feature_configs={
        Opening: OpeningPopulatorAgent(
            lintel_posts=True,             # add jack studs under the header
            header_width=120,
            split_bottom_plate_beam=True,  # doors only: cut the bottom plate at the opening
        ),
    },
)
```

To give one opening different settings, bind an agent to it and pass it in
`instance_feature_configs`.  An opening that already has an agent is skipped
by the defaults:

```python
special = OpeningPopulatorAgent(feature=my_opening, header_width=200)
populator = stud_panel(panel, standard_beam_width=60, instance_feature_configs=[special])
```

!!! note
    Openings are framed by their bounding rectangle in the panel plane, and
    only `OpeningType.WINDOW` / `OpeningType.DOOR` get type-specific framing.

## Beam widths

Every beam category has its own width parameter; anything left unset falls
back to `standard_beam_width`.  If neither is given, population raises a
`ValueError` naming the agent and category.

| Category                                    | Set on                                         |
|---------------------------------------------|------------------------------------------------|
| `stud`                                      | `stud_panel(stud_width=…)`                     |
| `edge_stud`, `top_plate_beam`, `bottom_plate_beam` | `stud_panel(edge_stud_width=…, …)`      |
| `header`, `sill`, `king_stud`, `jack_stud`  | `OpeningPopulatorAgent(header_width=…, …)`     |

`standard_beam_width_increment` rounds each edge-beam width *up* to a multiple
of the increment, e.g. to snap to stock lumber sizes.

## Joint rules

Joint candidates are found between beams on the same leaf layer (and its parent
layers), grouped into clusters, and resolved in this order:

1. the rules of the agents that own elements in the cluster, for the whole cluster;
2. the populator's `joint_rule_overrides`, for the whole cluster;
3. the agents' rules again, one candidate pair at a time;
4. the populator's `joint_rule_overrides`, one pair at a time.

Each agent carries three rule sets with sensible defaults:

- **internal**: pairs where both elements belong to the agent;
- **external**: pairs with an element from another agent;
- **composite**: clusters of three or more elements (e.g. a king stud meeting
  the corner of two edge beams), resolved as one `CompositeJoint`.

Override them per agent with `internal_joint_overrides`,
`external_joint_overrides` and `composite_joint_overrides`.  An override that
matches a default (same joint topology and same categories) replaces it; any
other override is added.

```python
from compas_timber.connections import TButtJoint
from timber_design.populators import StudPopulatorAgent
from timber_design.workflow import CategoryRule

studs = StudPopulatorAgent(
    panel.core_layer,
    stud_spacing=600,
    # replaces the default (stud, top_plate_beam) T-butt
    external_joint_overrides=[CategoryRule(TButtJoint, "stud", "top_plate_beam", mill_depth=0.0)],
)
```

`joint_rule_overrides` on `stud_panel()` / `PanelPopulator` are a panel-wide
**fallback**: they never change an agent's rules and are only tried once those
have failed.  `max_distance` (default `0.1`) bounds the gap considered for all
joint finding and creation.

Joining errors are collected on `populator.debug_info` instead of being raised.

## Custom agent stacks

For anything `stud_panel()` doesn't cover, build the agents yourself and pass
them to `PanelPopulator`.  Agents refer to layers by path, so they can be given
the live `Layer` or its `layer_path`.  Sublayers are layers like any other:

```python
from timber_design.populators import EdgePopulatorAgent, PanelPopulator, PlatePopulatorAgent

panel.layer_structure = LayerStructure(
    layer_defs=[
        LayerDefinition(
            name="exterior",
            thickness=40,
            sublayer_defs=[LayerDefinition(name="board", thickness=18), LayerDefinition(name="battens")],
        ),
        LayerDefinition(name="core"),
        LayerDefinition(name="interior", thickness=15),
    ]
)
model.add_element(panel)
panel.merge_layer_structure(model)

board, battens = panel.exterior_layer.sublayers
populator = PanelPopulator(
    panel,
    agents=[
        PlatePopulatorAgent(board),
        PlatePopulatorAgent(panel.interior_layer),
        EdgePopulatorAgent(panel.core_layer),
        StudPopulatorAgent(panel.core_layer, stud_spacing=600),
    ],
    standard_beam_width=60,
    default_feature_agents={
        Opening: OpeningPopulatorAgent(
            element_layers=[panel.core_layer],
            # trimming a layer also trims its sublayers
            trimming_layers=[panel.exterior_layer, panel.core_layer, panel.interior_layer],
        ),
    },
)
```

Agent order sets joint precedence: when several agents own elements in a
cluster, the earlier agent's rules are tried first.

`PanelPopulator` clones the agents you give it, so the same agent objects can
be reused for many panels.  Inspect the populated agents through
`populator.agents`.

## What happens inside

`populate_elements()` extracts the panel's layer tree into the populator's own
model, where all geometry is in the panel's local frame (X along the panel,
Y up, Z through the thickness).  It then runs five stages:

1. **generate**: every agent creates its elements and records its boundary
   outline on each layer it acts on;
2. **define outlines**: agents record outlines on the layers they only trim;
3. **extend**: agents extend their elements to their neighbours' boundaries
   (e.g. king studs to the plates);
4. **split**: each agent's boundary splits other agents' beams and cuts plates;
5. **cull**: beam segments that fall outside an *inclusive* boundary (the edge
   agent) or inside an *exclusive* one (an opening) are removed.

An agent never trims its own elements.  `join_elements()` and
`process_joinery()` then create the joints and their fabrication features, and
`merge_with_model(model)` moves the layer subtree back under the original
panel, converting the internal `Beam2D`s to plain `Beam`s.  By default it first
removes any framing the panel already had, so re-populating is safe.

## Grasshopper

The same workflow as components:

1. `CT: Panel Layer Definition` (and optionally `CT: Subdivide Layer`) →
   `CT: Panel`.
2. `CT: Stud Panel` for the standard case, or `CT: Layer Agent` /
   `CT: Feature Agent` → `CT: Panel Populator` for a custom stack.  Use
   `CT: Decompose LayerStructure` to get layer paths for the agents.
3. `CT: Model` → `CT: Populate Model` with the populators.  `CT: Model` adds
   each panel's layers to the model itself, so layer-aware panel joints (e.g.
   `PanelLLayerButtJoint`) work with or without a populator, and
   `CT: Populate Model` frames the layers as the panel joints extended them.
4. `CT: Filter Display` to show the result by layer.
