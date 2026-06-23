"""Grasshopper Python Script — multi-solve diagnostic.

Paste into a GH Python Script component.  Trigger the component several times
(e.g. connect a button to force re-compute).

What to look for
----------------
* Solve 1: always passes.
* Solve 2+: the bug manifests as an exception in populate_elements if Layer
  objects are being recreated each solve.

The script prints per-solve diagnostics so you can see:
  - Whether the same panel/layer Python objects are reused
  - Whether the layer is found in the model before extraction
  - Whether the error is reproducible in pure Python or only in GH

After each successful solve the solve count and element count are printed.
Any exception prints the full traceback so you can compare it against the
pytest run.
"""
import traceback

# ---------------------------------------------------------------------------
# Persistent state across GH solves
# Grasshopper Python Script reuses the module namespace between solves,
# so module-level variables survive re-computes as long as the component
# is not recompiled.
# ---------------------------------------------------------------------------
try:
    _solve_count  # already defined from a previous solve
except NameError:
    _solve_count = 0
    _panel = None

_solve_count += 1

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
from compas.geometry import Point, Polyline
from compas_timber.elements import Panel
from compas_timber.model import TimberModel
from timber_design.populators.populator_configs.stud_panel_config import stud_panel

STANDARD_BEAM_WIDTH = 60.0
STUD_SPACING = 625.0
THICKNESS = 160.0


def _make_panel():
    outline = Polyline([
        Point(0, 0, 0),
        Point(0, 2700, 0),
        Point(4000, 2700, 0),
        Point(4000, 0, 0),
        Point(0, 0, 0),
    ])
    return Panel.from_outline_thickness(outline, THICKNESS)


# ---------------------------------------------------------------------------
# Create or reuse the panel
# ---------------------------------------------------------------------------
if _panel is None:
    _panel = _make_panel()
    print("[Solve {}] Created panel id={}".format(_solve_count, id(_panel)))
else:
    print("[Solve {}] Reusing panel id={}".format(_solve_count, id(_panel)))

panel = _panel

# ---------------------------------------------------------------------------
# Diagnostics: layer state before this solve
# ---------------------------------------------------------------------------
print("  core_layer id   : {}".format(id(panel.core_layer) if panel.core_layer else "None"))
print("  core_layer.model: {}".format(
    "id={}".format(id(panel.core_layer.model)) if (panel.core_layer and panel.core_layer.model) else "None"
))
print("  core_layer.treenode: {}".format(
    "id={}".format(id(panel.core_layer.treenode)) if (panel.core_layer and panel.core_layer.treenode) else "None"
))

# ---------------------------------------------------------------------------
# Run the CT_Model workflow
# ---------------------------------------------------------------------------
try:
    model = TimberModel()
    panel.reset()
    model.add_element(panel)

    print("  After add_element:")
    print("    panel.model id : {}".format(id(panel.model)))
    print("    panel.treenode : id={}".format(id(panel.treenode)))

    # This calls define_core_layer -> should preserve existing layer object
    pop = stud_panel(panel,
                     standard_beam_width=STANDARD_BEAM_WIDTH,
                     stud_spacing=STUD_SPACING)

    core = panel.core_layer
    print("  After stud_panel (define_core_layer):")
    print("    core_layer id  : {}".format(id(core)))
    print("    core_layer.model: {}".format(
        "id={}".format(id(core.model)) if core.model else "None"
    ))
    in_model = any(e is core for e in model.elements())
    print("    core_layer in model (before merge_layer_tree): {}".format(in_model))

    # populate_elements calls merge_layer_tree then extract_model_from_parent
    pop.populate_elements()

    n = sum(1 for e in pop.model.elements()
            if hasattr(e, "attributes") and e.attributes.get("category"))
    print("  After populate_elements: {} framing elements in internal model".format(n))

    pop.join_elements()
    pop.merge_with_model(model)

    total = sum(1 for e in model.elements()
                if hasattr(e, "attributes") and e.attributes.get("category"))
    print("[Solve {}] SUCCESS: {} framing elements in final model".format(_solve_count, total))

except Exception as exc:
    print("[Solve {}] FAILED: {}".format(_solve_count, exc))
    print(traceback.format_exc())
