"""Panel population examples.

Demonstrates the common panel framing scenarios:

1.  Basic stud wall — edge beams and studs on a single-layer panel.
2.  Sheathed stud wall with a window and a door, customising the opening agent.
3.  Custom agent stack — building a PanelPopulator directly, with sublayers,
    per-agent joint overrides and a panel-level fallback rule.

Each scenario builds its own geometry, so no external model file is required.
All lengths are in mm.
"""

from compas.geometry import Point
from compas.geometry import Polyline
from compas_timber.connections import TButtJoint
from compas_timber.elements import LayerDefinition
from compas_timber.elements import LayerStructure
from compas_timber.elements import Panel
from compas_timber.model import TimberModel
from compas_timber.panel_features import Opening
from compas_timber.panel_features import OpeningType

from compas_timber_populator import EdgePopulatorAgent
from compas_timber_populator import OpeningPopulatorAgent
from compas_timber_populator import PanelPopulator
from compas_timber_populator import PlatePopulatorAgent
from compas_timber_populator import StudPopulatorAgent
from compas_timber_populator import stud_panel
from compas_timber_rules import CategoryRule


def rectangle(x0, y0, x1, y1):
    return Polyline([Point(x0, y0, 0), Point(x1, y0, 0), Point(x1, y1, 0), Point(x0, y1, 0), Point(x0, y0, 0)])


def add_panel(model, panel):
    """Add *panel* and its layers to *model*; the populator reads the layers from the model."""
    model.add_element(panel)
    panel.merge_layer_structure(model)


def run(populator, model):
    populator.populate_elements()
    populator.join_elements()
    populator.process_joinery()
    populator.merge_with_model(model)
    return populator.debug_info


def summarize(title, model):
    categories = {}
    for element in model.elements():
        category = element.attributes.get("category")
        if category:
            categories[category] = categories.get(category, 0) + 1
    print("{}: {} joints".format(title, len(list(model.joints))))
    for category, count in sorted(categories.items()):
        print("    {:<18} {}".format(category, count))


# =============================================================================
# 1. Basic stud wall
# =============================================================================


def basic_stud_wall():
    # Without a layer_structure the panel gets a single full-thickness "core" layer.
    panel = Panel.from_outline_thickness(rectangle(0, 0, 4000, 2700), 160)
    model = TimberModel()
    add_panel(model, panel)

    populator = stud_panel(panel, standard_beam_width=60, stud_spacing=625)
    run(populator, model)
    summarize("Basic stud wall", model)
    return model


# =============================================================================
# 2. Sheathed wall with window and door
# =============================================================================


def sheathed_wall_with_openings():
    panel = Panel.from_outline_thickness(rectangle(0, 0, 5000, 2700), 200)
    panel.layer_structure = LayerStructure(
        layer_defs=[
            LayerDefinition(name="exterior", thickness=22),
            LayerDefinition(name="core"),  # thickness=None absorbs the remaining 163 mm
            LayerDefinition(name="interior", thickness=15),
        ]
    )
    panel.add_feature(Opening.from_outline_panel(rectangle(800, 900, 2000, 2200), panel, opening_type=OpeningType.WINDOW))
    panel.add_feature(Opening.from_outline_panel(rectangle(3000, 0, 4000, 2100), panel, opening_type=OpeningType.DOOR))

    model = TimberModel()
    add_panel(model, panel)

    populator = stud_panel(
        panel,
        standard_beam_width=60,
        stud_spacing=625,
        edge_stud_width=80,
        default_feature_configs={
            # One prototype serves every Opening; it becomes a Window- or
            # DoorPopulatorAgent depending on each opening's type.
            Opening: OpeningPopulatorAgent(lintel_posts=True, header_width=120, split_bottom_plate_beam=True),
        },
    )
    run(populator, model)
    summarize("Sheathed wall with openings", model)
    return model


# =============================================================================
# 3. Custom agent stack
# =============================================================================


def custom_agent_stack():
    panel = Panel.from_outline_thickness(rectangle(0, 0, 4000, 2700), 200)
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
    panel.add_feature(Opening.from_outline_panel(rectangle(1000, 900, 2200, 2200), panel, opening_type=OpeningType.WINDOW))

    model = TimberModel()
    add_panel(model, panel)

    board, _battens = panel.exterior_layer.sublayers
    agents = [
        PlatePopulatorAgent(board),
        PlatePopulatorAgent(panel.interior_layer),
        EdgePopulatorAgent(panel.core_layer, standard_beam_width_increment=20),
        StudPopulatorAgent(
            panel.core_layer,
            stud_spacing=600,
            # Replaces the default (stud, top_plate_beam) T-butt: same topology and categories.
            external_joint_overrides=[CategoryRule(TButtJoint, "stud", "top_plate_beam", mill_depth=0.0)],
        ),
    ]
    populator = PanelPopulator(
        panel,
        agents,
        standard_beam_width=60,
        default_feature_agents={
            # Frame the opening in the core; cut its outline through every layer
            # (sublayers of "exterior" included) so the sheathing gets the hole.
            Opening: OpeningPopulatorAgent(
                element_layers=[panel.core_layer],
                trimming_layers=[panel.exterior_layer, panel.core_layer, panel.interior_layer],
            ),
        },
        # Panel-level fallback, tried only when no agent rule matches a cluster.
        joint_rule_overrides=[CategoryRule(TButtJoint, "stud", "sill")],
    )
    debug_info = run(populator, model)
    summarize("Custom agent stack", model)
    print("    joining errors:", len(debug_info.joint_errors))
    return model


if __name__ == "__main__":
    basic_stud_wall()
    sheathed_wall_with_openings()
    custom_agent_stack()
