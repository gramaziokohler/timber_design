"""Full-featured panel workflow tests.

Tests a stud wall with:
  - Three layers: exterior sheathing (22 mm) / core framing (156 mm) / interior sheathing (22 mm)
  - Sublayers on the exterior layer: board_layer (0-18 mm) + batten_layer (18-22 mm)
  - Window opening and door opening

Covers both single-solve correctness and multi-solve (GH re-solve) stability.
"""

import pytest

from compas.geometry import Point
from compas.geometry import Polyline
from compas_timber.elements import Layer
from compas_timber.elements import LayerDef
from compas_timber.elements import LayerStructure
from compas_timber.elements import Panel
from compas_timber.model import TimberModel

from timber_design.populators.populator_configs.stud_panel_config import stud_panel

try:
    from compas_timber.panel_features.opening import Opening
    from compas_timber.panel_features.opening import OpeningType
    from timber_design.populators import OpeningPopulatorAgent
    HAS_OPENING = True
except ImportError:
    HAS_OPENING = False

requires_opening = pytest.mark.skipif(not HAS_OPENING, reason="Opening not available")

# ---------------------------------------------------------------------------
# Dimensions
# ---------------------------------------------------------------------------
W = 4500.0
H = 2900.0
T = 200.0
SO = 22.0  # sheeting_outside (exterior face A)
SI = 22.0  # sheeting_inside  (interior face B)

STUD_WIDTH = 60.0
STUD_SPACING = 600.0


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _outline(x0, y0, x1, y1):
    return Polyline([
        Point(x0, y0, 0),
        Point(x1, y0, 0),
        Point(x1, y1, 0),
        Point(x0, y1, 0),
        Point(x0, y0, 0),
    ])


def make_panel():
    panel = Panel.from_outline_thickness(_outline(0, 0, W, H), T)
    panel.layer_structure = LayerStructure(layer_defs=[
        LayerDef(name="exterior", thickness=SO),
        LayerDef(name="core"),
        LayerDef(name="interior", thickness=SI),
    ])
    return panel


# ---------------------------------------------------------------------------
# Model helpers
# ---------------------------------------------------------------------------

def add_panel(model, panel):
    """Add *panel* to *model* together with its layer_structure's Layer children.

    ``model.add_element(panel)`` alone does not bring the panel's layers into
    the model tree, so ``panel.core_layer`` / ``exterior_layer`` /
    ``interior_layer`` resolve to ``None`` until ``merge_layer_structure`` runs.
    """
    model.add_element(panel)
    panel.merge_layer_structure(model)


# ---------------------------------------------------------------------------
# Sublayer helpers
# ---------------------------------------------------------------------------

def set_sublayers(panel):
    """Assign fresh sublayer objects to the exterior layer.

    Mirrors a GH CT_Layer component: new Python objects are created every
    solve, but exterior_layer itself is preserved (reused) since it lives in
    panel._root_layers, which is never rebuilt unless layer_structure is
    reassigned.
    """
    if not panel.exterior_layer:
        return
    board = Layer(panel, 0, 18, name="board_layer")
    batten = Layer(panel, 18, SO, name="batten_layer")
    panel.exterior_layer.sublayers = [board, batten]
    return board, batten


# ---------------------------------------------------------------------------
# Workflow helpers
# ---------------------------------------------------------------------------

def _make_pop(panel, with_openings=False):
    kwargs = dict(
        standard_beam_width=STUD_WIDTH,
        stud_spacing=STUD_SPACING,
    )
    if with_openings:
        kwargs["default_feature_configs"] = {
            Opening: OpeningPopulatorAgent(lintel_posts=True),
        }
    return stud_panel(panel, **kwargs)


