# Panel Populators

The `timber_design.populators` package orchestrates the automatic framing of a
:class:`~compas_timber.elements.Panel` with structural elements (beams, plates).
It is built around three layers:

1. **PanelPopulatorConfig** — holds all configuration data and produces a
   `PanelPopulator` via
   :meth:`~timber_design.populators.PanelPopulatorConfig.create_populator`.
   The convenience factory functions `stud_panel()` and `recess_panel()` return
   a ready-made `PanelPopulatorConfig` for the two most common framing systems.
2. **LayerAgent** subclasses — each responsible for one logical group of
   elements (edge beams, studs, plates, opening surround, …).
3. **ConnectionSolver2D** — 2D blank-outline topology solver used for trimming
   and joint detection.

---

## Workflow overview

```python
from timber_design.populators.populator_configs.stud_panel_config import stud_panel

config = stud_panel(standard_beam_width=60, stud_spacing=625, panel=panel)

populator = config.create_populator()
  # ├─ resolves LayerConfig thicknesses (two-pass bottom-up / top-down)
  # ├─ layers_from_panel_and_layer_defs() → list[Layer]  (outline chaining)
  # └─ create_feature_agents()            → list[FeatureAgent]

populator.populate_elements()
  # ├─ generate_elements()      each agent creates its Beam2D / Plate objects
  # ├─ extend_elements()        agents extend beams to reach adjacent boundaries
  # ├─ trim_elements()          within-layer trim, then cross-layer trim
  # └─ add_elements_to_model()  surviving elements → internal TimberModel

populator.join_elements()
  # ├─ create_agent_joints()        within-agent joints (DirectRule)
  # └─ create_cross_agent_joints()  cross-agent joints via JointRuleSolver

populator.process_joinery()     # BTLx fabrication features applied

populator.merge_with_model(model)
  # elements transformed back to world space and attached to the source panel
```

---

## Orchestration

::: timber_design.populators.populator.PanelPopulator

---

## Layers

::: timber_design.populators.layer.LayerConfig

::: timber_design.populators.layer.Layer

---

## Populator config

::: timber_design.populators.populator_configs.panel_populator_config.PanelPopulatorConfig

## Factory functions

::: timber_design.populators.populator_configs.stud_panel_config.stud_panel

::: timber_design.populators.populator_configs.recess_panel_config.recess_panel

---

## Populator agents

::: timber_design.populators.populator_agents.layer_agent.LayerAgent

::: timber_design.populators.populator_agents.layer_agent.AgentBoundaryType

::: timber_design.populators.populator_agents.layer_agent.LayerAgentConfig

::: timber_design.populators.populator_agents.feature_agent.FeatureAgent

::: timber_design.populators.populator_agents.feature_agent.FeatureAgentConfig

::: timber_design.populators.populator_agents.edge_populator_agent.EdgePopulatorAgent

::: timber_design.populators.populator_agents.edge_populator_agent.EdgePopulatorAgentConfig

::: timber_design.populators.populator_agents.stud_populator_agent.StudPopulatorAgent

::: timber_design.populators.populator_agents.stud_populator_agent.StudPopulatorAgentConfig

::: timber_design.populators.populator_agents.plate_populator_agent.PlatePopulatorAgent

::: timber_design.populators.populator_agents.plate_populator_agent.PlatePopulatorAgentConfig

::: timber_design.populators.populator_agents.recess_populator_agent.RecessPopulatorAgent

::: timber_design.populators.populator_agents.recess_populator_agent.RecessPopulatorAgentConfig

::: timber_design.populators.populator_agents.opening_populator_agent.OpeningPopulatorAgent

::: timber_design.populators.populator_agents.opening_populator_agent.OpeningPopulatorAgentConfig

::: timber_design.populators.populator_agents.panel_boundary_populator_agent.PanelBoundaryPopulatorAgent

::: timber_design.populators.populator_agents.panel_boundary_populator_agent.PanelBoundaryPopulatorAgentConfig

---

## 2D geometry

::: timber_design.populators.beam2d.Beam2D

::: timber_design.populators.beam2d.AABB2D

---

## 2D connection solver

::: timber_design.populators.connection_solver_2d.ConnectionSolver2D

::: timber_design.populators.connection_solver_2d.aabb_overlap

::: timber_design.populators.connection_solver_2d.aabb_overlap_x

---

## Beam–outline intersection utilities

::: timber_design.populators.agent_intersection.BeamOutlineIntersectionData

::: timber_design.populators.agent_intersection.find_beam_outline_crossings

::: timber_design.populators.agent_intersection.extend_beam_to_closest_agents
