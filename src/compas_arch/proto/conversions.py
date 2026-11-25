"""Protobuf guard for compas_arch types.

compas_timber's protobuf schema wraps elements and joints in closed ``oneof``
messages (``ElementData``, ``JointData``) that only know compas_timber's own
classes. compas_pb picks a serializer by walking the object's MRO, so without
this module a compas_arch object would be caught by the nearest compas_timber
ancestor and silently lose its type and data: an ``ArchModel`` would load back as
a ``TimberModel``, a ``Panel`` as a bare ``Element``, a ``PanelLButtJoint`` as a
``PlateLButtJoint``.

Until compas_timber's wrappers gain an extension point that compas_arch can hook
into, every compas_arch type gets a serializer here that raises instead. JSON
serialization (``compas.data.json_dump`` / ``json_load``) is unaffected.

Loaded by compas_pb through the ``compas_pb.plugins`` entry point.
"""

from compas_pb.registry import pb_serializer

from compas_arch.connections import PanelJoint
from compas_arch.elements import Layer
from compas_arch.elements import Panel
from compas_arch.model import ArchModel
from compas_arch.panel_features import PanelFeature

_UNSUPPORTED = (ArchModel, Panel, Layer, PanelFeature, PanelJoint)


def _unsupported(obj):
    raise NotImplementedError(
        "compas_arch does not support protobuf serialization yet: {} would be written as its compas_timber base class "
        "and lose its data. Use compas.data.json_dump() / json_load() instead.".format(type(obj).__name__)
    )


for _cls in _UNSUPPORTED:
    pb_serializer(_cls)(_unsupported)
