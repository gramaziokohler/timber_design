"""Panel population examples.

Demonstrates the three most common panel framing scenarios:

1.  Basic stud wall — edge beams, studs, optional sheathing.
2.  Stud wall with openings — window and door using Panel.features.
3.  Custom layer stack — direct use of LayerDefinition / PanelPopulatorConfig.

Run any section independently; all geometry is created from scratch so no
external model file is required.
"""

from compas.geometry import Point
from compas.geometry import Polyline
from compas.geometry import Vector
from compas_timber.elements import Panel
from compas_timber.model import TimberModel
from compas_timber.panel_features import Opening
from compas_timber.panel_features import OpeningType

from timber_design.populators import EdgePopulatorAgentConfig
from timber_design.populators import LayerDefinition
from timber_design.populators import OpeningPopulatorAgentConfig
from timber_design.populators import PanelPopulatorConfig
from timber_design.populators import PlatePopulatorAgentConfig
from timber_design.populators import RecessPanelPopulatorConfig
from timber_design.populators import StudPanelPopulatorConfig
from timber_design.populators import StudPopulatorAgentConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MM = 1  # model units are millimetres throughout


def make_rectangular_panel(width=5000, height=2700, thickness=160):
    """Return a flat rectangular Panel in the XY plane."""
    outline_a = Polyline([
        Point(0, 0, 0),
        Point(width, 0, 0),
        Point(width, height, 0),
        Point(0, height, 0),
        Point(0, 0, 0),
    ])
    outline_b = Polyline([
        Point(0, 0, thickness),
        Point(width, 0, thickness),
        Point(width, height, thickness),
        Point(0, height, thickness),
        Point(0, 0, thickness),
    ])
    return Panel.from_outlines(outline_a, outline_b)


# ===========================================================================
# Example 1 — Basic stud wall
# ===========================================================================

def example_basic_stud_wall():
    """Stud wall with edge beams, studs, and sheathing on both faces."""
    model = TimberModel()
    panel = make_rectangular_panel()
    model.add_element(panel)

    config = StudPanelPopulatorConfig(
        standard_beam_width=60,       # stud and plate cross-section width, mm
        stud_spacing=625,             # on-centre stud spacing, mm
        sheeting_inside=15,           # interior OSB / gypsum board, mm
        sheeting_outside=22,          # exterior structural sheathing, mm
    )

    populator = config.create_populator_from_panel(panel)
    populator.populate_elements()
    populator.join_elements()
    populator.process_joinery()
    populator.merge_with_model(model)

    print("Example 1 — Basic stud wall")
    for element in model.elements():
        print(" ", type(element).__name__, element.attributes.get("category", ""))
    return model


# ===========================================================================
# Example 2 — Stud wall with window and door openings
# ===========================================================================

def example_with_openings():
    """Stud wall with a window and a door, each automatically framed."""
    model = TimberModel()
    panel = make_rectangular_panel(width=6000, height=2700, thickness=160)
    model.add_element(panel)

    # --- Window ---------------------------------------------------------------
    win_outline = Polyline([
        Point(600, 900, 0),
        Point(2000, 900, 0),
        Point(2000, 2200, 0),
        Point(600, 2200, 0),
        Point(600, 900, 0),
    ])
    panel.add_feature(Opening.from_outline_panel(
        win_outline, panel, opening_type=OpeningType.WINDOW,
    ))

    # --- Door -----------------------------------------------------------------
    door_outline = Polyline([
        Point(3500, 0, 0),
        Point(4700, 0, 0),
        Point(4700, 2100, 0),
        Point(3500, 2100, 0),
        Point(3500, 0, 0),
    ])
    panel.add_feature(Opening.from_outline_panel(
        door_outline, panel, opening_type=OpeningType.DOOR,
    ))

    # One config applies to all Opening features via MRO lookup
    config = StudPanelPopulatorConfig(
        standard_beam_width=60,
        stud_spacing=625,
        sheeting_inside=15,
        sheeting_outside=22,
        lintel_posts=True,            # jack studs flanking headers / sills
        split_bottom_plate_beam=True, # gap in the bottom plate at the door
        default_feature_configs={
            Opening: OpeningPopulatorAgentConfig(
                lintel_posts=True,
                split_bottom_plate_beam=True,
            ),
        },
    )

    populator = config.create_populator_from_panel(panel)
    populator.populate_elements()
    populator.join_elements()
    populator.process_joinery()
    populator.merge_with_model(model)

    print("\nExample 2 — Stud wall with window and door")
    categories = {}
    for element in model.elements():
        cat = element.attributes.get("category", type(element).__name__)
        categories[cat] = categories.get(cat, 0) + 1
    for cat, count in sorted(categories.items()):
        print(f"  {cat}: {count}")
    return model


