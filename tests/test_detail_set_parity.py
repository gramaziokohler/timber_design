"""Parity of the detail sets with the opening / MEP / niche agents they replaced.

The expectations in ``data/detail_set_parity.json`` were recorded with the replaced agents
(``OpeningPopulatorAgent``, ``DoorPopulatorAgent``, ``WindowPopulatorAgent``,
``MEPPenetrationPopulatorAgent``, ``NichePopulatorAgent``) before they were removed.  Each case
populates one wall with one feature and fingerprints the result: every beam (category, layer,
centreline, width, features), every plate's cuts, and every joint.  The detail sets must
reproduce them.

The wall has a two-part exterior layer (cladding plates on the outside, battens behind them),
a core with edge beams and studs, and an interior lining, so a void has to cut beams as well
as plates.
"""

import json
import os

import pytest

from compas.data import json_dumps
from compas.geometry import Frame
from compas.geometry import Point
from compas.geometry import Polyline
from compas_timber.elements import Beam
from compas_timber.elements import Plate

from timber_design_arch.elements import LayerDefinition
from timber_design_arch.elements import LayerRole
from timber_design_arch.elements import LayerStructure
from timber_design_arch.elements import Panel
from timber_design_arch.model import ArchModel
from timber_design_arch.panel_features import MEPPenetration
from timber_design_arch.panel_features import Niche
from timber_design_arch.panel_features import Opening
from timber_design_arch.panel_features import OpeningType

from timber_design_populator import EdgeAgent
from timber_design_populator import PanelPopulator
from timber_design_populator import PanelType
from timber_design_populator import PlateAgent
from timber_design_populator import StudAgent

GOLDEN = os.path.join(os.path.dirname(__file__), "data", "detail_set_parity.json")
TOLERANCE = 0.11  # values are rounded to 0.1


# =============================================================================
# the wall
# =============================================================================


def _outline(xmin, ymin, xmax, ymax, z=0.0):
    return Polyline([Point(xmin, ymin, z), Point(xmax, ymin, z), Point(xmax, ymax, z), Point(xmin, ymax, z), Point(xmin, ymin, z)])


def make_panel():
    panel = Panel.from_outline_thickness(_outline(0, 0, 4000, 2700), 200.0)
    panel.layer_structure = LayerStructure(
        [
            LayerDefinition("exterior", 40.0, sublayer_defs=[LayerDefinition("cladding", 15.0), LayerDefinition("battens", 25.0)]),
            LayerDefinition("core"),
            LayerDefinition("interior", 20.0),
        ]
    )
    return panel


def make_agents(panel):
    structure = panel.layer_structure
    return [
        PlateAgent(structure.get_path_for_name("cladding")),
        StudAgent(structure.get_path_for_name("battens"), stud_spacing=400.0),
        EdgeAgent(structure.get_path_for_name("core")),
        StudAgent(structure.get_path_for_name("core"), stud_spacing=625.0),
        PlateAgent(structure.get_path_for_name("interior")),
    ]


# =============================================================================
# the features
# =============================================================================


def window(panel):
    return Opening.from_outline_panel(_outline(1000, 900, 2200, 2100), panel, opening_type=OpeningType.WINDOW)


def door(panel):
    return Opening.from_outline_panel(_outline(1600, 0, 2500, 2200), panel, opening_type=OpeningType.DOOR)


def mep(panel):
    return MEPPenetration(Frame.worldXY(), _outline(1500, 1000, 1900, 1300, 200), _outline(1450, 950, 1950, 1350, 100), _outline(1500, 1000, 1800, 1250, 0))


def niche_blind(panel):
    return Niche(Frame.worldXY(), _outline(2000, 600, 2600, 1500, 0), LayerRole.EXTERIOR, 10.0)


def niche_through(panel):
    return Niche(Frame.worldXY(), _outline(2000, 600, 2600, 1500, 0), LayerRole.EXTERIOR, None)


