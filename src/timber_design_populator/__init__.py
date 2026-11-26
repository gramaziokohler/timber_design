from .populator import PanelPopulator

from .populator_agents import AgentBoundaryType
from .populator_agents import PopulatorAgent
from .populator_agents import EdgeAgent
from .populator_agents import FasciaEdgeAgent
from .populator_agents import BoardAgent
from .populator_agents import StudAgent
from .populator_agents import PlateAgent
from .populator_agents import LayerBoundaryAgent
from .populator_agents import VoidFramingDetailAgent
from .populator_agents import LayerCutDetailAgent
from .populator_agents import LayerExtensionDetailAgent
from .populator_agents import BackingStudDetailAgent
from .populator_agents import ServiceDrillingDetailAgent
from .populator_agents import ServiceNotchDetailAgent

from .detail_sets import DetailAgentSet
from .detail_sets import FramedOpeningDetailSet
from .detail_sets import FramedPenetrationDetailSet
from .detail_sets import FramedNicheDetailSet
from .detail_sets import LinearServiceDetailSet
from .detail_sets import CutThroughDetailSet
from .detail_sets import PanelJointDetailSet
from .detail_sets import LGenericPanelJointDetailSet
from .detail_sets import TGenericPanelJointDetailSet

from .panel_joints import LGenericPanelJoint
from .panel_joints import TGenericPanelJoint

from .populator_configs.stud_panel_config import stud_panel

from .panel_types import PanelType
from .panel_types import framed_detail_sets
from .panel_types import get_panel_type
from .panel_types import list_panel_types
from .panel_types import list_panel_type_files
from .panel_types import write_panel_type_files
from .panel_types import load_panel_type
from .panel_types import save_panel_type
from .panel_types import stud_wall_layers
from .panel_types import stud_wall_type

__author__ = ["Chen Kasirer"]
__copyright__ = "Gramazio Kohler Research"
__license__ = "MIT License"
__email__ = "kasirer@arch.ethz.ch"
__version__ = "0.3.1"


__all__ = [
    "PanelPopulator",
    "stud_panel",
    "PanelType",
    "framed_detail_sets",
    "get_panel_type",
    "list_panel_types",
    "list_panel_type_files",
    "write_panel_type_files",
    "load_panel_type",
    "save_panel_type",
    "stud_wall_layers",
    "stud_wall_type",
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
    "DetailAgentSet",
    "FramedOpeningDetailSet",
    "FramedPenetrationDetailSet",
    "FramedNicheDetailSet",
    "LinearServiceDetailSet",
    "CutThroughDetailSet",
    "PanelJointDetailSet",
    "LGenericPanelJointDetailSet",
    "TGenericPanelJointDetailSet",
    "LGenericPanelJoint",
    "TGenericPanelJoint",
]
