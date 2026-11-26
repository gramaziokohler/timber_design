# Panel Populators

The `timber_design_populator` package frames a
:class:`~timber_design_arch.elements.Panel` with beams and plates.  See the
[Populating Panels](../user_guide/populating_panels.md) guide for the workflow.

```python
from timber_design_populator import stud_panel

populator = stud_panel(panel, standard_beam_width=60, stud_spacing=625)
populator.populate_elements()   # expand detail sets -> modify layers -> generate -> extend -> split -> cull -> machine
populator.join_elements()       # agent rules, then panel-level fallback rules
populator.process_joinery()     # fabrication features for the joints
populator.merge_with_model(model)
```

---

## Orchestration

::: timber_design_populator.populator.PanelPopulator

## Factory functions

::: timber_design_populator.stud_panel

## Panel types

::: timber_design_populator.panel_types.PanelType

::: timber_design_populator.panel_types.get_panel_type

::: timber_design_populator.panel_types.list_panel_types

::: timber_design_populator.panel_types.load_panel_type

::: timber_design_populator.panel_types.list_panel_type_files

::: timber_design_populator.panel_types.write_panel_type_files

::: timber_design_populator.panel_types.save_panel_type

::: timber_design_populator.panel_types.stud_wall_type

::: timber_design_populator.panel_types.stud_wall_layers

::: timber_design_populator.panel_types.framed_detail_sets

::: timber_design_populator.panel_types.dataholz

---

## Agent base class

::: timber_design_populator.populator_agents.populator_agent.PopulatorAgent

::: timber_design_populator.populator_agents.populator_agent.AgentBoundaryType

## Panel-wide agents

::: timber_design_populator.populator_agents.edge_agent.EdgeAgent

::: timber_design_populator.populator_agents.fascia_edge_agent.FasciaEdgeAgent

::: timber_design_populator.populator_agents.board_agent.BoardAgent

::: timber_design_populator.populator_agents.stud_agent.StudAgent

::: timber_design_populator.populator_agents.plate_agent.PlateAgent

::: timber_design_populator.populator_agents.layer_boundary_agent.LayerBoundaryAgent

## Detail sets

Each built-in set is one way to build a feature, not the only one.

::: timber_design_populator.detail_sets.DetailAgentSet

::: timber_design_populator.detail_sets.FramedOpeningDetailSet

::: timber_design_populator.detail_sets.FramedPenetrationDetailSet

::: timber_design_populator.detail_sets.FramedNicheDetailSet

::: timber_design_populator.detail_sets.LinearServiceDetailSet

::: timber_design_populator.detail_sets.CutThroughDetailSet

## Detail agents

::: timber_design_populator.populator_agents.void_framing_detail_agent.VoidFramingDetailAgent

::: timber_design_populator.populator_agents.layer_cut_detail_agent.LayerCutDetailAgent

::: timber_design_populator.populator_agents.service_drilling_detail_agent.ServiceDrillingDetailAgent

::: timber_design_populator.populator_agents.service_notch_detail_agent.ServiceNotchDetailAgent

::: timber_design_populator.populator_agents.layer_extension_detail_agent.LayerExtensionDetailAgent

::: timber_design_populator.populator_agents.backing_stud_detail_agent.BackingStudDetailAgent

## Connection details

A panel joint and its detail set form a pair: the joint computes each panel's half, the set
expands it in that panel's populator.

::: timber_design_populator.panel_joints.LGenericPanelJoint

::: timber_design_populator.panel_joints.TGenericPanelJoint

::: timber_design_populator.detail_sets.PanelJointDetailSet

::: timber_design_populator.detail_sets.LGenericPanelJointDetailSet

::: timber_design_populator.detail_sets.TGenericPanelJointDetailSet

---

## 2D geometry and connection solving

The populator works on :class:`~timber_design_populator.connections_2d.beam2d.Beam2D`s and
finds joint candidates with the 2D solver; see
[2D Connection Solving](../connections_2d.md).

::: timber_design_populator.connections_2d.beam2d.Beam2D

::: timber_design_populator.connections_2d.fascia_beam.FasciaBeam

::: timber_design_populator.connections_2d.beam2d.AABB2D

::: timber_design_populator.connections_2d.connection_solver_2d.ConnectionSolver2D

::: timber_design_populator.connections_2d.connection_solver_2d.Cluster2DFinder
