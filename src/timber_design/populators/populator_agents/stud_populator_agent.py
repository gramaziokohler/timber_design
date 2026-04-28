from dataclasses import dataclass

from compas.geometry import Line
from compas_timber.connections import TButtJoint

from timber_design.populators.populator_agents.layer_agent import LayerAgent
from timber_design.populators.populator_agents.layer_agent import LayerAgentConfig
from timber_design.workflow import CategoryRule


@dataclass
class StudPopulatorAgentConfig(LayerAgentConfig):
    """Configuration for a stud-framing agent.

    Parameters
    ----------
    stud_spacing : float
        On-centre spacing between studs in model units.
    """

    stud_spacing: float = 0.0

    @property
    def __data__(self):
        data = super().__data__
        data["stud_spacing"] = self.stud_spacing
        return data


class StudPopulatorAgent(LayerAgent):
    """Generates evenly-spaced vertical studs for a stud-framed wall panel.

    Studs are placed at fixed ``stud_spacing`` intervals along the panel X
    axis, starting at ``stud_spacing`` from the left edge and stopping before
    the right edge.  Each stud runs the full panel height (Y axis) at the
    Z-centre of the layer.

    Stud segments that intersect with an :class:`~timber_design.populators.OpeningPopulatorAgent`
    boundary are removed during the :meth:`~timber_design.populators.PanelPopulator.trim_within_layer_elements`
    phase; overlapping king or jack studs are culled by
    :meth:`~OpeningPopulatorAgent._cull_stud`.

    Parameters
    ----------
    layer : :class:`~timber_design.populators.Layer`
        The framing layer to fill with studs.  ``layer.panel`` provides the
        length and width; ``layer.layer_index`` is used for cross-layer
        trimming decisions.
    params : :class:`StudPopulatorAgentConfig`
        Must include ``stud_spacing`` and optionally beam width overrides.

    Attributes
    ----------
    stud_spacing : float
        On-centre spacing between studs in model units.
    """

    BEAM_CATEGORY_NAMES = ["stud"]
    NAME = "StudPopulatorAgent"
    INTERNAL_RULES = []
    EXTERNAL_RULES = [
        CategoryRule(TButtJoint, "stud", "top_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(TButtJoint, "stud", "bottom_plate_beam", mill_depth=10.0, max_distance=1.0),
        CategoryRule(TButtJoint, "stud", "edge_stud", mill_depth=10.0, max_distance=1.0),
        CategoryRule(TButtJoint, "stud", "header", mill_depth=10.0, max_distance=1.0),
        CategoryRule(TButtJoint, "stud", "sill", mill_depth=10.0, max_distance=1.0),
    ]

    def __init__(self, layer, params):
        # type: (Layer, StudPopulatorAgentConfig) -> None
        super(StudPopulatorAgent, self).__init__(layer, params)
        self.stud_spacing = params.stud_spacing

    def generate_elements(self):
        """Populate the layer with stud beams at ``stud_spacing`` intervals."""
        x_position = self.stud_spacing
        studs = []
        while x_position < self.panel.aabb.xmax - self.beam_dimensions["stud"][0]:
            studs.append(self.beam_from_category(Line.from_point_and_vector((x_position, 0, self.layer_center_height), (0, self.panel.aabb.ymax, 0)), "stud"))
            x_position += self.stud_spacing
        self.elements = studs


# Set after both classes are defined so forward reference is resolved
StudPopulatorAgentConfig.AGENT_TYPE = StudPopulatorAgent