def simulate_solve(panel, with_openings=False):
    """One CT_Model solve cycle, returning the merged model.

    Mirrors CT_Model.RunScript.add_elements_to_model: panel.reset() clears
    every feature (joinery-generated *and* user), so user features (openings)
    are saved and restored around the reset call.
    """
    model = TimberModel()
    saved_features = list(panel._features)
    panel.reset()
    panel._features.extend(saved_features)
    add_panel(model, panel)
    pop = _make_pop(panel, with_openings=with_openings)
    set_sublayers(panel)
    pop.populate_elements()
    pop.join_elements()
    pop.process_joinery()
    pop.merge_with_model(model)
    return model


def add_openings(panel):
    """Add a window and a door to the panel once.

    panel.reset() keeps non-joinery features, so these persist across solves.
    """
    win = Opening.from_outline_panel(
        _outline(900, 800, 2100, 2000), panel, opening_type=OpeningType.WINDOW
    )
    door = Opening.from_outline_panel(
        _outline(2800, 0, 3800, 2200), panel, opening_type=OpeningType.DOOR
    )
    panel.add_feature(win)
    panel.add_feature(door)


def cats(model):
    return {e.attributes.get("category") for e in model.elements()
            if hasattr(e, "attributes") and e.attributes.get("category")}


def by_cat(model, name):
    return [e for e in model.elements()
            if hasattr(e, "attributes") and e.attributes.get("category") == name]


# ---------------------------------------------------------------------------
# Sublayer tests
# ---------------------------------------------------------------------------


class TestSublayers:
    def test_sublayers_in_internal_model_after_populate(self):
        """After populate_elements, the internal (extracted) model must contain
        the sublayer elements so merge_with_model can move them correctly."""
        panel = make_panel()
        model = TimberModel()
        panel.reset()
        add_panel(model, panel)
        pop = stud_panel(panel, standard_beam_width=STUD_WIDTH)
        set_sublayers(panel)
        pop.populate_elements()

        layer_names = {e.name for e in pop.model.elements() if isinstance(e, Layer)}
        assert "board_layer" in layer_names
        assert "batten_layer" in layer_names

    def test_sublayers_in_merged_model(self):
        """After merge_with_model, sublayers must be present in the outer model."""
        panel = make_panel()
        model = TimberModel()
        panel.reset()
        add_panel(model, panel)
        pop = stud_panel(panel, standard_beam_width=STUD_WIDTH)
        set_sublayers(panel)
        pop.populate_elements()
        pop.join_elements()
        pop.merge_with_model(model)

        layer_names = {e.name for e in model.elements() if isinstance(e, Layer)}
        assert "board_layer" in layer_names
        assert "batten_layer" in layer_names

    def test_multi_solve_with_sublayers_does_not_raise(self):
        """Three consecutive solves with sublayers must not raise any exception."""
        panel = make_panel()
        for _ in range(3):
            simulate_solve(panel)

    def test_exterior_layer_reused_across_solves(self):
        """exterior_layer Python object must be the same instance on every solve."""
        panel = make_panel()
        simulate_solve(panel)
        ext_after_1 = panel.exterior_layer

        simulate_solve(panel)
        assert panel.exterior_layer is ext_after_1, (
            "exterior_layer was replaced with a new object on the second solve; "
            "agents holding a reference to the first-solve object will break"
        )

    def test_sublayer_objects_refreshed_each_solve(self):
        """Fresh Layer objects for sublayers are expected every solve.

        The exterior_layer identity is preserved; only the sublayer objects
        in exterior_layer.sublayers change (GH recreates them).
        """
        panel = make_panel()

        model = TimberModel()
        panel.reset()
        add_panel(model, panel)
        pop = stud_panel(panel, standard_beam_width=STUD_WIDTH)
        subs_1 = set_sublayers(panel)
        pop.populate_elements()
        pop.join_elements()
        pop.merge_with_model(model)

        ext_after_1 = panel.exterior_layer
        board_after_1 = subs_1[0]

        # Second solve — creates new sublayer objects
        model = TimberModel()
        panel.reset()
        add_panel(model, panel)
        pop = stud_panel(panel, standard_beam_width=STUD_WIDTH)
        subs_2 = set_sublayers(panel)
        pop.populate_elements()
        pop.join_elements()
        pop.merge_with_model(model)

        assert panel.exterior_layer is ext_after_1, "exterior_layer must be reused"
        assert subs_2[0] is not board_after_1, "sublayer objects expected to be new each solve"

    def test_element_count_stable_with_sublayers(self):
        """Framing count must be identical across three solves."""
        panel = make_panel()
        counts = []
        for _ in range(3):
            m = simulate_solve(panel)
            counts.append(sum(1 for e in m.elements()
                              if hasattr(e, "attributes") and e.attributes.get("category")))
        assert counts[0] == counts[1] == counts[2], (
            "Element counts differ across solves: {}".format(counts)
        )


