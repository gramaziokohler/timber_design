from .populator import PanelPopulator

from .populator_agents import AgentBoundaryType
from .populator_agents import PopulatorAgent
from .populator_agents import EdgeAgent
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
from .detail_sets import PanelJointDetailSet
from .detail_sets import LGenericPanelJointDetailSet
from .detail_sets import TGenericPanelJointDetailSet

from .panel_joints import LGenericPanelJoint
from .panel_joints import TGenericPanelJoint

from .populator_configs.stud_panel_config import stud_panel

__author__ = ["Chen Kasirer"]
__copyright__ = "Gramazio Kohler Research"
__license__ = "MIT License"
__email__ = "kasirer@arch.ethz.ch"
__version__ = "0.3.1"


__all__ = [
    "PanelPopulator",
    "stud_panel",
    "AgentBoundaryType",
    "PopulatorAgent",
    "EdgeAgent",
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
    "PanelJointDetailSet",
    "LGenericPanelJointDetailSet",
    "TGenericPanelJointDetailSet",
    "LGenericPanelJoint",
    "TGenericPanelJoint",
]
