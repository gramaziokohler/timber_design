"""Tests for detail sets: what they expand into, their parameters, and custom sets."""

from compas.data import json_dumps
from compas.data import json_loads
from compas.geometry import Point
from compas.geometry import Polyline
from compas_timber.elements import Plate
from compas_timber.fabrication import FreeContour

from compas_arch.elements import LayerDefinition
from compas_arch.elements import LayerRole
from compas_arch.elements import LayerStructure
from compas_arch.elements import Panel
from compas_arch.model import ArchModel
from compas_arch.panel_features import Opening
from compas_arch.panel_features import OpeningType

from timber_design_populator import EdgeAgent
from timber_design_populator import LayerCutDetailAgent
from timber_design_populator import PanelPopulator
from timber_design_populator import PlateAgent
from timber_design_populator import VoidFramingDetailAgent
from timber_design_populator.detail_sets import DetailAgentSet
from timber_design_populator.detail_sets import FramedOpeningDetailSet


def _outline(xmin, ymin, xmax, ymax, z=0.0):
    return Polyline([Point(xmin, ymin, z), Point(xmax, ymin, z), Point(xmax, ymax, z), Point(xmin, ymax, z), Point(xmin, ymin, z)])


def _panel(structure=True):
    panel = Panel.from_outline_thickness(_outline(0, 0, 4000, 2700), 200.0)
    if structure:
        panel.layer_structure = LayerStructure([LayerDefinition("exterior", 20.0), LayerDefinition("core"), LayerDefinition("interior", 20.0)])
    return panel


def _populated(detail_set, opening_type=OpeningType.WINDOW, structure=True):
    panel = _panel(structure)
    outline = _outline(1000, 900, 2200, 2100) if opening_type == OpeningType.WINDOW else _outline(1600, 0, 2500, 2200)
    opening = Opening.from_outline_panel(outline, panel, opening_type=opening_type, detail_set=detail_set)
    panel.add_feature(opening)
    model = ArchModel()
    model.add_element(panel)
    panel.merge_layer_structure(model)
    agents = [EdgeAgent(panel.core_layer)]
    for role in ("exterior", "interior"):
        layer = panel.layer_for_role(role)
        if layer is not None:
            agents.append(PlateAgent(layer))
    pop = PanelPopulator(panel, agents=agents, standard_beam_width=60.0)
    pop.populate_elements()
    return pop, opening


def _set_agents(pop, feature):
    return [a for a in pop.agents if getattr(a, "feature", None) is feature]


def _width(outline):
    xs = [p.x for p in outline.points]
    return round(max(xs) - min(xs), 6)


def _cut_widths(plate):
    """Widths of the interior FreeContour cuts in *plate* (not its own outer contour), from their contour polylines."""
    widths = []
    for feature in plate.features:
        if isinstance(feature, FreeContour) and feature.counter_sink:
            points = feature.contour_param_object.polyline.points
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            widths.append(round(max(max(xs) - min(xs), max(ys) - min(ys)), 3))
    return widths


# =============================================================================
# what the opening set expands into
# =============================================================================


def test_opening_set_expands_into_framing_and_one_cut_per_role_layer():
    pop, opening = _populated(FramedOpeningDetailSet())
    framing, *cutting = _set_agents(pop, opening)
    structure = pop.panel.layer_structure
    core = structure.get_path_for_role("core")

    assert type(framing) is VoidFramingDetailAgent and all(type(c) is LayerCutDetailAgent for c in cutting)
    assert framing.element_layer_paths == [core] and framing.trimming_layer_paths == [core]
    assert framing.sill and framing.bottom_offset == 0 and framing.boundary is not None
    assert all(c.element_layer_paths == [] for c in cutting)
    assert [c.trimming_layer_paths for c in cutting] == [[d.layer_path] for d in structure.layer_defs]
    for c in cutting:
        layer = pop.layer_tree[c.trimming_layer_paths[0]]
        if c.trimming_layer_paths == [core]:
            assert not c.cut_beams and c.outline_for_layer(layer) is None  # the framing bounds the core itself
        else:
            assert c.cut_beams and c.outline_for_layer(layer) is not None


