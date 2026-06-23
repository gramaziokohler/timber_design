"""Grasshopper Python Script — full-featured stud wall with sublayers and openings.

Panel layout (200 mm total thickness):
  [face A / outside]
  0 – 22 mm   exterior_layer (OSB sheathing)
               └── 0–18 mm   board_layer  (sublayer)
               └── 18–22 mm  batten_layer (sublayer)
  22 – 178 mm  core_layer (stud framing, 156 mm)
  178 – 200 mm interior_layer (gypsum board, 22 mm)
  [face B / inside]

Openings:
  - Window : x 900–2100, y 800–2000  (1200 × 1200 mm)
  - Door   : x 2800–3800, y 0–2200   (1000 × 2200 mm, floor-to-header)

Diagnostic output per solve:
  - Python id() of panel, core_layer, exterior_layer
  - Whether layers are new or reused objects
  - Sublayer object ids (new each solve — that is expected)
  - Element counts in the final model

Paste the entire file into a GH Python Script component.
Trigger several re-solves (e.g. via a button) and watch the printed output.
"""

import traceback

# ---------------------------------------------------------------------------
# Persistent state — survives between GH solves as long as the component is
# not recompiled.  The try/except pattern avoids a NameError on first solve.
# ---------------------------------------------------------------------------
try:
    _solve_count
except NameError:
    _solve_count = 0
    _panel = None
    _prev_core_id = None
    _prev_exterior_id = None

_solve_count += 1

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
from compas.geometry import Point
from compas.geometry import Polyline
from compas_timber.elements import Layer
from compas_timber.elements import Panel
from compas_timber.model import TimberModel
from compas_timber.panel_features.opening import Opening
from compas_timber.panel_features.opening import OpeningType

from timber_design.populators import OpeningPopulatorAgent
from timber_design.populators.populator_configs.stud_panel_config import stud_panel

# ---------------------------------------------------------------------------
# Panel / layer dimensions
# ---------------------------------------------------------------------------
PANEL_WIDTH = 4500.0
PANEL_HEIGHT = 2900.0
PANEL_THICKNESS = 200.0
SHEETING_OUTSIDE = 22.0   # exterior face A
SHEETING_INSIDE = 22.0    # interior face B
BOARD_SUBLAYER_END = 18.0 # within exterior_layer (0 – SHEETING_OUTSIDE)

STUD_WIDTH = 60.0
STUD_SPACING = 600.0


def _make_outline(x0, y0, x1, y1):
    return Polyline([
        Point(x0, y0, 0),
        Point(x0, y1, 0),
        Point(x1, y1, 0),
        Point(x1, y0, 0),
        Point(x0, y0, 0),
    ])


# ---------------------------------------------------------------------------
# Create or reuse the panel
# ---------------------------------------------------------------------------
if _panel is None:
    _panel = Panel.from_outline_thickness(
        _make_outline(0, 0, PANEL_WIDTH, PANEL_HEIGHT),
        PANEL_THICKNESS,
    )
    print("[Solve {}] Created new panel  id={}".format(_solve_count, id(_panel)))

    # Openings are non-joinery features: they survive panel.reset() and only
    # need to be added once.
    _win_outline = _make_outline(900, 800, 2100, 2000)
    _door_outline = _make_outline(2800, 0, 3800, 2200)
    window = Opening.from_outline_panel(_win_outline, _panel, opening_type=OpeningType.WINDOW)
    door = Opening.from_outline_panel(_door_outline, _panel, opening_type=OpeningType.DOOR)
    _panel.add_feature(window)
    _panel.add_feature(door)
    print("[Solve {}] Added window + door features".format(_solve_count))
else:
    print("[Solve {}] Reusing panel       id={}".format(_solve_count, id(_panel)))

panel = _panel


# ---------------------------------------------------------------------------
# Diagnostics: layer state BEFORE this solve's define_core_layer runs
# ---------------------------------------------------------------------------
def _fmt_id(obj, label, prev_id):
    if obj is None:
        return "  {:20s}: None".format(label)
    status = "NEW" if (prev_id is None or id(obj) != prev_id) else "REUSED"
    return "  {:20s}: id={:<18d} [{}]".format(label, id(obj), status)


print(_fmt_id(panel.core_layer, "core_layer (before)", _prev_core_id))
print(_fmt_id(panel.exterior_layer, "exterior_layer (before)", _prev_exterior_id))


# ---------------------------------------------------------------------------
# Run the workflow
# ---------------------------------------------------------------------------
try:
    # --- Step 1: Fresh model + reset panel (mirrors CT_Model.add_elements_to_model) ---
    model = TimberModel()
    panel.reset()
    model.add_element(panel)

    # --- Step 2: Create populator (calls define_core_layer internally) ---
    #             With our fix, core_layer/exterior_layer are REUSED when
    #             dimensions are unchanged.
    pop = stud_panel(
        panel,
        standard_beam_width=STUD_WIDTH,
        stud_spacing=STUD_SPACING,
        sheeting_outside=SHEETING_OUTSIDE,
        sheeting_inside=SHEETING_INSIDE,
        default_feature_configs={
            Opening: OpeningPopulatorAgent(lintel_posts=True),
        },
    )

    print(_fmt_id(panel.core_layer, "core_layer (after)", _prev_core_id))
    print(_fmt_id(panel.exterior_layer, "exterior_layer (after)", _prev_exterior_id))

    # --- Step 3: Sublayers on exterior_layer ---
    #             Simulates a separate GH CT_Layer component that runs BEFORE
    #             CT_Model.  New Layer objects are created each solve; the
    #             exterior_layer they attach to is preserved (reused).
    if panel.exterior_layer:
        board = Layer(panel, 0, BOARD_SUBLAYER_END, name="board_layer")
        batten = Layer(panel, BOARD_SUBLAYER_END, SHEETING_OUTSIDE, name="batten_layer")
        panel.exterior_layer.sublayers = [board, batten]
        print("  sublayers (new each solve):")
        print("    board_layer  id={}".format(id(board)))
        print("    batten_layer id={}".format(id(batten)))
    else:
        print("  exterior_layer is None — no sublayers added")

    # --- Step 4: populate / join / merge (mirrors CT_Model.handle_populators) ---
    pop.populate_elements()

    n_internal = sum(
        1 for e in pop.model.elements()
        if hasattr(e, "attributes") and e.attributes.get("category")
    )
    print("  Internal model framing elements: {}".format(n_internal))

    # Check sublayers are in the internal (extracted) model
    from compas_timber.elements import Layer as _Layer
    internal_layers = [e for e in pop.model.elements() if isinstance(e, _Layer)]
    print("  Internal model layers: {}".format([e.name for e in internal_layers]))

    pop.join_elements()
    pop.process_joinery()
    pop.merge_with_model(model)

    # --- Step 5: Report final state ---
    by_cat = {}
    for e in model.elements():
        if hasattr(e, "attributes"):
            cat = e.attributes.get("category")
            if cat:
                by_cat[cat] = by_cat.get(cat, 0) + 1

    print("[Solve {}] SUCCESS  categories: {}".format(_solve_count, dict(sorted(by_cat.items()))))

    _prev_core_id = id(panel.core_layer)
    _prev_exterior_id = id(panel.exterior_layer)

except Exception as exc:
    print("[Solve {}] FAILED: {}".format(_solve_count, exc))
    print(traceback.format_exc())

# ---------------------------------------------------------------------------
# GH outputs
# ---------------------------------------------------------------------------
Model = model if "model" in dir() else None
