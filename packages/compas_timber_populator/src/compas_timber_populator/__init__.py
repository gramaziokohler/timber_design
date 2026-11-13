from .populator import PanelPopulator

from .populator_agents.populator_agent import AgentBoundaryType
from .populator_agents.populator_agent import PopulatorAgent
from .populator_agents.layer_agent import LayerAgent
from .populator_agents.feature_agent import FeatureAgent
from .populator_agents.stud_populator_agent import StudPopulatorAgent
from .populator_agents.plate_populator_agent import PlatePopulatorAgent
from .populator_agents.edge_populator_agent import EdgePopulatorAgent
from .populator_agents.opening_populator_agent import OpeningPopulatorAgent
from .populator_agents.opening_populator_agent import DoorPopulatorAgent
from .populator_agents.opening_populator_agent import WindowPopulatorAgent
from .populator_agents.panel_boundary_populator_agent import PanelBoundaryPopulatorAgent

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
    "LayerAgent",
    "FeatureAgent",
    "StudPopulatorAgent",
    "PlatePopulatorAgent",
    "EdgePopulatorAgent",
    "OpeningPopulatorAgent",
    "DoorPopulatorAgent",
    "WindowPopulatorAgent",
    "PanelBoundaryPopulatorAgent",
]