# name -> (feature factory, keyword arguments of the opening framing)
CASES = {
    "window": (window, {}),
    "window_lintel_posts": (window, {"lintel_posts": True, "header_width": 120.0}),
    "door": (door, {}),
    "door_split_bottom_plate": (door, {"split_bottom_plate_beam": True}),
    "door_split_lintel_posts": (door, {"split_bottom_plate_beam": True, "lintel_posts": True}),
    "mep": (mep, {}),
    "niche_blind": (niche_blind, {}),
    "niche_through": (niche_through, {}),
}


def new_defaults(case):
    """The detail sets that replace the old default agents, configured like the case."""
    from timber_design_populator.detail_sets import FramedNicheDetailSet
    from timber_design_populator.detail_sets import FramedOpeningDetailSet
    from timber_design_populator.detail_sets import FramedPenetrationDetailSet

    _, options = CASES[case]
    return {Opening: FramedOpeningDetailSet(**options), MEPPenetration: FramedPenetrationDetailSet(), Niche: FramedNicheDetailSet()}


# =============================================================================
# populating and fingerprinting
# =============================================================================


def populate(case, defaults):
    feature_factory, _ = CASES[case]
    panel = make_panel()
    panel.add_feature(feature_factory(panel))
    model = ArchModel()
    model.add_element(panel)
    panel.merge_layer_structure(model)
    pop = PanelPopulator(panel, PanelType("parity", panel.layer_structure, agents=make_agents(panel), default_detail_sets=defaults, standard_beam_width=60.0))
    pop.populate_elements()
    pop.join_elements()
    pop.process_joinery()
    pop.merge_with_model(model)
    return model, pop


def _plain(value):
    """*value* as plain JSON data, without guids, floats rounded to 0.1."""
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in sorted(value.items()) if k != "guid"}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, float):
        return round(value, 1) + 0.0
    return value


def _feature_data(feature):
    return _plain(json.loads(json_dumps(feature)))


def _layer_name(element):
    parent = element.parent
    return parent.name if parent is not None else None


def _point(p):
    return [round(c, 1) + 0.0 for c in p]


def fingerprint(model):
    beams = []
    plates = []
    for element in model.elements():
        if isinstance(element, Beam):
            line = element.centerline
            ends = sorted([_point(line.start), _point(line.end)])
            features = sorted(type(f).__name__ for f in element.features)
            beams.append([element.attributes.get("category"), _layer_name(element), ends, round(element.width, 1), features])
        elif isinstance(element, Plate):
            plates.append([_layer_name(element), sorted((_feature_data(f) for f in element.features), key=json.dumps)])
    joints = []
    for joint in model.joints:
        categories = sorted(str(e.attributes.get("category")) for e in joint.elements)
        joints.append([type(joint).__name__, categories])
    return {
        "beams": sorted(beams, key=json.dumps),
        "plates": sorted(plates, key=json.dumps),
        "joints": sorted(joints, key=json.dumps),
    }


def _assert_close(actual, expected, path="$"):
    if isinstance(expected, dict):
        assert isinstance(actual, dict) and sorted(actual) == sorted(expected), "{}: keys {} != {}".format(path, sorted(actual), sorted(expected))
        for key in expected:
            _assert_close(actual[key], expected[key], "{}.{}".format(path, key))
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected), "{}: {} items != {}".format(path, len(actual) if isinstance(actual, list) else actual, len(expected))
        for i, (a, e) in enumerate(zip(actual, expected)):
            _assert_close(a, e, "{}[{}]".format(path, i))
    elif isinstance(expected, float) or isinstance(actual, float):
        assert abs(actual - expected) <= TOLERANCE, "{}: {} != {}".format(path, actual, expected)
    else:
        assert actual == expected, "{}: {!r} != {!r}".format(path, actual, expected)


# =============================================================================
# the tests
# =============================================================================


@pytest.mark.parametrize("case", sorted(CASES))
def test_detail_sets_reproduce_the_replaced_agents(case):
    golden = json.load(open(GOLDEN, encoding="utf-8"))
    model, pop = populate(case, new_defaults(case))
    assert pop.debug_info.feature_errors == []
    _assert_close(fingerprint(model), golden[case])
