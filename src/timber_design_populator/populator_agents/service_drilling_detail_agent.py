from __future__ import annotations

from typing import Optional

from compas.geometry import Line
from compas.geometry import Polyline
from compas_timber.errors import FeatureApplicationError

from timber_design_populator.connections_2d.beam2d import Beam2D
from timber_design_populator.populator_agents.populator_agent import PopulatorAgent
from timber_design_populator.populator_agents.service_geometry import _ServiceDrillingProxy
from timber_design_populator.populator_agents.service_geometry import crossings


class ServiceDrillingDetailAgent(PopulatorAgent):
    """Drills a hole through every beam a service path runs through.

    Creates no elements: it machines the surviving beams of its trimming layers (normally the
    core).  A beam is drilled where the path crosses it, along the path, if the path lies
    within the beam's extent through the panel thickness.  A hole larger than
    :attr:`MAX_DRILLING_RATIO` of the beam's depth is reported as a feature error (the default
    follows the common rule for studs: holes up to 40% of the depth).

    Parameters
    ----------
    path : :class:`~compas.geometry.Polyline`
        The service path, in populator space.
    diameter : float
        The hole diameter.
    element_layers, trimming_layers, feature, priority, internal_joint_overrides, external_joint_overrides, composite_joint_overrides : optional
        See :class:`~timber_design_populator.PopulatorAgent`.
    """

    NAME = "ServiceDrillingDetailAgent"
    IS_DETAIL = True
    MAX_DRILLING_RATIO = 0.4

    def __init__(self, path: Optional[Polyline] = None, diameter: Optional[float] = None, **kwargs):
        super().__init__(**kwargs)
        self.path = path
        self.diameter = diameter

    @property
    def __data__(self):
        data = super().__data__
        data["path"] = self.path
        data["diameter"] = self.diameter
        return data

    def machine_element(self, element) -> list:
        if self.path is None or not isinstance(element, Beam2D):
            return []
        warnings = []
        for point, direction in crossings(self.path, element):
            # a line along the service, long enough to pass through the beam
            reach = element.width + element.height
            line = Line(point - direction * reach, point + direction * reach)
            element.add_feature(_ServiceDrillingProxy(line, element, self.diameter))
            if self.diameter > self.MAX_DRILLING_RATIO * element.height:
                warnings.append(
                    FeatureApplicationError(
                        line,
                        element.blank,
                        "{} {:.1f} hole is more than {:.0%} of the beam depth {:.1f}.".format(
                            element.attributes.get("category", "beam"), self.diameter, self.MAX_DRILLING_RATIO, element.height
                        ),
                    )
                )
        return warnings
