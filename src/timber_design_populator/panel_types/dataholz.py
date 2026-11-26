"""Exterior wall buildups after the dataholz.eu catalogue (https://www.dataholz.eu/bauteile/aussenwand.htm).

Each function returns a :class:`~timber_design_populator.PanelType` that follows one catalogue
buildup's layers, thicknesses and materials, with ``reference`` naming the entry.  Layers run
from the exterior (the panel's ``outline_a`` side) to the interior.  Membranes and the
insulation between members are layer attributes (``membrane_a``/``membrane_b`` on the layer's
outer/inner face, ``fill``), not elements.  Values the catalogue leaves open (cladding board
widths, batten spacings it does not state) are parameters with common defaults.

The ``attributes`` (U-value, fire rating) are as the catalogue states them for its reference
variant.  A panel type records them; it does not verify them.  See the catalogue entry for
the conditions they hold under.
"""

from __future__ import annotations

from compas.geometry import Vector
from timber_design_arch.elements import LayerDefinition
from timber_design_arch.elements import LayerStructure
from timber_design_arch.panel_features import LinearService
from timber_design_arch.panel_features import MEPPenetration
from timber_design_arch.panel_features import Niche
from timber_design_arch.panel_features import Opening

from timber_design_populator.detail_sets import CutThroughDetailSet
from timber_design_populator.detail_sets import FramedNicheDetailSet
from timber_design_populator.detail_sets import FramedOpeningDetailSet
from timber_design_populator.detail_sets import FramedPenetrationDetailSet
from timber_design_populator.detail_sets import LinearServiceDetailSet
from timber_design_populator.populator_agents.board_agent import BoardAgent
from timber_design_populator.populator_agents.edge_agent import EdgeAgent
from timber_design_populator.populator_agents.plate_agent import PlateAgent
from timber_design_populator.populator_agents.stud_agent import StudAgent

from .panel_type import PanelType

URL = "https://www.dataholz.eu/bauteile/aussenwand/detail/kz/{}.htm"


def _reference(component_id):
    return {"source": "dataholz.eu", "id": component_id, "url": URL.format(component_id)}


def _framed_sets():
    return {
        Opening: FramedOpeningDetailSet(),
        MEPPenetration: FramedPenetrationDetailSet(),
        Niche: FramedNicheDetailSet(),
        LinearService: LinearServiceDetailSet(),
    }


def _ventilated_facade(sheathing_thickness, sheathing_material, batten_width, batten_spacing, sheathing_attributes=None):
    """The exterior of a ventilated timber facade: cladding boards on vertical battens on a sheathing board."""
    return LayerDefinition(
        "exterior",
        24 + 30 + sheathing_thickness,
        sublayer_defs=[
            LayerDefinition("cladding", 24, material="spruce boards"),
            LayerDefinition("battens", 30, material="spruce", attributes={"use": "ventilation cavity", "section": "30/{}".format(batten_width)}),
            LayerDefinition("sheathing", sheathing_thickness, material=sheathing_material, attributes=sheathing_attributes),
        ],
    )


def _facade_agents(batten_width, batten_spacing, cladding_board_width, cladding_gap):
    return [
        BoardAgent("cladding", board_width=cladding_board_width, spacing=cladding_board_width + cladding_gap, direction=Vector(1, 0, 0), category="cladding"),
        BoardAgent("battens", board_width=batten_width, spacing=batten_spacing, category="batten"),
        PlateAgent("sheathing"),
    ]


def awrhho05b(stud_spacing=625, stud_width=60, batten_spacing=625, cladding_board_width=146, cladding_gap=4, name="awrhho05b"):
    """Timber frame exterior wall, ventilated, no installation layer, timber cladding.

    Exterior to interior: timber cladding 24 on battens 30/50, MDF 15, studs 60/160 @ 625 with
    mineral wool between and a vapour retarder (sd >= 1 m) on the inside, gypsum fibre board 18.
    """
    layers = LayerStructure(
        [
            _ventilated_facade(15, "MDF", 50, batten_spacing),
            LayerDefinition("core", 160, material="C24", attributes={"fill": "mineral wool", "membrane_b": "vapour retarder, sd >= 1 m"}),
            LayerDefinition("interior", 18, material="gypsum fibre board"),
        ]
    )
    agents = _facade_agents(50, batten_spacing, cladding_board_width, cladding_gap) + [
        EdgeAgent("core"),
        StudAgent("core", stud_width=stud_width, stud_spacing=stud_spacing),
        PlateAgent("interior"),
    ]
    return PanelType(name, layers, agents=agents, default_detail_sets=_framed_sets(), standard_beam_width=stud_width, reference=_reference("awrhho05b"), attributes={"U": 0.27})


