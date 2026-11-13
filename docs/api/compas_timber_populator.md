# Panel Populators

The `compas_timber_populator` package frames a
:class:`~compas_timber.elements.Panel` with beams and plates.  See the
[Populating Panels](../user_guide/populating_panels.md) guide for the workflow.

```python
from compas_timber_populator import stud_panel

populator = stud_panel(panel, standard_beam_width=60, stud_spacing=625)
populator.populate_elements()   # generate -> define outlines -> extend -> split -> cull
populator.join_elements()       # agent rules, then panel-level fallback rules
populator.process_joinery()     # fabrication features for the joints
populator.merge_with_model(model)
```

---

## Orchestration

::: compas_timber_populator.populator.PanelPopulator

## Factory functions

::: compas_timber_populator.stud_panel

---

## Agent base classes

::: compas_timber_populator.populator_agents.populator_agent.PopulatorAgent

::: compas_timber_populator.populator_agents.populator_agent.AgentBoundaryType

::: compas_timber_populator.populator_agents.layer_agent.LayerAgent

::: compas_timber_populator.populator_agents.feature_agent.FeatureAgent

## Layer agents

::: compas_timber_populator.populator_agents.edge_populator_agent.EdgePopulatorAgent

::: compas_timber_populator.populator_agents.stud_populator_agent.StudPopulatorAgent

::: compas_timber_populator.populator_agents.plate_populator_agent.PlatePopulatorAgent

::: compas_timber_populator.populator_agents.panel_boundary_populator_agent.PanelBoundaryPopulatorAgent

## Feature agents

::: compas_timber_populator.populator_agents.opening_populator_agent.OpeningPopulatorAgent

::: compas_timber_populator.populator_agents.opening_populator_agent.WindowPopulatorAgent

::: compas_timber_populator.populator_agents.opening_populator_agent.DoorPopulatorAgent

---

## 2D geometry and connection solving

The populator works on :class:`~compas_timber_populator.connections_2d.beam2d.Beam2D`s and
finds joint candidates with the 2D solver; see
[2D Connection Solving](../connections_2d.md).

::: compas_timber_populator.connections_2d.beam2d.Beam2D

::: compas_timber_populator.connections_2d.beam2d.AABB2D

::: compas_timber_populator.connections_2d.connection_solver_2d.ConnectionSolver2D

::: compas_timber_populator.connections_2d.connection_solver_2d.Cluster2DFinder
