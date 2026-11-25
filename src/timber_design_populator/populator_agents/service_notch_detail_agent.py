from __future__ import annotations

import math
from typing import Optional

from compas.geometry import Plane
from compas.geometry import Polyline
from compas.geometry import Vector
from compas.geometry import angle_vectors
from compas_timber.errors import FeatureApplicationError

from timber_design_populator.connections_2d.beam2d import Beam2D
from timber_design_populator.populator_agents.populator_agent import PopulatorAgent
from timber_design_populator.populator_agents.service_geometry import _ServiceLapProxy
from timber_design_populator.populator_agents.service_geometry import crossings
from timber_design_populator.populator_agents.service_geometry import ref_side_facing


class ServiceNotchDetailAgent(PopulatorAgent):
    """Notches every beam a service path runs through, from one side of the panel.

    Creates no elements: it machines the surviving beams of its trimming layers (normally the
    core).  Where the path crosses a beam, a :class:`~compas_timber.fabrication.Lap` notch is
    cut into the beam's face towards *side*, as deep as the service and as long as its
    footprint along the beam.  A notch deeper than :attr:`MAX_NOTCH_RATIO` of the beam's depth
    is reported as a feature error (the default follows the common rule for studs: notches
    up to 25% of the depth).

    Parameters
    ----------
    path : :class:`~compas.geometry.Polyline`
        The service path, in populator space.
    diameter : float
        The service diameter: the notch depth and width.
    side : :class:`~compas.geometry.Vector`
        The panel-normal direction of the face to notch from (e.g. towards the interior).
        ``None``: no notch, a feature error per crossing.
    element_layers, trimming_layers, feature, priority, internal_joint_overrides, external_joint_overrides, composite_joint_overrides : optional
        See :class:`~timber_design_populator.PopulatorAgent`.
    """

    NAME = "ServiceNotchDetailAgent"
    IS_DETAIL = True
    MAX_NOTCH_RATIO = 0.25

    def __init__(self, path: Optional[Polyline] = None, diameter: Optional[float] = None, side: Optional[Vector] = None, **kwargs):
        super().__init__(**kwargs)
        self.path = path
        self.diameter = diameter
        self.side = side

    @property
    def __data__(self):
        data = super().__data__
        data["path"] = self.path
        data["diameter"] = self.diameter
        data["side"] = self.side
        return data

    def machine_element(self, element) -> list:
        if self.path is None or not isinstance(element, Beam2D):
            return []
        warnings = []
        for point, direction in crossings(self.path, element):
            if self.side is None:
                warnings.append(FeatureApplicationError(point, element.blank, "Cannot notch: the side to notch from is unknown."))
                continue
            axis = element.centerline.direction.unitized()
            # the notch spans the service's footprint along the beam
            sin_angle = abs(math.sin(angle_vectors(axis, direction)))
            length = self.diameter / max(sin_angle, 1e-3)
            plane = Plane(point + axis * (length / 2.0), axis)
            element.add_feature(_ServiceLapProxy(plane, element, length, self.diameter, ref_side_facing(element, self.side)))
            if self.diameter > self.MAX_NOTCH_RATIO * element.height:
                warnings.append(
                    FeatureApplicationError(
                        point,
                        element.blank,
                        "{} {:.1f} notch is more than {:.0%} of the beam depth {:.1f}.".format(
                            element.attributes.get("category", "beam"), self.diameter, self.MAX_NOTCH_RATIO, element.height
                        ),
                    )
                )
        return warnings