def test_door_framing_has_no_sill_and_only_doors_split_the_bottom_plate():
    pop, door = _populated(FramedOpeningDetailSet(split_bottom_plate_beam=True), OpeningType.DOOR)
    framing, *_ = _set_agents(pop, door)
    assert not framing.sill and framing.bottom_offset > 0 and framing.split_bottom_plate_beam

    pop, window = _populated(FramedOpeningDetailSet(split_bottom_plate_beam=True))
    framing, *_ = _set_agents(pop, window)
    assert framing.sill and not framing.split_bottom_plate_beam


def test_widths_are_passed_to_the_framing():
    pop, opening = _populated(FramedOpeningDetailSet(header_width=120.0, king_stud_width=80.0))
    framing, *_ = _set_agents(pop, opening)
    assert framing.beam_widths["header"] == 120.0 and framing.beam_widths["king_stud"] == 80.0
    assert framing.beam_widths["sill"] == 60.0  # unset: the populator's standard width


# =============================================================================
# cut_offsets: a layer cut beyond the opening outline
# =============================================================================


def test_cut_offsets_grow_only_that_layers_cut():
    plain_pop, plain = _populated(FramedOpeningDetailSet())
    grown_pop, grown = _populated(FramedOpeningDetailSet(cut_offsets={"exterior": 20.0}))
    plain_framing, *plain_cutting = _set_agents(plain_pop, plain)
    grown_framing, *grown_cutting = _set_agents(grown_pop, grown)
    structure = plain_pop.panel.layer_structure

    def cut(pop, cutting, role):
        path = structure.get_path_for_role(role)
        agent = [c for c in cutting if c.trimming_layer_paths == [path]][0]
        return agent, agent.outline_for_layer(pop.layer_tree[path])

    (grown_ext, grown_boundary), (plain_ext, plain_boundary) = cut(grown_pop, grown_cutting, "exterior"), cut(plain_pop, plain_cutting, "exterior")
    assert _width(grown_ext.outline_a) == _width(plain_ext.outline_a) + 40
    assert _width(grown_boundary) == _width(plain_boundary) + 40
    assert _width(cut(grown_pop, grown_cutting, "interior")[0].outline_a) == _width(cut(plain_pop, plain_cutting, "interior")[0].outline_a)
    assert _width(grown_framing.boundary) == _width(plain_framing.boundary)  # the framing does not move


# =============================================================================
# a custom set: coordination the feature knows nothing about
# =============================================================================


class CladdingBeyondOpening(DetailAgentSet):
    """Frames the opening like the built-in set, but cuts the exterior layer 50 larger on every side."""

    FEATURE_TYPES = (Opening,)

    def expand(self, feature, panel, layer_tree, standard_beam_width=None):
        agents, errors = FramedOpeningDetailSet().expand(feature, panel, layer_tree, standard_beam_width)
        exterior = self.root_layer(layer_tree, LayerRole.EXTERIOR)
        xs = [p.x for p in feature.outline_a.points]
        ys = [p.y for p in feature.outline_a.points]
        z = exterior.planes[0].point.z
        bigger = _outline(min(xs) - 50, min(ys) - 50, max(xs) + 50, max(ys) + 50, z)
        # keep every agent of the built-in set, except the exterior cut, which is replaced
        kept = [a for a in agents if a.trimming_layer_paths != [exterior.layer_path] or not isinstance(a, LayerCutDetailAgent)]
        return kept + [LayerCutDetailAgent(exterior.layer_path, outline_a=bigger, feature=feature)], errors


def test_a_custom_set_cuts_a_layer_elsewhere_than_the_feature_outline():
    pop, opening = _populated(CladdingBeyondOpening())
    plates = {plate.parent.name: plate for plate in pop.model.find_all_elements_of_type(Plate)}
    assert _cut_widths(plates["exterior"]) == [1200 + 100]  # the opening is 1200 wide
    assert _cut_widths(plates["interior"]) == [1200]


