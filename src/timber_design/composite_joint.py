from __future__ import annotations

from typing import TYPE_CHECKING

from compas_timber.connections import Joint
from compas_timber.connections import JointTopology

if TYPE_CHECKING:
    from compas_timber.model import TimberModel


class CompositeJoint(Joint):
    """A joint composed of multiple pairwise sub-joints acting on a cluster of 3 or more elements.

    Instead of defining a single fabrication strategy for the whole cluster, this joint
    delegates all feature and extension calculations to a list of pairwise sub-joints.
    The sub-joints are instantiated without being registered in the model; only the
    CompositeJoint itself is added.

    Parameters
    ----------
    joints : list[:class:`~compas_timber.connections.Joint`], optional
        The pairwise sub-joints that make up this composite connection.

    Attributes
    ----------
    joints : list[:class:`~compas_timber.connections.Joint`]
        The pairwise sub-joints.
    elements : tuple[:class:`~compas_timber.elements.Element`]
        The unique elements connected by this joint, derived from the sub-joints.
    """

    SUPPORTED_TOPOLOGY = JointTopology.TOPO_UNKNOWN
    MIN_ELEMENT_COUNT = 3
    MAX_ELEMENT_COUNT = None

    def __init__(self, joints=None, **kwargs):
        self.joints = joints or []
        elements = list({id(e): e for j in self.joints for e in j.elements}.values())
        if elements:
            super().__init__(elements=elements, **kwargs)
        else:
            # Deserialization path: sub-joints carry element_guids but no live elements yet.
            element_guids = list({guid for j in self.joints for guid in j.element_guids})
            super().__init__(element_guids=element_guids, **kwargs)

    @property
    def __data__(self):
        data = super().__data__
        data["joints"] = self.joints
        return data

    @classmethod
    def __from_data__(cls, data):
        return cls(
            joints=data.get("joints") or [],
            topology=data.get("topology"),
            location=data.get("location"),
            name=data.get("name"),
        )

    def __repr__(self):
        return '{}({} sub-joints)'.format(self.__class__.__name__, len(self.joints))

    @property
    def location(self):
        """The approximate location of the joint, taken from the first sub-joint."""
        if self._location is None and self.joints:
            return self.joints[0].location
        return super().location

    @classmethod
    def create(cls, model, joints=None, **kwargs):
        """Creates a CompositeJoint and registers it in the model.

        Parameters
        ----------
        model : :class:`~compas_timber.model.TimberModel`
            The model to register this joint in.
        joints : list[:class:`~compas_timber.connections.Joint`], optional
            The pairwise sub-joints.

        Returns
        -------
        :class:`~timber_design.composite_joint.CompositeJoint`
        """
        joint = cls(joints=joints, **kwargs)
        model.add_joint(joint)
        return joint

    def add_features(self):
        """Delegates feature calculation to each sub-joint."""
        for joint in self.joints:
            joint.add_features()

    def add_extensions(self):
        """Delegates extension calculation to each sub-joint."""
        for joint in self.joints:
            joint.add_extensions()

    def restore_elements_from_keys(self, model: TimberModel):
        """Restores element references by delegating to each sub-joint, then rebuilds elements.

        Parameters
        ----------
        model : :class:`~compas_timber.model.TimberModel`
            The model from which to look up elements by GUID.
        """
        for joint in self.joints:
            joint.restore_elements_from_keys(model)
        self._elements = tuple({id(e): e for j in self.joints for e in j.elements}.values())
