
from typing import Optional

from compas.geometry import Line
from compas_timber.connections import LButtJoint
from compas_timber.connections import TButtJoint

from timber_design.populators.populator_agents.layer_agent import LayerAgent
from timber_design.workflow import CategoryRule


class StudPopulatorAgent(LayerAgent):
    """Generates evenly-spaced vertical studs for a stud-framed wall panel.

    Studs are placed at fixed ``stud_spacing`` intervals along the panel X
    axis, starting at ``stud_spacing`` from the left edge and stopping before
    the right edge.  Each stud runs the full panel height (Y axis) at the
    Z-centre of the layer.

    Stud segments that intersect with an :class:`~timber_design.populators.OpeningPopulatorAgent`
    boundary are removed during the :meth:`~timber_design.populators.PanelPopulator.trim_elements`
    phase; overlapping king or jack studs are culled by
    :meth:`~OpeningPopulatorAgent._cull_stud`.

    Parameters
    ----------
    layer : :class:`~timber_design.populators.Layer`
        The framing layer to fill with studs.  ``layer`` provides the
        length and width; ``layer.layer_index`` is used for cross-layer
        trimming decisions.
    params : :class:`StudPopulatorAgentConfig`
        Must include ``stud_spacing`` and optionally beam width overrides.

    Attributes
    ----------
    stud_spacing : float
        On-centre spacing between studs in model units.  Must be positive
        and non-zero; resolved from the config before the agent is constructed.
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
        # HACK: the following are for when the studs extend and hit a corner in the edge beams. This should eventually be replaced by proper Y_TOPO/K_TOPO joint rules.
        CategoryRule(LButtJoint, "stud", "top_plate_beam", mill_depth=0.0, max_distance=1.0, modify_cross=False),
        CategoryRule(LButtJoint, "stud", "bottom_plate_beam", mill_depth=0.0, max_distance=1.0, modify_cross=False),
        CategoryRule(LButtJoint, "stud", "edge_stud", mill_depth=0.0, max_distance=1.0, modify_cross=False),
    ]

    def __init__(
        self,
        layer=None,
        stud_width: Optional[float] = None,
        internal_joint_overrides=None,
        external_joint_overrides=None,
        stud_spacing=None,
        **kwargs,
    ):
        # type: (Layer, Optional[float], Optional[list], Optional[list], Optional[float]) -> None
        super(StudPopulatorAgent, self).__init__(layer, internal_joint_overrides, external_joint_overrides, **kwargs)
        self.beam_widths["stud"] = stud_width
        # Stored as-is; the default (``stud_width * 8``) is resolved in
        # :meth:`generate_elements` once ``PanelPopulator.resolve_beam_widths``
        # has filled the stud width from ``standard_beam_width``.
        self.stud_spacing = stud_spacing

    @property
    def __data__(self):
        data = super().__data__
        data["stud_width"] = self.beam_widths.get("stud")
        data["stud_spacing"] = self.stud_spacing
        return data

    def generate_layer_elements(self):
        """Populate the layer with stud beams at ``stud_spacing`` intervals."""
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
            studs.append(self.beam_from_category(Line.from_point_and_vector((x_position, 0, self.layer_center_height), (0, self.layer.aabb.ymax, 0)), "stud"))
            x_position += spacing
        return studs, None