# ===========================================================================
# Example 3 — Custom layer stack with PanelPopulatorConfig
# ===========================================================================

def example_custom_layer_stack():
    """Full control over the cross-section via LayerDefinition."""
    model = TimberModel()
    # Thicker panel: interior board + structural frame + exterior cladding
    panel = make_rectangular_panel(width=4000, height=2700, thickness=220)
    model.add_element(panel)

    # Optional opening
    win_outline = Polyline([
        Point(800, 800, 0),
        Point(2200, 800, 0),
        Point(2200, 2000, 0),
        Point(800, 2000, 0),
        Point(800, 800, 0),
    ])
    panel.add_feature(Opening.from_outline_panel(
        win_outline, panel, opening_type=OpeningType.WINDOW,
    ))

    # LayerDefinitions — thickness=None on the frame claims the remainder
    layer_defs = [
        LayerDefinition(
            thickness=15,
            name="interior",
            agent_configs=[PlatePopulatorAgentConfig()],
        ),
        LayerDefinition(
            thickness=None,   # filled with whatever is left: 220 - 15 - 25 = 180 mm
            name="frame",
            is_framing_layer=True,
            agent_configs=[
                EdgePopulatorAgentConfig(
                    edge_beam_min_width=60,
                    standard_beam_width_increment=20,
                ),
                StudPopulatorAgentConfig(stud_spacing=600),
            ],
        ),
        LayerDefinition(
            thickness=25,
            name="exterior",
            agent_configs=[PlatePopulatorAgentConfig()],
        ),
    ]

    config = PanelPopulatorConfig(
        panel=panel,
        standard_beam_width=60,
        layer_defs=layer_defs,
        default_feature_configs={
            Opening: OpeningPopulatorAgentConfig(lintel_posts=True),
        },
    )

    populator = config.create_populator()
    populator.populate_elements()
    populator.join_elements()
    populator.process_joinery()
    populator.merge_with_model(model)

    print("\nExample 3 — Custom layer stack")
    categories = {}
    for element in model.elements():
        cat = element.attributes.get("category", type(element).__name__)
        categories[cat] = categories.get(cat, 0) + 1
    for cat, count in sorted(categories.items()):
        print(f"  {cat}: {count}")
    return model


# ===========================================================================
# Example 4 — Recess panel
# ===========================================================================

def example_recess_panel():
    """Recessed frame with a sheeting plate inset into the recess."""
    model = TimberModel()
    panel = make_rectangular_panel(width=3000, height=2700, thickness=120)
    model.add_element(panel)

    config = RecessPanelPopulatorConfig(
        standard_beam_width=60,
        recess_beam_width=40,     # width of the recess frame member
        recess_beam_height=80,    # height of the recess frame member
        edge_beam_min_width=60,
        sheeting_recess=18,       # thickness of the plate in the recess
        sheeting_inside=12,       # additional interior sheathing
    )

    populator = config.create_populator_from_panel(panel)
    populator.populate_elements()
    populator.join_elements()
    populator.process_joinery()
    populator.merge_with_model(model)

    print("\nExample 4 — Recess panel")
    categories = {}
    for element in model.elements():
        cat = element.attributes.get("category", type(element).__name__)
        categories[cat] = categories.get(cat, 0) + 1
    for cat, count in sorted(categories.items()):
        print(f"  {cat}: {count}")
    return model


# ===========================================================================
# Example 5 — Batch populate all panels in a model
# ===========================================================================

def example_batch_populate():
    """Apply the same config to every panel; re-populate with clear_panel=True."""
    model = TimberModel()

    # Two panels side by side
    for x_offset in [0, 6000]:
        panel = make_rectangular_panel(width=5500, height=2700, thickness=160)
        # Translate each panel in world space (simplified: just offset the outline)
        shifted_a = Polyline([pt + [x_offset, 0, 0] for pt in panel.plate_geometry.outline_a.points])
        shifted_b = Polyline([pt + [x_offset, 0, 0] for pt in panel.plate_geometry.outline_b.points])
        model.add_element(Panel.from_outlines(shifted_a, shifted_b))

    config = StudPanelPopulatorConfig(
        standard_beam_width=60,
        stud_spacing=625,
        sheeting_inside=15,
    )

    for panel in list(model.panels):
        populator = config.create_populator_from_panel(panel)
        populator.populate_elements()
        populator.join_elements()
        populator.process_joinery()
        # clear_panel=True removes any previously generated children before merging
        populator.merge_with_model(model, clear_panel=True)

    print("\nExample 5 — Batch populate")
    print(f"  Total elements: {sum(1 for _ in model.elements())}")
    return model


# ===========================================================================
# Run all examples
# ===========================================================================

if __name__ == "__main__":
    example_basic_stud_wall()
    example_with_openings()
    example_custom_layer_stack()
    example_recess_panel()
    example_batch_populate()
