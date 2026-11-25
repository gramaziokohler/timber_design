from __future__ import annotations

from typing import List

from compas_timber.model import TimberModel

# importing connections registers the panel pairs with compas_timber's candidate dispatch
import compas_arch.connections  # noqa: F401
from compas_arch.elements import Layer
from compas_arch.elements import Panel


class ArchModel(TimberModel):
    """A :class:`~compas_timber.model.TimberModel` that also holds architectural elements.

    Everything a ``TimberModel`` does (beams, plates, joints, candidates, joinery
    processing, serialization) works unchanged. On top of that, ``panels`` and
    ``layers`` return the :mod:`compas_arch.elements` types, so
    ``compute_topologies()`` and ``connect_adjacent_panels()`` pick them up.

    Attributes
    ----------
    panels : list[:class:`~compas_arch.elements.Panel`]
        All panels in this model.
    layers : list[:class:`~compas_arch.elements.Layer`]
        All layers in this model.

    """

    def __str__(self):
        # type: () -> str
        return "ArchModel ({}) with {} elements(s) and {} joint(s).".format(str(self.guid), len(list(self.elements())), len(list(self.joints)))

    @property
    def panels(self) -> List[Panel]:
        return self.find_all_elements_of_type(Panel)

    @property
    def layers(self) -> List[Layer]:
        return self.find_all_elements_of_type(Layer)

    def connect_adjacent_panels(self, max_distance=None):
        """Detects adjacent panels and creates joint candidates for them.

        Parameters
        ----------
        max_distance : float, optional
            The maximum distance between panels to consider them adjacent. Defaults to `TOL.absolute`.

        """
        self.compute_topologies(self.panels, max_distance)
