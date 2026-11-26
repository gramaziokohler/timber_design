from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Optional

from compas_timber.connections import TButtJoint

from timber_design_populator.populator_agents.board_agent import BoardAgent
from timber_design_rules import CategoryRule

if TYPE_CHECKING:
    from timber_design_arch.elements import Layer  # noqa: F401


class StudAgent(BoardAgent):
    """Generates evenly-spaced studs for a stud-framed wall panel.

    A :class:`~timber_design_populator.BoardAgent` of category ``"stud"``, with the stud-plate
    joint rules.  Studs are placed at ``offset + k * stud_spacing`` along the panel X axis
    (``k >= 1``: the first stud is one spacing from the panel origin, where the edge stud
    is), stopping one stud width before the far edge.  They run along *direction* (default
    the panel's Y axis) through the whole layer, at its Z-centre, and are trimmed by the
    framing boundary (e.g. :class:`~timber_design_populator.EdgeAgent`), not by the layer
    outline.

    Stud segments that fall inside a :class:`~timber_design_populator.VoidFramingDetailAgent`
    boundary are removed during
    :meth:`~timber_design_populator.PanelPopulator._cull_elements`, and so are studs
    overlapping one of its king or jack studs.

    Parameters
    ----------
    layer : :class:`~timber_design_arch.elements.Layer` or tuple, optional
        The framing layer to fill with studs, or its path.
    stud_width : float, optional
        Explicit stud width.  When unset it is filled with the panel-wide
        ``standard_beam_width`` by
        :class:`~timber_design_populator.PanelPopulator`.
    internal_joint_overrides, external_joint_overrides : list, optional
        Per-agent joint-rule overrides, see :class:`PopulatorAgent`.
    stud_spacing : float, optional
        On-centre spacing between studs.  ``None`` resolves to
        ``stud_width * 8`` at generation time.
    direction, offset : optional
        See :class:`~timber_design_populator.BoardAgent`.

    Attributes
    ----------
    stud_spacing : float or None
        On-centre spacing between studs in model units, or ``None`` to use the
        ``stud_width * 8`` default.  Must resolve to a positive, non-zero value.
    """

    NAME = "StudAgent"
    DEFAULT_CATEGORY = "stud"
    CLIP_TO_LAYER = False  # trimmed by the framing boundary, like it always was
    INTERNAL_JOINT_RULES = []
    EXTERNAL_JOINT_RULES = [
        CategoryRule(TButtJoint, "stud", "top_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(TButtJoint, "stud", "bottom_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(TButtJoint, "stud", "edge_stud", mill_depth=10.0, max_distance=1.0),
        CategoryRule(TButtJoint, "stud", "header", mill_depth=10.0, max_distance=1.0),
        CategoryRule(TButtJoint, "stud", "sill", mill_depth=10.0, max_distance=1.0),
    ]

    def __init__(
        self,
        layer: Optional[Layer | tuple] = None,
        stud_width: Optional[float] = None,
        internal_joint_overrides: Optional[list] = None,
        external_joint_overrides: Optional[list] = None,
        stud_spacing: Optional[float] = None,
        **kwargs,
    ) -> None:
        kwargs.pop("category", None)  # always "stud": other agents rely on it
        super().__init__(
            layer=layer,
            board_width=stud_width,
            spacing=stud_spacing,
            internal_joint_overrides=internal_joint_overrides,
            external_joint_overrides=external_joint_overrides,
            **kwargs,
        )

    @property
    def stud_spacing(self):
        return self.spacing

    @stud_spacing.setter
    def stud_spacing(self, value):
        self.spacing = value

    @property
    def __data__(self):
        data = super().__data__
        data["stud_width"] = data.pop("board_width")
        data["stud_spacing"] = data.pop("spacing")
        del data["category"]
        return data

    def _positions(self, lo, hi, spacing, width):
        """``offset + k * spacing`` for ``k >= 1``, up to one stud width before the far edge."""
        positions = []
        position = self.offset + spacing
        while position < hi - width:
            positions.append(position)
            position += spacing
        return positions
