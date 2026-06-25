from abc import ABC, abstractmethod

from compas_timber.elements import Layer

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
        and mutated by :meth:`trim_elements` / :meth:`split_agent_elements`.
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

    def __init__(self, layer=None, internal_joint_overrides=None, external_joint_overrides=None):
        # type: (Layer, Optional[list], Optional[list]) -> None
        super(LayerAgent, self).__init__(internal_joint_overrides, external_joint_overrides)
        self._layer = None
        if isinstance(layer, Layer):
            self.layer_path = layer.layer_path
        else:
            self.layer_path = layer

    @property
    def layer(self):
        return self._layer

    def repoint_to_layer_tree(self, tree):
        """Rebind this agent's layer references to the current panel's layer tree by path.

        If no paths were recorded at construction (layer had no layer_path yet),
        the existing direct references are left unchanged.
        """
        if self.layer_path is not None:
            self._layer = tree.get(self.layer_path)


    @property
    def __data__(self):
        data = super().__data__
        data["layer"] = self.layer_path
        return data

    @property
    def layer_center_height(self):
        """Z coordinate of the centre of this agent's layer (populator space)."""
        return self.layer.center_height if self.layer is not None else None

    @property
    def element_layers(self):
        return [self.layer]

    @property
    def trimming_layers(self):
        return [self.layer]

    def generate_elements(self):
        """Generate (and store) this agent's elements.

        With *layer* given, generates only on that layer; otherwise on every
        framing layer in :attr:`element_layers`.  The populator drives this one
        layer at a time (mirroring :meth:`split_agent_elements` /
        :meth:`extend_elements`), but the no-argument form is kept for callers
        that want the whole agent generated at once.
        """
        # Clear stale entries from previous solves before regenerating.
        self.elements_by_layer.clear()
        self.outline_by_layer.clear()
        elements, outline = self.generate_layer_elements()
        self.elements_by_layer[self.layer] = elements  # add to dict
        self.outline_by_layer[self.layer] = outline  # capture boundary

    @abstractmethod
    def generate_layer_elements(self):
        """Generate the elements for the LayerAgent.layer"""
        raise NotImplementedError

    def beam_from_category(self, centerline, category, layer=None, **kwargs):
        """Create a beam, defaulting *layer* to ``self.layer``."""
        return super().beam_from_category(centerline, category, layer=self.layer, **kwargs)

    def is_on_panel(self, panel):
        return self.layer_path in panel.layer_tree
