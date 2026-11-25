# Populating Panels

This guide walks through framing a :class:`~compas_arch.elements.Panel` with
beams and plates using `timber_design_populator`.  A runnable version of every
scenario below lives in `examples/panel_population.py`.

All lengths are in the model's native units (mm in the examples).

## Concepts

- **Layers belong to the panel.**  A panel's cross-section is a
  :class:`~compas_arch.elements.LayerStructure` (from `compas_arch`): a tree
  of :class:`~compas_arch.elements.LayerDefinition`s, each with a name, a
  thickness, optional sublayers and, for the exterior, core and interior
  layers, a :class:`~compas_arch.elements.LayerRole`.  The populator never defines layers itself;
  it frames the ones the panel already has.
- **Agents generate the framing.**  Every agent is a `PopulatorAgent`
  acting on some layers (its element layers, where it creates elements, and its
  trimming layers, whose elements it cuts; `layer=` sets both):
    - **Panel-wide agents** frame or sheathe whole layers and are given to the
      populator: `EdgeAgent` (plates and edge studs along the outline),
      `StudAgent` (intermediate studs), `PlateAgent` (a sheathing plate),
      `LayerBoundaryAgent` (no elements; it only clips other agents to the
      layer outline).
    - **Detail agents** (`*DetailAgent`) build one part of one feature from
      explicit inputs: `VoidFramingDetailAgent` frames a void in the core,
      `LayerCutDetailAgent` cuts it out of the layers,
      `ServiceDrillingDetailAgent` / `ServiceNotchDetailAgent` machine the beams
      a service crosses, `LayerExtensionDetailAgent` moves layer edges and
      `BackingStudDetailAgent` places backing studs.  You do not create these
      yourself: detail sets do.
- **Every feature is built by exactly one detail set**: the feature's own
  `detail_set`, or else the populator's default for its type.  A detail set
  reads the feature and the panel's layers and expands into detail agents, e.g.
  `FramedOpeningDetailSet` into a framing agent and a cutting agent.  The
  feature only states design intent (where the opening is, door or window); the
  set holds the construction decisions.  The built-in sets are one possible way
  to build each feature, not the only one.
- **Panel joints do all cross-panel calculation.**  A joint that builds a
  connection detail (e.g. `LGenericPanelJoint`) sees both panels, works out
  each panel's half, and hands it to that panel's interface feature as a ready
  detail set.  So a populator only ever needs its own panel.
- **`PanelPopulator` runs the pipeline** and is the only thing that writes to
  the model.  `stud_panel()` is a factory that builds one with the usual agents
  and default detail sets.

There are three ways to extend the populator:

| To add | Write | Example |
|---|---|---|
| a new base behaviour | a detail agent | drilling a beam, placing a backing stud |
| a new way to build a feature | a detail set (a new combination of agents, or new inputs for them) | a recessed cladding cut around an opening |
| a new connection detail | a panel joint and its detail set | a corner post at an L corner |

## Basic stud wall

```python
from compas.geometry import Point, Polyline
from compas_arch.elements import Panel
from compas_timber.model import TimberModel
from timber_design_populator import stud_panel

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
from compas_arch.elements import LayerDefinition, LayerStructure

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

Openings are :class:`~compas_arch.panel_features.Opening` features on the
panel.  `stud_panel()` builds them with a default `FramedOpeningDetailSet`,
which frames the opening on the core layer and cuts it through every layer, so
sheathing plates and battens get the hole too.

```python
from compas_arch.panel_features import Opening, OpeningType

window = Polyline([Point(800, 900, 0), Point(2000, 900, 0), Point(2000, 2200, 0), Point(800, 2200, 0), Point(800, 900, 0)])
panel.add_feature(Opening.from_outline_panel(window, panel, opening_type=OpeningType.WINDOW))
```

A window gets a **header**, a **sill** and two **king_stud**s; a door gets no
sill.  Studs that cross the opening are cut at its boundary and the inner
pieces removed, and studs that coincide with a king or jack stud are dropped.

To customise every opening, pass your own set under `default_detail_sets`:

```python
from timber_design_populator.detail_sets import FramedOpeningDetailSet