def awrhhi01a(stud_spacing=625, stud_width=60, batten_spacing=625, installation_spacing=400, installation_batten_width=50, cladding_board_width=146, cladding_gap=4, name="awrhhi01a"):
    """Timber frame exterior wall, ventilated, with an installation layer, timber cladding.

    Exterior to interior: timber cladding 24 on battens 30/50, gypsum fibre board 12.5 with a
    wind barrier (sd <= 0.3 m) on the outside, studs 60/160 @ 625 with mineral wool between,
    gypsum fibre board 10 with a vapour retarder (sd >= 2 m) on the inside, a 40 installation
    layer of horizontal battens @ 400 with mineral wool, gypsum board 12.5.
    """
    layers = LayerStructure(
        [
            _ventilated_facade(12.5, "gypsum fibre board", 50, batten_spacing, sheathing_attributes={"membrane_a": "wind barrier, sd <= 0.3 m"}),
            LayerDefinition("core", 160, material="C24", attributes={"fill": "mineral wool"}),
            LayerDefinition(
                "interior",
                62.5,
                sublayer_defs=[
                    LayerDefinition("bracing", 10, material="gypsum fibre board", attributes={"membrane_b": "vapour retarder, sd >= 2 m"}),
                    LayerDefinition("installation", 40, material="spruce", attributes={"fill": "mineral wool"}),
                    LayerDefinition("lining", 12.5, material="gypsum board type DF"),
                ],
            ),
        ]
    )
    agents = _facade_agents(50, batten_spacing, cladding_board_width, cladding_gap) + [
        EdgeAgent("core"),
        StudAgent("core", stud_width=stud_width, stud_spacing=stud_spacing),
        PlateAgent("bracing"),
        BoardAgent("installation", board_width=installation_batten_width, spacing=installation_spacing, direction=Vector(1, 0, 0), category="installation_batten"),
        PlateAgent("lining"),
    ]
    return PanelType(name, layers, agents=agents, default_detail_sets=_framed_sets(), standard_beam_width=stud_width, reference=_reference("awrhhi01a"), attributes={"U": 0.22})


def awmhhi01a(i_joist_spacing=625, batten_spacing=625, installation_spacing=625, cladding_board_width=146, cladding_gap=4, name="awmhhi01a"):
    """Solid timber exterior wall, ventilated, with an installation layer, timber cladding.

    Exterior to interior: timber cladding 24 on battens 30/60, MDF 15, 300 insulation between
    timber I-joists (flanges 60/45, hardboard web) @ 625, 100 cross-laminated timber, a 70
    installation layer of battens 60/60 on resilient bars @ 625 with 50 insulation, gypsum
    board 12.5.  The I-joists are modelled as solid 60 wide members, and openings and
    penetrations are cut through, not framed (:class:`~timber_design_populator.CutThroughDetailSet`).
    """
    cut = CutThroughDetailSet()
    layers = LayerStructure(
        [
            LayerDefinition(
                "exterior",
                369,
                sublayer_defs=[
                    LayerDefinition("cladding", 24, material="spruce boards"),
                    LayerDefinition("battens", 30, material="spruce", attributes={"use": "ventilation cavity", "section": "30/60"}),
                    LayerDefinition("sheathing", 15, material="MDF"),
                    LayerDefinition("insulation", 300, material="timber I-joist", attributes={"fill": "mineral wool", "section": "flanges 60/45, hardboard web"}),
                ],
            ),
            LayerDefinition("core", 100, material="CLT"),
            LayerDefinition(
                "interior",
                82.5,
                sublayer_defs=[
                    LayerDefinition("installation", 70, material="spruce", attributes={"fill": "50 insulation", "section": "60/60 on resilient bars"}),
                    LayerDefinition("lining", 12.5, material="gypsum board type DF"),
                ],
            ),
        ]
    )
    agents = _facade_agents(60, batten_spacing, cladding_board_width, cladding_gap) + [
        BoardAgent("insulation", board_width=60, spacing=i_joist_spacing, category="i_joist"),
        PlateAgent("core"),
        BoardAgent("installation", board_width=60, spacing=installation_spacing, category="installation_batten"),
        PlateAgent("lining"),
    ]
    detail_sets = {Opening: cut, MEPPenetration: cut, LinearService: LinearServiceDetailSet()}
    return PanelType(name, layers, agents=agents, default_detail_sets=detail_sets, standard_beam_width=60, reference=_reference("awmhhi01a"), attributes={"U": 0.12, "REI": "REI 90 (inside), REI 60 (outside)"})
