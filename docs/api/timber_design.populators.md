# Panel Populators

The `timber_design.populators` package frames a
:class:`~compas_timber.elements.Panel` with beams and plates.  See the
[Populating Panels](../user_guide/populating_panels.md) guide for the workflow.

```python
from timber_design.populators import stud_panel

populator = stud_panel(panel, standard_beam_width=60, stud_spacing=625)
populator.populate_elements()   # generate -> define outlines -> extend -> split -> cull
populator.join_elements()       # agent rules, then panel-level fallback rules
populator.process_joinery()     # fabrication features for the joints
populator.merge_with_model(model)
```

---

## Orchestration

::: timber_design.populators.populator.PanelPopulator

## Factory functions

::: timber_design.populators.stud_panel

---

## Agent base classes

::: timber_design.populators.populator_agents.populator_agent.PopulatorAgent

::: timber_design.populators.populator_agents.populator_agent.AgentBoundaryType

::: timber_design.populators.populator_agents.layer_agent.LayerAgent

::: timber_design.populators.populator_agents.feature_agent.FeatureAgent

## Layer agents

::: timber_design.populators.populator_agents.edge_populator_agent.EdgePopulatorAgent

::: timber_design.populators.populator_agents.stud_populator_agent.StudPopulatorAgent

::: timber_design.populators.populator_agents.plate_populator_agent.PlatePopulatorAgent

::: timber_design.populators.populator_agents.panel_boundary_populator_agent.PanelBoundaryPopulatorAgent

## Feature agents

::: timber_design.populators.populator_agents.opening_populator_agent.OpeningPopulatorAgent

::: timber_design.populators.populator_agents.opening_populator_agent.WindowPopulatorAgent

::: timber_design.populators.populator_agents.opening_populator_agent.DoorPopulatorAgent

---

## 2D geometry and connection solving

The populator works on :class:`~timber_design.connections_2d.beam2d.Beam2D`s and
finds joint candidates with the 2D solver; see
[2D Connection Solving](../connections_2d.md).

::: timber_design.connections_2d.beam2d.Beam2D

::: timber_design.connections_2d.beam2d.AABB2D

::: timber_design.connections_2d.connection_solver_2d.ConnectionSolver2D

::: timber_design.connections_2d.connection_solver_2d.Cluster2DFinder
