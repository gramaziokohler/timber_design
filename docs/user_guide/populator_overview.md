# Panels, Joints, Features and the Populator at a Glance

Four diagrams of how the pieces fit together.  For the details, see
[Populating Panels](populating_panels.md); for the full class diagrams, see
[Class Diagrams](../contribution/class_diagrams.md).

## Who owns what

A **panel** is a design element: an outline, a thickness and a stack of
**layers**, plus **panel features** that state design intent (an opening here, a
niche there).  A **panel joint** connects two panels and gives each one a
**connection interface**, which is just another feature.  How a feature is
*built* is decided by a **detail set**.  The **populator** frames one panel with
**agents**: panel-wide ones that you give it, and detail agents that the detail
sets create.

```mermaid
flowchart LR
    subgraph design["Design (timber_design_arch)"]
        Panel["Panel"]
        Layers["Layers<br/>(LayerStructure)"]
        Feature["PanelFeature<br/>Opening · MEPPenetration · Niche<br/>LinearService · PanelConnectionInterface"]
        Joint["PanelJoint<br/>(between two panels)"]
    end

    subgraph construction["Construction (timber_design_populator)"]
        Set["DetailSet<br/>how to build one feature"]
        DetailAgent["Detail agents<br/>VoidFraming · LayerCut · Service* ·<br/>LayerExtension · BackingStud"]
        WideAgent["Panel-wide agents<br/>Edge · FasciaEdge · Stud · Board · Plate · LayerBoundary"]
        Populator["PanelPopulator<br/>(one per panel)"]
        Type["PanelType<br/>a named buildup"]
        Elements["Beams & plates"]
    end

    Panel -->|has| Layers
    Panel -->|has| Feature
    Joint -->|connects 2| Panel
    Joint -->|adds an interface + its detail set to each panel| Feature
    Feature -.->|optional detail_set| Set
    Populator -->|populates| Panel
    Type -.->|"apply: layer structure"| Layers
    Type -.->|"populator(): agents + default detail sets"| Populator
    Populator -->|"default_detail_sets (per feature type)"| Set
    Populator -->|"agents="| WideAgent
    Set -->|expands into| DetailAgent
    WideAgent -->|frame / sheathe| Layers
    DetailAgent -->|cut / frame / extend| Layers
    WideAgent --> Elements
    DetailAgent --> Elements
```

## One rule: every feature is built by exactly one detail set

The feature's own `detail_set` if it has one, else the populator's default for
the feature's type.  Panel joints always set their interfaces' detail sets, so
connection details need nothing on the populator.

```mermaid
flowchart TD
    F["PanelFeature on the panel"] --> Q{"feature.detail_set<br/>set?"}
    Q -->|yes| Own["use it"]
    Q -->|no| D{"populator has a default<br/>for this feature type?"}
    D -->|yes| Def["use the default<br/>(e.g. FramedOpeningDetailSet)"]
    D -->|no| None["not built"]
    Own --> X["expand into detail agents<br/>(explicit inputs, panel-local)"]
    Def --> X
```

## From model to framing

The joint sees both panels; each populator sees only its own.  All cross-panel
calculation therefore happens in the joint, which hands each panel its half as a
ready detail set.

```mermaid
sequenceDiagram
    participant M as Model
    participant J as PanelJoint
    participant P as Panel
    participant Pop as PanelPopulator
    participant S as DetailSet
    participant A as Agents

    M->>J: process joinery
    J->>P: shape the panel envelope (extensions)
    J->>P: add an interface feature,<br/>with this panel's half as its detail set
    Pop->>P: read layers + features (own panel only)
    Pop->>S: pick one set per feature (own, else default)
    S-->>Pop: detail agents
    Pop->>A: sort all agents by priority
    Pop->>A: modify layers → generate → extend → split → cull → machine
    Pop->>A: join elements (agents' joint rules)
    Pop->>M: merge the beams and plates under the panel's layers
```

## Three ways to extend

```mermaid
flowchart LR
    Need{"What is new?"}
    Need -->|"a base behaviour<br/>(drill, place a stud, cut a layer)"| NA["new detail agent"]
    Need -->|"a way to build a feature<br/>(a new combination of agents)"| NS["new detail set"]
    Need -->|"a connection detail<br/>between two panels"| NJ["new panel joint + its detail set"]
    NS -.uses.-> NA
    NJ -.creates.-> NS
```