# ---------------------------------------------------------------------------
# Full-featured workflow: three layers + sublayers + window + door
# ---------------------------------------------------------------------------


@requires_opening
class TestFullFeaturedPanel:
    @pytest.fixture(scope="class")
    def panel(self):
        p = make_panel()
        add_openings(p)
        return p

    @pytest.fixture(scope="class")
    def model(self, panel):
        return simulate_solve(panel, with_openings=True)

    def test_single_solve_does_not_raise(self, model):
        assert model is not None

    def test_header_created_for_each_opening(self, model):
        """One header per opening (window + door = 2)."""
        assert len(by_cat(model, "header")) == 2

    def test_sill_only_for_window(self, model):
        """Sill is generated for windows but not for doors."""
        assert len(by_cat(model, "sill")) == 1

    def test_king_studs_present(self, model):
        """Two king studs per opening."""
        assert len(by_cat(model, "king_stud")) == 4

    def test_jack_studs_present_when_lintel_posts(self, model):
        """lintel_posts=True must create jack studs."""
        assert len(by_cat(model, "jack_stud")) > 0

    def test_regular_studs_outside_openings(self, model):
        assert len(by_cat(model, "stud")) > 0

    def test_top_and_bottom_plates(self, model):
        assert "top_plate_beam" in cats(model)
        assert "bottom_plate_beam" in cats(model)

    def test_sublayers_in_merged_model(self, panel, model):
        layer_names = {e.name for e in model.elements() if isinstance(e, Layer)}
        assert "board_layer" in layer_names
        assert "batten_layer" in layer_names


@requires_opening
class TestFullFeaturedMultiSolve:
    """Multi-solve stability with the complete feature set."""

    def _make_panel_with_openings(self):
        p = make_panel()
        add_openings(p)
        return p

    def test_three_solves_do_not_raise(self):
        panel = self._make_panel_with_openings()
        for _ in range(3):
            simulate_solve(panel, with_openings=True)

    def test_core_layer_reused_with_openings(self):
        panel = self._make_panel_with_openings()
        simulate_solve(panel, with_openings=True)
        core_after_1 = panel.core_layer

        simulate_solve(panel, with_openings=True)
        assert panel.core_layer is core_after_1

    def test_element_count_stable_with_openings(self):
        panel = self._make_panel_with_openings()
        counts = []
        for _ in range(3):
            m = simulate_solve(panel, with_openings=True)
            counts.append(sum(1 for e in m.elements()
                              if hasattr(e, "attributes") and e.attributes.get("category")))
        assert counts[0] == counts[1] == counts[2], (
            "Element counts differ across solves: {}".format(counts)
        )

    def test_opening_features_survive_reset(self):
        """Opening features survive a CT_Model-style reset cycle (save -> reset -> restore).

        ``panel.reset()`` on its own clears every feature; CT_Model.RunScript
        preserves user features by saving them first and re-appending them
        after reset (see ``simulate_solve``).
        """
        panel = self._make_panel_with_openings()
        n_features_before = len([f for f in panel.features if isinstance(f, Opening)])
        saved_features = list(panel._features)
        panel.reset()
        panel._features.extend(saved_features)
        n_features_after = len([f for f in panel.features if isinstance(f, Opening)])
        assert n_features_before == n_features_after == 2