# =============================================================================
# errors, serialization, repeated runs
# =============================================================================


def test_a_panel_without_a_core_is_reported():
    panel = _panel()
    panel.layer_structure = LayerStructure([LayerDefinition("exterior", 20.0), LayerDefinition("interior")])
    model = ArchModel()
    model.add_element(panel)
    panel.merge_layer_structure(model)
    panel.add_feature(Opening.from_outline_panel(_outline(1000, 900, 2200, 2100), panel, detail_set=FramedOpeningDetailSet()))
    pop = PanelPopulator(panel, agents=[], standard_beam_width=60.0)
    pop.populate_elements()
    assert any("no core layer" in e.message for e in pop.debug_info.feature_errors)


def test_sets_round_trip_and_clone():
    detail_set = FramedOpeningDetailSet(lintel_posts=True, header_width=120.0, cut_offsets={"exterior": 20.0})
    for copy in (json_loads(json_dumps(detail_set)), detail_set.clone()):
        assert type(copy) is FramedOpeningDetailSet and copy is not detail_set
        assert copy.__data__ == detail_set.__data__


def test_expanded_agents_are_rebuilt_on_every_run():
    pop, opening = _populated(FramedOpeningDetailSet())
    first = _set_agents(pop, opening)
    model = pop.panel.model
    pop.merge_with_model(model)  # as between Grasshopper solves
    pop.populate_elements()
    second = _set_agents(pop, opening)
    assert len(second) == 4 and not any(a in first for a in second)  # framing + a cut per role layer


def test_sets_are_expanded_only_when_populating():
    panel = _panel()
    opening = Opening.from_outline_panel(_outline(1000, 900, 2200, 2100), panel, detail_set=FramedOpeningDetailSet())
    panel.add_feature(opening)
    model = ArchModel()
    model.add_element(panel)
    panel.merge_layer_structure(model)
    pop = PanelPopulator(panel, agents=[], standard_beam_width=60.0)
    assert _set_agents(pop, opening) == []
    pop.populate_elements()
    assert len(_set_agents(pop, opening)) == 4  # framing + a cut per role layer


def test_grasshopper_defaults_are_keyed_by_the_feature_types_they_build():
    from compas_arch.panel_features import Niche
    from timber_design_gh.ghcomponent_helpers import feature_defaults_by_type
    from timber_design_populator.detail_sets import FramedNicheDetailSet

    opening_set, niche_set = FramedOpeningDetailSet(), FramedNicheDetailSet()
    defaults = feature_defaults_by_type([opening_set, niche_set, None])
    assert defaults == {Opening: opening_set, Niche: niche_set}
    assert feature_defaults_by_type([]) is None


def test_panels_with_pathless_sublayers_are_still_cut():
    """Sublayers assigned directly (as Grasshopper does) have no layer path.  Agents find layers by path,
    so nothing is built on those sublayers; the sets must skip them and still cut the layers above."""
    from compas_arch.elements import Layer
    from timber_design_populator import stud_panel

    panel = _panel()
    model = ArchModel()
    model.add_element(panel)
    panel.merge_layer_structure(model)
    exterior = panel.exterior_layer
    board = Layer.from_parent_start_end(exterior, 0.0, 10.0, name="board")
    battens = Layer.from_parent_start_end(exterior, 10.0, 20.0, name="battens")
    exterior.sublayers = [board, battens]
    assert board.layer_path is None
    panel.add_feature(Opening.from_outline_panel(_outline(1000, 900, 2200, 2100), panel))
    pop = stud_panel(panel, standard_beam_width=60.0, stud_spacing=625.0)
    pop.populate_elements()

    exterior_plates = [plate for plate in pop.model.find_all_elements_of_type(Plate) if plate.parent.name in ("exterior", "board", "battens")]
    assert exterior_plates
    assert all(_cut_widths(plate) == [1200] for plate in exterior_plates), [(p.parent.name, _cut_widths(p)) for p in exterior_plates]
    assert pop.debug_info.feature_errors == []