populator = stud_panel(
    panel,
    standard_beam_width=60,
    stud_spacing=625,
    default_detail_sets={
        Opening: FramedOpeningDetailSet(
            lintel_posts=True,             # add jack studs under the header
            header_width=120,
            split_bottom_plate_beam=True,  # doors only: cut the bottom plate at the opening
            cut_offsets={"exterior": 20},  # cut the cladding 20 beyond the opening
        ),
    },
)
```

To give one opening different settings, give it its own `detail_set`, which
replaces the populator's default for its type (in Grasshopper: `CT: Detail
Agent Set` into the `detail_set` input of `CT: Panel Opening`):

```python
special = Opening.from_outline_panel(window, panel, detail_set=FramedOpeningDetailSet(header_width=200))
```

Every feature type works this way, including the interfaces panel joints put
on a panel (see below): a feature is built by its own `detail_set`, or else by
the populator's default for its type.  Each populator expands a fresh clone of
the set on every run, so one set can serve many features and panels.

`stud_panel()` uses these defaults:

| Feature | Default detail set |
|---|---|
| `Opening` | `FramedOpeningDetailSet()` |
| `MEPPenetration` | `FramedPenetrationDetailSet()` |
| `Niche` | `FramedNicheDetailSet()` |
| `LinearService` | `LinearServiceDetailSet()` (drilling) |
| `PanelConnectionInterface` | none: the panel joint sets it |

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
| `header`, `sill`, `king_stud`, `jack_stud`  | `FramedOpeningDetailSet(header_width=…, …)` (and the penetration / niche sets) |

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
from timber_design_populator import StudAgent
from timber_design_rules import CategoryRule

studs = StudAgent(
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
from timber_design_populator import EdgeAgent, PanelPopulator, PlateAgent, StudAgent

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

from timber_design_populator.detail_sets import FramedOpeningDetailSet

board, battens = panel.exterior_layer.sublayers
populator = PanelPopulator(
    panel,
    agents=[
        PlateAgent(board),
        PlateAgent(panel.interior_layer),
        EdgeAgent(panel.core_layer),
        StudAgent(panel.core_layer, stud_spacing=600),
    ],
    standard_beam_width=60,
    # the opening set frames in the core and cuts the exterior (board and battens), core and interior
    default_detail_sets={Opening: FramedOpeningDetailSet()},
)
```

`agents=` takes panel-wide agents only; a detail agent given there is skipped
and reported in `debug_info` (put it in a detail set instead).

Agents run in order of `priority` (lower first), and agents with the same
priority keep the order given, detail agents after the panel-wide ones.
Class defaults: `LayerExtensionDetailAgent` -100 (layer geometry comes first),
`EdgeAgent` and `LayerBoundaryAgent` -10, everything else 0.  Pass
`priority=` to any agent to change it.  The order also sets joint precedence:
when several agents own elements in a cluster, the earlier agent's rules are
tried first.

`PanelPopulator` clones the agents you give it, so the same agent objects can
be reused for many panels.  Inspect the populated agents (including the
expanded detail agents) through `populator.agents`.

## What happens inside

`populate_elements()` extracts the panel's layer tree into the populator's own
model, where all geometry is in the panel's local frame (X along the panel,
Y up, Z through the thickness).  It expands every feature's detail set into
agents, sorts all agents by priority, and then runs these stages, each over
every agent in that order:

1. **modify layers**: agents set layer extension planes (e.g. a layer stagger
   at a corner), which are then applied, so every later stage sees the final
   layers.  If two agents move the same layer edge, the later one wins and
   this is reported in `debug_info`;
