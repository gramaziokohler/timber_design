# env: C:\Users\Admin\OneDrive\Documents\01_ETH\04_Repositories\timber_design\src
import Grasshopper
from compas_timber.connections import JointTopology
from compas_timber.connections import LMiterJoint
from compas_timber.connections import TButtJoint
from compas_timber.connections import XLapJoint

from timber_design.workflow import TopologyRule


class DefaultJointRule(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(self):
        topoRules = []
        topoRules.append(TopologyRule(JointTopology.TOPO_L, LMiterJoint))
        topoRules.append(TopologyRule(JointTopology.TOPO_T, TButtJoint))
        topoRules.append(TopologyRule(JointTopology.TOPO_X, XLapJoint))

        return topoRules
