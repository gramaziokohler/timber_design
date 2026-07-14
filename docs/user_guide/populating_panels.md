# Populating Panels

This guide walks through the workflow for automatically framing a
:class:`~compas_timber.elements.Panel` with structural elements using
`timber_design.populators`.

## Cross-section layers live on the Panel

A panel's cross-section is described by **layers that belong to the panel
itself** (in `compas_timber`), not by a separate configuration object.  Call
`panel.define_core_layer(start, end)` to slice the panel — measured from the
``outline_a`` face — into up to three layers:

- `panel.exterior_layer` — `[0, start]` (omitted/``None`` when ``start == 0``)
- `panel.core_layer` — `[start, end]` (the structural frame)
- `panel.interior_layer` — `[end, thickness]` (omitted/``None`` when ``end == thickness``)

Each `Layer` *is a* `Panel` (it wraps a sliced ``layer_panel``), so it can be
joined by `PanelJoint`s and added to the `TimberModel` as a child of the panel.
The `stud_panel()` factory function calls `define_core_layer` for you; for a
panel that already carries a layer structure you provide the agents directly.

## The PanelPopulator

`PanelPopulator` is the single entry point — there is no longer a separate
`PanelPopulatorConfig`.  You hand it the panel and a list of agents (each agent
references one of the panel's layers); the factory functions assemble both:

```python
from compas_timber.model import TimberModel
from timber_design.populators.populator_configs.stud_panel_config import stud_panel

populator = stud_panel(
    panel=panel,                 # define_core_layer is called for you
    standard_beam_width=60,
    stud_spacing=625,
    sheeting_inside=15,
    sheeting_outside=18,
)

model = TimberModel()
model.add_element(panel)         # panel + its layers enter the model tree
populator.populate_elements()    # prepare -> generate -> extend -> trim -> add
populator.join_elements()        # within-agent + cross-agent joints
populator.merge_with_model(model)
```

### What the populator does internally

The populator always works in a flat *populator space* (the panel re-expressed
as an axis-aligned rectangle with the stud orientation aligned to +Y), then maps
results back to the world-space panel:

```mermaid
flowchart LR
    classDef element fill:#d4edda,stroke:#28a745,color:#000
    classDef stage   fill:#f8f9fa,stroke:#6c757d,color:#000
    classDef model   fill:#f8d7da,stroke:#721c24,color:#000

    panel(["Panel (+ layers, world space)"]):::element

    subgraph pop["  PanelPopulator  "]
        direction TB
        prep["prepare()<br/>mirror layers onto a populator-space panel<br/>+ re-point agents at the mirror"]:::stage
        gen["generate_elements()"]:::stage
        ext["extend_elements()"]:::stage
        trim["trim_elements()"]:::stage
        add["add_elements_to_model()"]:::stage
        join["join_elements()"]:::stage
        prep --> gen --> ext --> trim --> add --> join
    end

    panel -->|populate_elements()| prep

    model[("TimberModel")]:::model
    join -->|"merge_with_model()<br/>re-parent each element under its<br/>matching original-panel layer"| model
```

- **`prepare()`** builds a populator-space copy of the panel, mirrors the
  panel's layer structure onto *that* copy (never onto the original), and
  re-points every agent at the mirrored layer.  It is deferred until
  `populate_elements()` so it reads the panel's *final* layer geometry — i.e.
  after any panel-joinery extensions (see the model workflow below).
- **`merge_with_model()`** transforms each generated element from populator
  space straight into its owning **original-panel layer's** local frame and
  parents it there, so framing is grouped by layer in the model tree and moves
  with the layer.

---

## Prerequisites

```python
from compas_timber.elements import Panel
from compas_timber.model import TimberModel
from timber_design.populators import OpeningPopulatorAgent
from timber_design.populators import PanelPopulator
from timber_design.populators.populator_configs.stud_panel_config import stud_panel
```

All lengths are in the model's native units (mm in the examples below).

!!! note "API change"
    The `*Config` classes (`PanelPopulatorConfig`, `LayerConfig`,
    `EdgePopulatorAgentConfig`, …) have been removed.  Layers now live on the
    `Panel` (`panel.define_core_layer`), and `PanelPopulator` is constructed
    directly with a panel and a list of agents.  Sections further down that
    still reference the old `*Config` API are being updated.

---

## Model-level workflow (CT: Model)

When several panels are joined to each other, the order of operations matters.
Panel joints **extend the per-layer `layer_panels`** (so adjacent panels' layers
butt correctly), and the populators must see that *final* layer geometry.  The
`CT: Model` component runs:

1. **Add elements** — each panel (with its layer structure) is added to the
   model.  `element.reset()` is called first so a Grasshopper re-solve starts
   from a clean state (prior extensions / joinery features / connection
   interfaces are cleared; user openings are kept).
2. **Panel joinery first** — `model.connect_adjacent_panels()`, promote the
   panel-joint candidates via the joint rules, then `model.process_panel_joinery()`
   so each `PanelJoint` extends its layers.
3. **Populate** — run each `PanelPopulator` (`populate_elements` → `join_elements`
   → `merge_with_model`).  Because `prepare()` is deferred, agents now generate
   against the extended layers.
4. **Beam / plate joinery** — `connect_adjacent_beams` / `connect_adjacent_plates`
   then apply the joint rules.
5. **Final joinery** — `model.process_joinery(include_panels=False)` applies
   extensions + features for the non-panel joints.  Panel joints are skipped
   here because step 2 already processed them (their layer extensions are not
   idempotent).
6. **User features**.

---

## Basic stud wall

The simplest case: a rectangular panel with evenly-spaced vertical studs and
plate beams along the top and bottom edges.

```python
from compas.geometry import Point, Polyline
from compas_timber.elements import Panel
from compas_timber.model import TimberModel
from timber_design.populators.populator_configs.stud_panel_config import stud_panel

# 1 -- Build the Panel and add it (with its layers) to the model
outline_a = Polyline([Point(0, 0, 0), Point(4000, 0, 0), Point(4000, 2700, 0), Point(0, 2700, 0), Point(0, 0, 0)])
outline_b = Polyline([Point(0, 0, 160), Point(4000, 0, 160), Point(4000, 2700, 160), Point(0, 2700, 160), Point(0, 0, 160)])
panel = Panel.from_outlines(outline_a, outline_b)

# 2 -- The factory returns a ready-to-run PanelPopulator (and calls
#      panel.define_core_layer for you).
populator = stud_panel(
    panel=panel,
    standard_beam_width=60,   # default cross-section width, mm
    stud_spacing=625,         # on-centre stud spacing, mm
)

model = TimberModel()
model.add_element(panel)      # panel + its layers enter the model tree

# 3 -- Run the population stages
populator.populate_elements()   # prepare -> generate -> extend -> trim -> add
populator.join_elements()       # within-agent and cross-agent joints

# 4 -- Merge framing into the model under the matching panel layers
populator.merge_with_model(model)

# 5 -- Apply fabrication features for the joints created above
model.process_joinery()
```

After `merge_with_model` the model contains, **grouped under the panel's
`core_layer`**:

- **top_plate_beam** — full-width horizontal beam along the top edge
- **bottom_plate_beam** — full-width horizontal beam along the bottom edge
- **edge_stud** × 2 — vertical beams at the left and right panel edges
- **stud** × N — intermediate vertical studs at 625 mm spacing

---

## Adding sheathing plates

Pass non-zero `sheeting_inside` and/or `sheeting_outside` to create flat
:class:`~compas_timber.elements.Plate` elements on one or both faces.

```python
config = stud_panel(
    panel=panel,
    standard_beam_width=60,
    stud_spacing=625,
    sheeting_inside=15,    # OSB / gypsum board on the inside face, mm
    sheeting_outside=22,   # structural sheathing on the outside face, mm
)
```

The frame is automatically inset from the full panel faces by the sheathing
thicknesses, so beams and plates never overlap.

---

## Stud wall with a window opening

Openings are modelled as :class:`~compas_timber.panel_features.Opening` features
attached to the panel.  `stud_panel()` registers an
:class:`~timber_design.populators.OpeningPopulatorAgentConfig` under
`default_feature_configs[Opening]` for you, so any Opening on the panel is
automatically picked up and produces an
:class:`~timber_design.populators.OpeningPopulatorAgent`.

```python
from compas_timber.panel_features.opening import Opening, OpeningType

# Define the opening outline in panel-local XY coordinates.
# from_outline_panel projects it onto both faces of the panel automatically.
win_outline = Polyline([Point(800, 900, 0), Point(2200, 900, 0), Point(2200, 2400, 0), Point(800, 2400, 0), Point(800, 900, 0)])
opening = Opening.from_outline_panel(win_outline, panel, opening_type=OpeningType.WINDOW)
panel.add_feature(opening)

config = stud_panel(
    panel=panel,
    standard_beam_width=60,
    stud_spacing=625,
    lintel_posts=True,         # add jack studs (lintel posts) beside the header
)

populator = config.create_populator()
populator.populate_elements()
populator.join_elements()
populator.process_joinery()
populator.merge_with_model(model)
```

The opening agent creates: **header**, **sill**, **king_stud** × 2, and
(with `lintel_posts=True`) **jack_stud** × 2.  Studs that would pass through
the opening zone are trimmed and the resulting short segments discarded.

### Door opening

For a door set `opening_type=OpeningType.DOOR`.  The sill is omitted and the
bottom plate beam can optionally be split at the opening:

```python
door_outline = Polyline([Point(1500, 0, 0), Point(2500, 0, 0), Point(2500, 2100, 0), Point(1500, 2100, 0), Point(1500, 0, 0)])
opening = Opening.from_outline_panel(door_outline, panel, opening_type=OpeningType.DOOR)
panel.add_feature(opening)

config = stud_panel(
    panel=panel,
    standard_beam_width=60,
    stud_spacing=625,
    lintel_posts=True,
    split_bottom_plate_beam=True,  # gap in the bottom plate beneath the door
)
```

---

## Custom beam dimensions per category

Each beam category that an agent can produce has an **explicit per-category
width** parameter on its config — there is no longer a single
`beam_width_overrides` dict.  Any category not given an explicit width falls
back to `standard_beam_width`.

```python
config = stud_panel(
    panel=panel,
    standard_beam_width=60,
    stud_spacing=625,
    stud_width=60,              # intermediate studs
    edge_stud_width=80,         # vertical edge studs (wider than studs here)
    top_plate_beam_width=60,
    bottom_plate_beam_width=60,
)
```

Opening-related categories (header, sill, king_stud, jack_stud) are owned by
:class:`~timber_design.populators.OpeningPopulatorAgentConfig` and are set there
when you supply your own opening config:

```python
config = stud_panel(
    panel=panel,
    standard_beam_width=60,
    stud_spacing=625,
    default_feature_configs={
        Opening: OpeningPopulatorAgentConfig(
            lintel_posts=True,
            header_width=120,    # double-up the header
            king_stud_width=60,
            jack_stud_width=60,
        ),
    },
)
```

---

## Snapping edge beams to standard lumber widths

`standard_beam_width_increment` rounds each edge-beam width *up* to the nearest
multiple of that value.  Combine it with the explicit per-category widths above
when you need a specific lower bound.

```python
config = stud_panel(
    panel=panel,
    standard_beam_width=60,
    stud_spacing=625,
    standard_beam_width_increment=20,  # round each edge-beam width up to 60, 80, 100, ... mm
)
```

---

## Reusing one config across many panels

`config.create_populator()` is the only entry point.  Reuse a config across
many panels by assigning `config.panel = panel` before each call (the factory
functions also accept a `panel=` keyword for the one-shot case).  Call
`merge_with_model` with `clear_panel=True` to replace any previously generated
framing when re-running.

```python
config = stud_panel(
    standard_beam_width=60,
    stud_spacing=625,
    sheeting_inside=15,
)

for panel in list(model.panels):
    config.panel = panel
    populator = config.create_populator()
    populator.populate_elements()
    populator.join_elements()
    populator.process_joinery()
    populator.merge_with_model(model, clear_panel=True)
```

!!! note
    `list(model.panels)` captures the panel list before the loop so that newly
    added child elements are not iterated.

---

## Controlling stud orientation

By default studs run parallel to the panel's local Y axis (vertical).  Pass
a world-space `orientation` vector to `stud_panel()` (or
`PanelPopulatorConfig`) to override this — useful for diagonal or horizontal
framing.

```python
from compas.geometry import Vector

config = stud_panel(
    panel=panel,
    standard_beam_width=60,
    stud_spacing=625,
    orientation=Vector(0, 0, 1),   # vertical in world space
)
```

The vector is projected onto the panel plane automatically; a vector parallel
to the panel normal falls back to the default.

---

## Type-level feature definitions

`default_feature_configs` maps a feature class to a
:class:`~timber_design.populators.FeatureAgentConfig` instance (with no
`feature` set).  When `create_populator()` iterates over `panel.features` it
picks the most-specific matching config using MRO-based lookup and calls
`get_agent_from_feature` for each match.

```python
from timber_design.populators import OpeningPopulatorAgentConfig

config = stud_panel(
    panel=panel,
    standard_beam_width=60,
    stud_spacing=625,
    default_feature_configs={
        Opening: OpeningPopulatorAgentConfig(lintel_posts=True),
    },
)

populator = config.create_populator()   # one agent per Opening on the panel
```

Because `Door` is a subclass of `Opening`, you can provide separate configs for
each type and the most-specific key wins:

```python
default_feature_configs={
    Opening: OpeningPopulatorAgentConfig(),                    # fallback
    Door:    OpeningPopulatorAgentConfig(lintel_posts=True),   # more specific
}
```

---

## Injecting per-instance feature agents

Set `instance_feature_configs` on the config (either at construction or after)
to a list of :class:`~timber_design.populators.FeatureAgentConfig` instances —
each with its `feature` attribute pointing at a specific feature on the panel.
Instance configs always take precedence over `default_feature_configs` for
their feature.

```python
from timber_design.populators import OpeningPopulatorAgentConfig

agent_cfg = OpeningPopulatorAgentConfig(feature=my_opening, lintel_posts=True)

config.panel = panel
config.instance_feature_configs = [agent_cfg]
populator = config.create_populator()
```

The feature geometry is automatically transformed into populator space before
the agent is instantiated.

---

## Understanding the layer system

The panel cross-section is described by an ordered list of
:class:`~timber_design.populators.LayerConfig` objects — one per layer from
the interior face (`outline_a`) to the exterior face (`outline_b`).

Each `LayerConfig` is a pure data blueprint.  It carries:

- `thickness` — the layer's depth in model units.  Pass ``None`` to let the
  layer claim the remaining panel thickness after all fixed-thickness siblings
  have been allocated (at most one ``None`` per sibling group).
- `name` — a human-readable identifier used in the resolved `Layer` object.
- `agent_configs` — the :class:`~timber_design.populators.LayerAgentConfig`
  instances that will be instantiated on this layer.
- `sublayers` — optional nested `LayerConfig` children.

There is no `is_framing_layer` flag — instead, the `OpeningPopulatorAgentConfig`
(and other feature configs) declare *which* layers they frame on via
`framing_layer_defs=[…]` and which they trim through via
`trimming_layer_defs=[…]`.  The `stud_panel()` factory wires these up for you.

At runtime, `PanelPopulatorConfig.create_populator_model` resolves all
thicknesses, calls `resolve_beam_widths` to fill every agent config's
`beam_widths` with `standard_beam_width`, and then delegates to
`LayerConfig.model_from_panel` to slice the source panel into
:class:`~timber_design.populators.Layer` objects.  Slicing uses *outline
chaining* — each layer's far boundary is reused as the next layer's near
boundary with no floating-point re-interpolation.

### Custom cross-section with LayerConfig

Use `PanelPopulatorConfig` directly when you need full control over the layer
stack:

```python
from timber_design.populators import (
    PanelPopulatorConfig,
    LayerConfig,
    EdgePopulatorAgentConfig,
    StudPopulatorAgentConfig,
    PlatePopulatorAgentConfig,
    OpeningPopulatorAgentConfig,
)

interior_ld = LayerConfig(15, name="interior", agent_configs=[PlatePopulatorAgentConfig()])
frame_ld    = LayerConfig(None, name="frame",
                          agent_configs=[
                              EdgePopulatorAgentConfig(),
                              StudPopulatorAgentConfig(stud_spacing=625),
                          ])
exterior_ld = LayerConfig(22, name="exterior", agent_configs=[PlatePopulatorAgentConfig()])
layer_defs  = [interior_ld, frame_ld, exterior_ld]

config = PanelPopulatorConfig(
    panel=panel,
    standard_beam_width=60,
    layer_defs=layer_defs,
    default_feature_configs={
        # Tell the opening agent which layer to frame and which layers to
        # cut its outline through (so sheathing plates get the opening hole).
        Opening: OpeningPopulatorAgentConfig(
            lintel_posts=True,
            framing_layer_defs=[frame_ld],
            trimming_layer_defs=layer_defs,
        ),
    },
)
populator = config.create_populator()
```

The ``None`` thickness on the frame layer receives whatever is left after the
15 mm and 22 mm sheeting layers are subtracted from the total panel thickness.

### Nested sublayers

A `LayerConfig` can contain `sublayers` instead of `agent_configs` to
group related layers under a shared parent thickness.  Sublayers inherit the
parent's remaining thickness the same way:

```python
from timber_design.populators import LayerConfig, PlatePopulatorAgentConfig

insulation = LayerConfig(
    thickness=120,
    name="insulation",
    sublayers=[
        LayerConfig(60, name="insulation_a", agent_configs=[PlatePopulatorAgentConfig()]),
        LayerConfig(60, name="insulation_b", agent_configs=[PlatePopulatorAgentConfig()]),
    ],
)
```

!!! note
    A `LayerConfig` may have either `agent_configs` or `sublayers`, never
    both.  The outermost list passed to `PanelPopulatorConfig` may freely mix
    leaf definitions (with `agent_configs`) and composite definitions (with
    `sublayers`).

---

## Complete single-panel example

```python
from compas.geometry import Point, Polyline
from compas_timber.elements import Panel
from compas_timber.model import TimberModel
from compas_timber.panel_features.opening import Opening, OpeningType
from timber_design.populators import OpeningPopulatorAgentConfig
from timber_design.populators.populator_configs.stud_panel_config import stud_panel

# Model
model = TimberModel()

outline_a = Polyline([
    Point(0, 0, 0), Point(5000, 0, 0), Point(5000, 2700, 0),
    Point(0, 2700, 0), Point(0, 0, 0),
])
outline_b = Polyline([
    Point(0, 0, 160), Point(5000, 0, 160), Point(5000, 2700, 160),
    Point(0, 2700, 160), Point(0, 0, 160),
])
panel = Panel.from_outlines(outline_a, outline_b)
model.add_element(panel)

# Opening
win_outline = Polyline([
    Point(1000, 800, 0), Point(2400, 800, 0), Point(2400, 2200, 0),
    Point(1000, 2200, 0), Point(1000, 800, 0),
])
panel.add_feature(Opening.from_outline_panel(win_outline, panel, opening_type=OpeningType.WINDOW))

# Config: stud_panel() builds the right layer stack and wires up an Opening
# agent for any Opening feature on the panel.  Customize opening beam widths
# by supplying your own OpeningPopulatorAgentConfig.
config = stud_panel(
    panel=panel,
    standard_beam_width=60,
    stud_spacing=625,
    sheeting_inside=15,
    sheeting_outside=22,
    lintel_posts=True,
    default_feature_configs={
        Opening: OpeningPopulatorAgentConfig(lintel_posts=True, header_width=120),
    },
)

# Populate
populator = config.create_populator()
populator.populate_elements()
populator.join_elements()
populator.process_joinery()
populator.merge_with_model(model)

# Inspect
for element in model.elements():
    print(element, element.attributes.get("category"))
```