2. **generate**: every agent creates its elements and records its boundary
   outline on each layer it acts on;
3. **define outlines**: agents record outlines on the layers they only trim;
4. **extend**: agents extend their elements to their neighbours' boundaries
   (e.g. king studs to the plates);
5. **split**: each agent's boundary splits other agents' beams and cuts plates;
6. **cull**: beam segments that fall outside an *inclusive* boundary (the edge
   agent) or inside an *exclusive* one (an opening) are removed;
7. **machine**: agents add features to surviving beams (e.g. service holes).

An agent never trims its own elements.  `join_elements()` and
`process_joinery()` then create the joints and their fabrication features, and
`merge_with_model(model)` moves the layer subtree back under the original
panel, converting the internal `Beam2D`s to plain `Beam`s.  By default it first
removes any framing the panel already had, so re-populating is safe.

## Grasshopper

The same workflow as components:

1. `CT: Panel Layer Definition` (and optionally `CT: Subdivide Layer`) →
   `CT: Panel`.
2. `CT: Stud Panel` for the standard case, or `CT: Layer Agent` →
   `CT: Panel Populator` for a custom stack.  Use
   `CT: Decompose LayerStructure` to get layer paths for the agents.
   `CT: Detail Agent Set` makes detail sets for the populators'
   `default_detail_sets` or a feature component's `detail_set`.  The panel
   joint rule components offer the detail joints (`LGenericPanelJoint`,
   `TGenericPanelJoint`) with their flags as inputs.
3. `CT: Model` → `CT: Populate Model` with the populators.  `CT: Model` adds
   each panel's layers to the model itself, and `CT: Populate Model` frames
   the layers as the panel joints and connection details shaped them.
4. `CT: Filter Display` to show the result by layer.

## Detail sets

A detail set decides how a feature is built.  It reads the feature and the
panel's layers, derives what each agent needs (frames, cut outlines, depths,
shared widths) and expands into detail agents, on every run, once the layers
are in populator space.  Built-in sets live in
`timber_design_populator.detail_sets`, one module each.  They are examples and
defaults; write your own for any other construction:

| Set | Builds | Expands into |
|---|---|---|
| `FramedOpeningDetailSet` | `Opening` | `VoidFramingDetailAgent` (sill for windows; doors can split the bottom plate) + a `LayerCutDetailAgent` through each of exterior, core and interior |
| `FramedPenetrationDetailSet` | `MEPPenetration` | framing around the core outline + a `LayerCutDetailAgent` per role layer, each with that layer's outline |
| `FramedNicheDetailSet` | `Niche` | framing in the core (trimming it only when the niche goes through) + a `LayerCutDetailAgent` on the side layer, to depth or through |
| `LinearServiceDetailSet(mode="drilling")` | `LinearService` | `ServiceDrillingDetailAgent` on the core, or with `mode="notching"` a `ServiceNotchDetailAgent` notching from the interior face |

Detail agents take explicit inputs, never the feature: a
`VoidFramingDetailAgent` gets its frame and boundary, a `LayerCutDetailAgent`
the layer to cut and the cut itself (an outline, or a prism between two
outlines; through, or a blind pocket of some depth).  The cut agent applies it
to that layer and its sublayers: beams such as battens are split and removed
inside the cut, plates get the hole.  So a set holds only the decisions (which
layer, by which outline, how deep), and a custom detail is a set that decides
differently, e.g. cuts one layer somewhere other than the feature outline:

