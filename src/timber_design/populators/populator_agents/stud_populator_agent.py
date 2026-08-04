from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Optional

from compas.geometry import Line
from compas_timber.connections import TButtJoint

from timber_design.populators.populator_agents.layer_agent import LayerAgent
from timber_design.workflow import CategoryRule

if TYPE_CHECKING:
    from compas_timber.elements import Layer  # noqa: F401


class StudPopulatorAgent(LayerAgent):
    """Generates evenly-spaced vertical studs for a stud-framed wall panel.

    Studs are placed at fixed ``stud_spacing`` intervals along the panel X
    axis, starting at ``stud_spacing`` from the left edge and stopping before
    the right edge.  Each stud runs the full panel height (Y axis) at the
    Z-centre of the layer.

    Stud segments that fall inside an :class:`~timber_design.populators.OpeningPopulatorAgent`
    boundary are removed during
    :meth:`~timber_design.populators.PanelPopulator._cull_elements`; studs
    overlapping a king or jack stud are culled by
    :meth:`~OpeningPopulatorAgent._cull_stud`.

    Parameters
    ----------
    layer : :class:`~compas_timber.elements.Layer` or str, optional
        The framing layer to fill with studs, or its path.
    stud_width : float, optional
        Explicit stud width.  When unset it is filled with the panel-wide
        ``standard_beam_width`` by
        :meth:`~timber_design.populators.PanelPopulator.resolve_beam_widths`.
    internal_joint_overrides, external_joint_overrides : list, optional
        Per-agent joint-rule overrides, see :class:`PopulatorAgent`.
    stud_spacing : float, optional
        On-centre spacing between studs.  ``None`` resolves to
        ``stud_width * 8`` at generation time.

    Attributes
    ----------
    stud_spacing : float or None
        On-centre spacing between studs in model units, or ``None`` to use the
        ``stud_width * 8`` default.  Must resolve to a positive, non-zero value.
    """

    BEAM_CATEGORY_NAMES = ["stud"]
    NAME = "StudPopulatorAgent"
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
        layer: Optional[Layer | str] = None,
        stud_width: Optional[float] = None,
        internal_joint_overrides: Optional[list] = None,
        external_joint_overrides: Optional[list] = None,
        stud_spacing: Optional[float] = None,
        **kwargs,
    ) -> None:
        super().__init__(layer, internal_joint_overrides, external_joint_overrides, **kwargs)
        self.beam_widths["stud"] = stud_width
        self.stud_spacing = stud_spacing

    @property
    def __data__(self):
        data = super().__data__
        data["stud_width"] = self.beam_widths.get("stud")
        data["stud_spacing"] = self.stud_spacing
        return data

    def generate_layer_elements(self):
        """Populate the layer with stud beams at ``stud_spacing`` intervals.

        Returns
        -------
        tuple[list[:class:`~timber_design.populators.Beam2D`], None]
            The studs and this agent's boundary outline — always ``None``,
            studs define no boundary.
        """
        spacing = self.stud_spacing if self.stud_spacing is not None else self.beam_widths["stud"] * 8
        if spacing <= 0:
            raise ValueError(
                "StudPopulatorAgent requires a positive stud_spacing; got {!r}. "
                "Pass an explicit stud_spacing or ensure standard_beam_width is set "
                "so the default (stud_width * 8) is positive.".format(spacing)
            )
        x_position = spacing
        studs = []
        while x_position < self.layer.aabb.xmax - self.beam_widths["stud"]:
            studs.append(
                self.beam_from_category(Line.from_point_and_vector((x_position, -self.layer.aabb.ymax, self.layer_center_height), (0, self.layer.aabb.ymax * 3, 0)), "stud")
            )
            x_position += spacing
        return studs, None
