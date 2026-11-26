"""Populator agents, one module per agent.

Panel-wide agents (``*Agent``) are configured on the populator; detail agents (``*DetailAgent``)
are created by detail sets.  Every agent is exported here: compas serializes a class as
``timber_design_populator.populator_agents/<ClassName>`` and looks it up in this package when
decoding (e.g. detail agents in a serialized model).
"""

from .populator_agent import AgentBoundaryType
from .populator_agent import PopulatorAgent
from .edge_agent import EdgeAgent
from .fascia_edge_agent import FasciaEdgeAgent
from .board_agent import BoardAgent
from .stud_agent import StudAgent
from .plate_agent import PlateAgent
from .layer_boundary_agent import LayerBoundaryAgent
from .void_framing_detail_agent import VoidFramingDetailAgent
from .layer_cut_detail_agent import LayerCutDetailAgent
from .layer_extension_detail_agent import LayerExtensionDetailAgent
from .backing_stud_detail_agent import BackingStudDetailAgent
from .service_drilling_detail_agent import ServiceDrillingDetailAgent
from .service_notch_detail_agent import ServiceNotchDetailAgent

__all__ = [
    "AgentBoundaryType",
    "PopulatorAgent",
    "EdgeAgent",
    "FasciaEdgeAgent",
    "BoardAgent",
    "StudAgent",
    "PlateAgent",
    "LayerBoundaryAgent",
    "VoidFramingDetailAgent",
    "LayerCutDetailAgent",
    "LayerExtensionDetailAgent",
    "BackingStudDetailAgent",
    "ServiceDrillingDetailAgent",
    "ServiceNotchDetailAgent",
]
