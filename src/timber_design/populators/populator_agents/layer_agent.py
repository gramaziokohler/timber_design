from abc import ABC

from .populator_agent import AgentBoundaryType
from .populator_agent import PopulatorAgent


class LayerAgent(PopulatorAgent, ABC):
    """Abstract base class for all panel populator agents.

    A ``LayerAgent`` is responsible for one logical group of framing
    elements within a panel (edge beams, studs, plates, opening surround,
    recess frame, …).  Subclasses implement :meth:`generate_elements` and
    optionally override :meth:`extend_elements` and :meth:`cull_beam_segment`.

    Every agent holds:

    - :attr:`layer` — the :class:`~timber_design.populators.Layer` it belongs
      to, which carries the panel geometry (``layer``) and the layer's
      position in the cross-section stack (``layer.layer_index``).
    - :attr:`elements` — the flat list of :class:`~timber_design.populators.Beam2D`
      and :class:`~compas_timber.elements.Plate` objects it has created.
    - :attr:`outline` — a closed :class:`~compas.geometry.Polyline` that marks
      its spatial boundary in populator space, used for trimming by peer agents.
    - :attr:`rules` — :class:`~timber_design.workflow.CategoryRule` instances
      that specify which joint type to create between specific beam categories.
    - :attr:`beam_widths` — ``{category: width}`` filled by
      :meth:`get_agent_from_layer` just before the agent is constructed.

    Class-level attributes
    ----------------------
    BEAM_CATEGORY_NAMES : list[str]
        The beam categories this agent can create.  Used by
        :meth:`~PopulatorAgentConfig.fill_beam_widths`.
    INTERNAL_JOINT_RULES : list[:class:`~timber_design.workflow.CategoryRule`]
        Default joint rules for **within-agent** pairs — elements that belong
        to this agent and are joined to each other.  Used by
        :meth:`create_joint_defs` / :meth:`get_direct_rule_from_elements`.
        Overridable per-instance via the config's ``internal_joint_overrides``.
    EXTERNAL_JOINT_RULES : list[:class:`~timber_design.workflow.CategoryRule`]
        Default joint rules for **cross-agent** pairs — elements from this
        agent that are joined to elements from a different agent.  Used by
        :meth:`~timber_design.populators.PanelPopulator.create_cross_agent_joints`.
        Overridable per-instance via the config's ``external_joint_overrides``.
    BOUNDARY_TYPE : :class:`FeatureBoundaryType`
        Controls how the agent's outline is used during trimming.
        Defaults to :attr:`~FeatureBoundaryType.NONE`.

    Parameters
    ----------
    layer : :class:`~timber_design.populators.Layer`
        The layer this agent operates within.  Provides the panel geometry
        (``layer``) and cross-section position (``layer.layer_index``).
    params : :class:`LayerAgentConfig`
        Configuration including beam width overrides, joint rule overrides,
        agent parameters and rule overrides.

    Attributes
    ----------
    layer : :class:`~timber_design.populators.Layer`
        The layer this agent belongs to.
    layer_index : int or None
        Index of this agent's layer in the cross-section stack.
        Taken directly from ``layer.layer_index``.
    panel : :class:`compas_timber.elements.Panel`
        The panel geometry for this layer.  Shortcut for ``self.layer``.
    elements : list[:class:`~timber_design.populators.Beam2D` | :class:`~compas_timber.elements.Plate`]
        All elements created by this agent.  Populated by :meth:`generate_elements`
        and mutated by :meth:`trim_elements` / :meth:`trim_agent_elements`.
    outline : :class:`~compas.geometry.Polyline` or None
        Closed boundary polyline in populator space.  Set by :meth:`generate_elements`.
    internal_rules : list[:class:`~timber_design.workflow.CategoryRule`]
        Active within-agent joint rules (``INTERNAL_JOINT_RULES`` merged with
        any matching ``internal_joint_overrides``).
    external_rules : list[:class:`~timber_design.workflow.CategoryRule`]
        Active cross-agent joint rules (``EXTERNAL_JOINT_RULES`` merged with
        any matching ``external_joint_overrides``).
    beam_widths : dict[str, float]
        ``{category: width}`` mapping supplied by the config.
        Beam height is always ``layer.thickness`` at call time.
    joint_defs : list[:class:`~timber_design.workflow.DirectRule`]
        Accumulated joint definitions, populated by :meth:`create_joint_defs`.
    aabb : :class:`~timber_design.populators.AABB2D` or None
        2D bounding box enclosing all elements in this agent.
    layer_center_height : float
        Z coordinate of the centre of this agent's layer.  Used to place beam
        centrelines at the correct height in populator space.
    """

    BEAM_CATEGORY_NAMES = []
    INTERNAL_JOINT_RULES = []
    EXTERNAL_JOINT_RULES = []
    BOUNDARY_TYPE = AgentBoundaryType.NONE

    def __init__(self, layer, internal_joint_overrides=None, external_joint_overrides=None):
        # type: (Layer, Optional[list], Optional[list]) -> None
        super(LayerAgent, self).__init__(internal_joint_overrides, external_joint_overrides)
        self.layer = layer
        self.element_layers = [layer]  # default to only generating on this agent's layer; override in subclass if needed
        self.trimming_layers = [layer]  # default to only trimming on this agent's layer; override in subclass if needed

    @property
    def __data__(self):
        data = super().__data__
        data["layer"] = self.layer
        return data

    @property
    def layer_center_height(self):
        """Z coordinate of the centre of this agent's layer (populator space).

        Computed from :attr:`layer` rather than cached, so re-pointing the agent
        onto a different layer (e.g. the populator-panel copy) stays consistent.
        """
        return self.layer.center_height if self.layer is not None else None

    @property
    def panel(self):
        """The panel geometry for this layer (``Layer`` IS a ``Panel``)."""
        return self.layer

    def _agent_layers(self):
        return [self.layer] if self.layer is not None else []

    def beam_from_category(self, centerline, category, layer=None, **kwargs):
        """Create a beam, defaulting *layer* to ``self.layer``.

        Delegates to :meth:`~PopulatorAgent.beam_from_category` with
        ``layer`` set to ``self.layer`` when the caller omits it.  This lets
        :class:`LayerAgent` subclasses call
        ``self.beam_from_category(line, "stud")`` without explicitly passing
        the layer every time.

        :class:`FeatureAgent` subclasses must pass *layer* explicitly because
        they operate across multiple layers.
        """
        return super().beam_from_category(centerline, category, layer=layer or self.layer, **kwargs)

    def is_on_layer(self, layer):
        """Tests whether this agent is active on *layer*.
        Parameters
        ----------
        layer : :class:`~timber_design.populators.Layer`
            The layer to check.
        """
        return layer is self.layer

    def is_on_panel(self, panel):
        """Tests whether this agent is active on *layer*.
        Parameters
        ----------
        layer : :class:`~timber_design.populators.Layer`
            The layer to check.
        """
        return self.layer in panel.layers
