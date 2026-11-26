# Populating Panels

This guide walks through framing a :class:`~timber_design_arch.elements.Panel` with
beams and plates using `timber_design_populator`.  A runnable version of every
scenario below lives in `examples/panel_population.py`.

All lengths are in the model's native units (mm in the examples).

For a diagram overview first, see [Panels, Joints, Features and the Populator at a Glance](populator_overview.md).

## Concepts

- **Layers belong to the panel.**  A panel's cross-section is a
  :class:`~timber_design_arch.elements.LayerStructure` (from `timber_design_arch`): a tree
  of :class:`~timber_design_arch.elements.LayerDefinition`s, each with a name, a
  thickness, optional sublayers and, for the exterior, core and interior
  layers, a :class:`~timber_design_arch.elements.LayerRole`.  The populator never defines layers itself;
  it frames the ones the panel already has.
- **Agents generate the framing.**  Every agent is a `PopulatorAgent`
  acting on some layers (its element layers, where it creates elements, and its
  trimming layers, whose elements it cuts; `layer=` sets both):
    - **Panel-wide agents** frame or sheathe whole layers and are given to the
      populator: `EdgeAgent` (plates and edge studs along the outline),
      `FasciaEdgeAgent` (like `EdgeAgent`, but an angled fascia on sloped
      edges, see below), `StudAgent` (intermediate studs), `BoardAgent` (battens,
      cladding boards: parallel members at a spacing, in any direction), `PlateAgent` (a sheathing plate),
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
from timber_design_arch.elements import Panel
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
from timber_design_arch.elements import LayerDefinition, LayerStructure

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

Openings are :class:`~timber_design_arch.panel_features.Opening` features on the
panel.  `stud_panel()` builds them with a default `FramedOpeningDetailSet`,
which frames the opening on the core layer and cuts it through every layer, so
sheathing plates and battens get the hole too.

```python
from timber_design_arch.panel_features import Opening, OpeningType

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

## Sloped edges: fascia beams

`EdgeAgent` frames a sloped edge (an edge plane that is not square to the
panel, e.g. a plumb-cut eave) with a flat beam, widened to reach the edge and
cut along the edge plane.  `FasciaEdgeAgent` uses an angled fascia instead: the
beam is rotated about its axis so its outer face lies on the edge plane, and
it is made higher than the layer is thick so it covers the layer on both of
its faces.  Studs and other beams butted against it get angled jack rafter cuts
on its sloped inner face, from the usual joint rules.  Square edges get the same
beams as with `EdgeAgent`.

```python
from timber_design_populator import FasciaEdgeAgent, PanelPopulator, PanelType, StudAgent

roof = PanelType(
    "roof",
    panel.layer_structure,
    agents=[FasciaEdgeAgent(panel.core_layer, flush_cuts=True), StudAgent(panel.core_layer, stud_spacing=600)],
    standard_beam_width=60,
)
populator = PanelPopulator(panel, roof)
```

`flush_cuts=True` trims each fascia flush with the layer's two faces
(longitudinal cuts); without it, the fascia overhangs them.  With
`standard_beam_width_increment`, the fascia's height is rounded up as well.

## Battens and cladding: BoardAgent

`BoardAgent` fills a layer with parallel members at an on-centre `spacing`:
battens, counter-battens, cladding boards, the joists of an insulation layer.
`direction` is a vector in the panel plane (default the panel's y axis, "up"
on a wall), `offset` shifts the grid, and `category` names the members, e.g.
`"batten"`.  The grid is measured from the panel's origin, not from the
layer's edge, so members with the same spacing line up from layer to layer:
battens @ 625 sit over studs @ 625, however far a layer is extended.  Members
are placed where their full width lies within the layer and are clipped to
its outline.

```python
from compas.geometry import Vector
from timber_design_populator import BoardAgent

battens = BoardAgent(battens_path, board_width=50, spacing=625, category="batten")
cladding = BoardAgent(cladding_path, board_width=146, spacing=150, direction=Vector(1, 0, 0), category="cladding")
```

`StudAgent` is a `BoardAgent` of category `"stud"`: other agents (edge plates,
opening framing, backing studs) rely on that category.  Unlike plain boards,
studs are trimmed by the framing boundary (`EdgeAgent`), and the first one is
one spacing from the panel origin, where the edge stud is.

## Panel types

A `PanelType` names a whole buildup, e.g. an exterior wall from a catalogue
such as [dataholz.eu](https://www.dataholz.eu/bauteile/aussenwand.htm):

- its cross-section, a `LayerStructure` whose layers carry a `material` and
  free `attributes` (`fill` for insulation between members, `membrane_a` /
  `membrane_b` for a membrane on a layer's outer / inner face);
- the panel-wide agents that build each layer, referring to layers by path,
  name or role;
- its default detail sets (how openings, services and so on are built), and
  the populator settings.

It holds no panel, so one type serves every panel of that type.  `apply` gives
a panel the cross-section (a design step: panel joints then see the real
layers), and `populator` makes the populator that builds it.

```python
from timber_design_populator import get_panel_type

