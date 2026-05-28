from abc import ABC
from dataclasses import dataclass

from .populator_agent import AgentBoundaryType
from .populator_agent import PopulatorAgent
from .populator_agent import PopulatorAgentConfig


@dataclass
class LayerAgentConfig(PopulatorAgentConfig, ABC):
    """Base dataclass for layer-bound populator agent configuration.

    All concrete config classes (e.g. :class:`~timber_design.populators.StudPopulatorAgentConfig`,
    :class:`~timber_design.populators.EdgePopulatorAgentConfig`) extend this
    class and add their own fields.

    Class Attributes
    ----------------
    AGENT_TYPE : type or None
        The :class:`LayerAgent` subclass this config instantiates.
        Set on each concrete subclass after both classes are defined.
    """

    IS_ABSTRACT = True
    AGENT_TYPE = None

    def get_agent_from_layer(self, layer, standard_beam_width=None):
        """Construct this config's :class:`LayerAgent` for *layer*.

        The agent is built with explicit keyword arguments assembled by
        :meth:`~PopulatorAgentConfig._agent_kwargs` — the agent never receives
        the config object itself.

        Parameters
        ----------
        layer : :class:`~timber_design.populators.Layer`
            The layer to create the agent for.
        standard_beam_width : float, optional
            Convenience for constructing an agent in isolation: when given,
            any unset beam-category widths are filled via
            :meth:`~PopulatorAgentConfig.fill_beam_widths` first.  In the full
            pipeline widths are pre-filled by
            :meth:`~timber_design.populators.PanelPopulatorConfig.resolve_beam_widths`
            and this argument is omitted.

        Returns
        -------
        :class:`LayerAgent`

        Raises
        ------
        NotImplementedError
            If ``AGENT_TYPE`` has not been set on this config class.
        """
        if self.AGENT_TYPE is None:
            raise NotImplementedError("{} does not define AGENT_TYPE".format(type(self).__name__))
        if standard_beam_width is not None:
            self.fill_beam_widths(standard_beam_width)
        return self.AGENT_TYPE(layer, **self._agent_kwargs())


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

    def __init__(self, layer, beam_widths=None, internal_joint_overrides=None, external_joint_overrides=None):
        # type: (Layer, Optional[dict], Optional[list], Optional[list]) -> None
        super(LayerAgent, self).__init__(beam_widths, internal_joint_overrides, external_joint_overrides)
        self.layer = layer
        self.layer_index = layer.layer_index if layer is not None else None
        self.layer_center_height = layer.center_height

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

    # elements_for_layer / set_elements_for_layer / trim_elements are inherited
    # from PopulatorAgent: a LayerAgent holds one flat element list and trims on
    # its single layer (PopulatorAgent._trim_layers -> _agent_layers -> [self.layer]).