```python
from timber_design_populator import LayerCutDetailAgent
from timber_design_populator.detail_sets import DetailAgentSet, FramedOpeningDetailSet

class RecessedCladdingOpeningDetailSet(DetailAgentSet):
    FEATURE_TYPES = (Opening,)

    def __init__(self, recess=50.0):
        super().__init__()
        self.recess = recess

    @property
    def __data__(self):
        return {"recess": self.recess}

    def expand(self, feature, panel, layer_tree, standard_beam_width=None):
        agents, errors = FramedOpeningDetailSet().expand(feature, panel, layer_tree, standard_beam_width)
        exterior = self.root_layer(layer_tree, "exterior")
        bigger = ...  # the cladding cut, derived from feature.outline_a and self.recess
        # keep the built-in framing and cuts, except the exterior cut, which is replaced
        kept = [a for a in agents if not (isinstance(a, LayerCutDetailAgent) and a.trimming_layer_paths == [exterior.layer_path])]
        return kept + [LayerCutDetailAgent(exterior.layer_path, outline_a=bigger, feature=feature)], errors
```

A new base behaviour is a new detail agent: subclass `PopulatorAgent`, set
`IS_DETAIL = True`, take its inputs as constructor arguments (and return them
from `__data__`, so it can be cloned and serialized), and implement the hooks
it needs: `modify_layers(layer_tree)`, `generate_elements_for_layer(layer)`,
`trim_plate(plate)`, `machine_element(element)`.

New built-in sets and agents go in their own module in
`timber_design_populator/detail_sets/` or `populator_agents/` and are exported
from that package's `__init__.py`: compas looks a class up there when loading
it from JSON (e.g. a feature's `detail_set`).

## Connection details

A panel joint shapes the panel envelope; a *detail joint* also builds a
connection detail.  It does all cross-panel calculation while it sees both
panels, and gives each panel's
:class:`~compas_arch.panel_features.PanelConnectionInterface` that panel's
half as a ready detail set, in the panel's own frame.  The populator builds
the interface like any other feature, so nothing is configured on the
populator and it never sees the other panel.  Pick the joint and set its
flags through a joint rule (in Grasshopper: any panel joint rule component;
the flags appear as inputs):

```python
from compas_timber.connections import JointTopology
from timber_design_populator import LGenericPanelJoint, TGenericPanelJoint
from timber_design_rules import TopologyRule

rules = [
    TopologyRule(JointTopology.TOPO_EDGE_EDGE, LGenericPanelJoint, backing_studs=True, backing_stud_width=45),
    TopologyRule(JointTopology.TOPO_EDGE_FACE, TGenericPanelJoint, backing_studs=True),
]
```

Built-in detail joints (`timber_design_populator.panel_joints`), each with its
detail set:

- `LGenericPanelJoint` → `LGenericPanelJointDetailSet`, at an L-butt corner:
    - `stagger_layers=True`: staggers exterior, core and interior.  The main
      panel's core butts against the cross panel's core, while the cladding
      layers wrap the corner the other way round.  Both panels need all three
      role layers; a missing one is reported by the populator.
    - `backing_studs=False`: gives the cross panel a backing stud under the
      inside corner.
- `TGenericPanelJoint` → `TGenericPanelJointDetailSet`, at a T junction:
    - `backing_studs=False`: gives the cross panel (the one the other panel's
      edge lands on) a backing stud centred on each inside corner.

Backing studs: `backing_stud_width` defaults to the populator's
`standard_beam_width`; `backing_stud_inset` moves the studs from the partner's
faces into its footprint.  Studs closer than one width merge into one centred
stud, a corner already backed by a parallel edge stud is skipped, and regular
studs running alongside a backing stud are removed.

The detail set expands into a `LayerExtensionDetailAgent`, which moves the
layer edges before anything is generated, and a `BackingStudDetailAgent` on
the core, which then places its studs against the staggered layers.  The plain
`compas_arch` joints (`PanelLButtJoint`, `PanelTButtJoint`, `PanelMiterJoint`)
carry no detail: their layers stay as the envelope shaped them.

A new connection detail is a new joint/detail set pair: subclass a panel joint,
compute each panel's half in `add_features()` (after `super().add_features()`)
in that panel's local frame, and set it on `self.interface_a.detail_set` /
`self.interface_b.detail_set` as your own detail set.
