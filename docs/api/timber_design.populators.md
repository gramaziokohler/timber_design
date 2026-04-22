# Panel Populators

The `timber_design.populators` package orchestrates the automatic framing of a
:class:`~compas_timber.elements.Panel` with structural elements (beams, plates).
It is built around three layers:

1. **PanelPopulatorConfig** subclasses — combine all configuration data and
   factory behaviour into a single object.  Call
   :meth:`~timber_design.populators.PanelPopulatorConfig.create_populator_from_panel`
   to get a fully-configured populator for a given panel.
2. **LayerAgent** subclasses — each responsible for one logical group of
   elements (edge beams, studs, plates, opening surround, …).
3. **ConnectionSolver2D** — 2D blank-outline topology solver used for trimming
   and joint detection.

---

## Workflow overview

```
config = StudPanelPopulatorConfig(standard_beam_width=60, stud_spacing=625)

populator = config.create_populator_from_panel(panel)
  ├─ PanelPopulatorConfig._prepare_panels()        → dict[str, Layer]
  │     "local"    – full panel in populator space
  │     "frame"    – structural frame (sheeting removed)
  │     "interior" – inside sheathing layer  (if sheeting_inside > 0)
  │     "exterior" – outside sheathing layer (if sheeting_outside > 0)
  └─ PanelPopulatorConfig.create_populator_agents(layers) → list[LayerAgent]

PanelPopulator.populate_elements()
  ├─ generate_elements()   each agent creates its Beam2D / Plate objects
  ├─ extend_elements()     agents extend beams to reach adjacent boundaries
  ├─ trim_elements()       beams split at agent boundaries; out-of-zone
  │                        segments discarded (INCLUSIVE / EXCLUSIVE)
  └─ add_elements_to_model()   surviving elements → internal TimberModel

PanelPopulator.join_elements()
  ├─ create_agent_joints()       within-agent joints
  └─ create_cross_agent_joints() cross-agent joints via JointRuleSolver

PanelPopulator.process_joinery()    BTLx fabrication features applied

PanelPopulator.merge_with_model()   elements transformed back to world space
                                    and attached to the source panel
```

---

## Orchestration

::: timber_design.populators.populator.PanelPopulator

---

## Layers

::: timber_design.populators.layer.Layer

---

## Populator configs

::: timber_design.populators.populator_configs.panel_populator_config.PanelPopulatorConfig

::: timber_design.populators.populator_configs.stud_panel_populator_config.StudPanelPopulatorConfig

::: timber_design.populators.populator_configs.recess_panel_populator_config.RecessPanelPopulatorConfig

---

## Populator agents

::: timber_design.populators.populator_agents.layer_agent.LayerAgent

::: timber_design.populators.populator_agents.layer_agent.FeatureBoundaryType

::: timber_design.populators.populator_agents.layer_agent.LayerAgentConfig

::: timber_design.populators.populator_agents.edge_populator_agent.EdgePopulatorAgent

::: timber_design.populators.populator_agents.edge_populator_agent.EdgePopulatorAgentConfig

::: timber_design.populators.populator_agents.stud_populator_agent.StudPopulatorAgent

::: timber_design.populators.populator_agents.stud_populator_agent.StudPopulatorAgentConfig

::: timber_design.populators.populator_agents.opening_populator_agent.OpeningPopulatorAgent

::: timber_design.populators.populator_agents.opening_populator_agent.OpeningPopulatorAgentConfig

::: timber_design.populators.populator_agents.plate_populator_agent.PlatePopulatorAgent

::: timber_design.populators.populator_agents.plate_populator_agent.PlatePopulatorAgentConfig

::: timber_design.populators.populator_agents.recess_populator_agent.RecessPopulatorAgent

::: timber_design.populators.populator_agents.recess_populator_agent.RecessPopulatorAgentConfig

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
