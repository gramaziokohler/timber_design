"""Registers timber_design_arch element types with compas_timber's candidate dispatch.

``TimberModel.compute_topologies()`` looks up a handler for each adjacent pair by the
pair's exact element types. compas_timber only knows its own types, so the panel
pairs are registered here, reusing compas_timber's plate handler: a panel is
plate-like, and ``PlateConnectionSolver`` only needs the outlines and planes that
``Panel`` provides.

The registry is not public API in compas_timber yet (``_register`` and
``_CONNECTION_HANDLERS`` are underscored), which is why it is wrapped in this one
module rather than used directly elsewhere.
"""

from compas_timber.connections import candidate_dispatch as _ct_dispatch

from timber_design_arch.elements import Panel


def register_connection_handlers():
    """Registers the timber_design_arch element type pairs with compas_timber's candidate dispatch.

    Idempotent; called on import of :mod:`timber_design_arch.connections`.
    """
    _ct_dispatch._register(Panel, Panel)(_ct_dispatch._plate_connection_candidate)