wall = get_panel_type("awrhho05b")      # timber frame, ventilated, timber cladding
wall.apply(panel)                       # the panel must be wall.thickness (247) thick
populator = wall.populator(panel)       # agents=, default_detail_sets= etc. add or replace
```

The built-in types are `stud_wall` (any cross-section with a core) and, after
dataholz.eu, `awrhho05b`, `awrhhi01a` (with an installation layer) and
`awmhhi01a` (solid timber: a CLT core whose openings are cut through with
`CutThroughDetailSet`, not framed).  Their factories take parameters, e.g.
`get_panel_type("awrhho05b", stud_spacing=400)`.  Values a catalogue leaves open
(cladding board widths, some spacings) are such parameters.  A type's
`reference` names its source and `attributes` keep the properties the source
states (U-value, fire rating): recorded, not verified.

The dataholz types also ship as JSON files in
`timber_design_populator/panel_types/data/`, with their factories' defaults:
`load_panel_type("awrhho05b")` reads one by name, and `list_panel_type_files()`
lists them.  After changing one of those factories, regenerate the files with
`write_panel_type_files()`; a test fails while they differ.

Make your own from a layer structure and agents, and share it as JSON:

```python
from timber_design_arch.elements import LayerDefinition, LayerStructure
from timber_design_populator import BoardAgent, EdgeAgent, PanelType, PlateAgent, StudAgent
from timber_design_populator import framed_detail_sets, save_panel_type

layers = LayerStructure([
    LayerDefinition("exterior", 30, sublayer_defs=[LayerDefinition("battens", 30, material="spruce")]),
    LayerDefinition("core", 160, material="C24", attributes={"fill": "mineral wool"}),
    LayerDefinition("interior", 15, material="OSB"),
])
wall = PanelType(
    "my_wall",
    layers,
    agents=[BoardAgent("battens", board_width=50, spacing=625, category="batten"),
            EdgeAgent("core"), StudAgent("core", stud_spacing=625), PlateAgent("interior")],
    default_detail_sets=framed_detail_sets(),
    standard_beam_width=60,
)
save_panel_type(wall, "my_wall.json")
```

`stud_panel(panel, ...)` is the `stud_wall` type for the panel's own layers.
`stud_wall_type(exterior_sheeting_thickness=15, interior_sheeting_thickness=12.5)`
builds its own: sheeting of those thicknesses and a core that fills the rest
(`stud_wall_layers`), so it fits any panel.

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
wall = PanelType(
    "my_wall",
    panel.layer_structure,
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
populator = PanelPopulator(panel, wall)
```

A populator is always built from a `PanelType`: `PanelPopulator(panel, panel_type)`
(or `panel_type.populator(panel)`).  The type's `agents=` take panel-wide agents
only; a detail agent there is refused (put it in a detail set instead).  For a
variant of a type, e.g. one more agent or another beam width for one panel, use
`panel_type.derive(agents=[...], standard_beam_width=...)`.

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

1. `CT: Panel` (or another panel component) with its features.  Panels have
   no layers yet, and features do not need them.
2. A panel type: `CT: Stud Wall Panel Type` (exterior and interior sheeting
   thicknesses, stud spacing and widths), `CT: Custom Panel Type` (a layer
   structure from `CT: Panel Layer Definition` / `CT: Subdivide Layer`, the
   layer agents that build it and detail sets) or `CT: Panel Type From JSON`.
   The first two can save the type as JSON.  The dataholz.eu types ship as
   JSON: give `CT: Panel Type From JSON` their name (`awrhho05b`, ...; see
   its `available` output).
3. `CT: Create Populator` (panel, panel type) makes the populator that
   builds the panel as its type.  The panel itself goes into `CT: Model`
   without layers: `CT: Populate Model` gives it the type's layers before it
   re-runs the panel joints (layer-aware joints read them) and populates.
   For a custom stack, `CT: Layer Agent` makes the agents for
   `CT: Custom Panel Type`; `CT: Decompose LayerStructure` gives the layer
   paths.  `CT: Detail Agent Set` makes detail sets for a panel type's
   `detail_sets` or a feature component's `detail_set`.  The panel
   joint rule components offer the detail joints (`LGenericPanelJoint`,
   `TGenericPanelJoint`) with their flags as inputs.
4. `CT: Model` → `CT: Populate Model` with the populators.  `CT: Populate Model`
   gives each panel its type's layers, re-runs the panel joints, and frames
   the layers as the panel joints and connection details shaped them.
5. `CT: Filter Display` to show the result by layer.

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
:class:`~timber_design_arch.panel_features.PanelConnectionInterface` that panel's
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
`timber_design_arch` joints (`PanelLButtJoint`, `PanelTButtJoint`, `PanelMiterJoint`)
carry no detail: their layers stay as the envelope shaped them.

A new connection detail is a new joint/detail set pair: subclass a panel joint,
compute each panel's half in `add_features()` (after `super().add_features()`)
in that panel's local frame, and set it on `self.interface_a.detail_set` /
`self.interface_b.detail_set` as your own detail set.
