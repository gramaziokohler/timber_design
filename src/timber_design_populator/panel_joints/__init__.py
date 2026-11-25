"""Panel joints that build connection details, one module per joint.

A detail joint does the cross-panel calculation once, with both panels in view, and gives each
panel's interface a detail set holding that panel's half.  A new connection detail is a new
joint/detail-set pair.  Every joint is exported here: compas serializes a joint as
``timber_design_populator.panel_joints/<ClassName>`` and looks the class up in this package.
"""

from .l_generic_panel_joint import LGenericPanelJoint
from .t_generic_panel_joint import TGenericPanelJoint

__all__ = [
    "LGenericPanelJoint",
    "TGenericPanelJoint",
]
