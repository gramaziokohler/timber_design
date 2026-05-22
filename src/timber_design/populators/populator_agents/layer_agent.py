from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from dataclasses import field
from typing import List
from typing import Optional
from typing import Union

from compas.geometry import Line
from compas.geometry import Vector
from compas.itertools import pairwise
from compas_timber.base import TimberElement
from compas_timber.connections import JointCandidate
from compas_timber.connections import JointTopology
from compas_timber.elements import Plate
from compas_timber.utils import is_point_in_polyline

from timber_design.populators import aabb_overlap
from timber_design.populators.agent_intersection import BeamOutlineIntersectionData
from timber_design.populators.agent_intersection import find_beam_outline_crossings
from timber_design.populators.beam2d import AABB2D
from timber_design.populators.beam2d import Beam2D
from timber_design.populators.connection_solver_2d import ConnectionSolver2D
from timber_design.populators.layer import Layer
from .populator_agent import PopulatorAgentConfig
from .populator_agent import PopulatorAgent
from .populator_agent import AgentBoundaryType

from timber_design.workflow import CategoryRule
from timber_design.workflow import DirectRule




@dataclass
class LayerAgentConfig(PopulatorAgentConfig, ABC):
    """Base dataclass for layer-bound populator agent configuration.

    All concrete config classes (e.g. :class:`~timber_design.populators.StudPopulatorAgentConfig`,
    :class:`~timber_design.populators.EdgePopulatorAgentConfig`) extend this
    class and add their own fields.

    Parameters
    ----------
    beam_width_overrides : dict, optional
        Per-category beam width overrides.  Keys are category name strings
        (e.g. ``"stud"``, ``"header"``); values are floats in model units.
        Applied as fallback when a concrete subclass does not provide an
        explicit per-category width kwarg.
    joint_rule_overrides : list[:class:`~timber_design.workflow.CategoryRule`], optional
        Rules that replace matching entries in the agent's ``RULES`` list.
        Non-matching overrides are appended.

    Class Attributes
    ----------------
    AGENT_TYPE : type or None
        The :class:`LayerAgent` subclass this config instantiates.
        Set on each concrete subclass after both classes are defined.
    """
    IS_ABSTRACT = True
    AGENT_TYPE = None

    def get_agent_from_layer(self, layer, standard_beam_width=None):
        """Instantiate the agent for the given layer.

        Fills any missing entries in :attr:`beam_widths` from
        :attr:`beam_width_overrides` and *standard_beam_width* before
        constructing the agent, so the agent receives a fully-resolved
        ``beam_widths`` dict.

        Parameters
        ----------
        layer : :class:`~timber_design.populators.Layer`
            The layer to create the agent for.
        standard_beam_width : float, optional
            Default width applied to every beam category not already present
            in :attr:`beam_widths`.

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
        bwo = self.beam_width_overrides or {}
        for category in self.AGENT_TYPE.BEAM_CATEGORY_NAMES:
            if category not in self.beam_widths:
                self.beam_widths[category] = bwo.get(category, standard_beam_width)
        return self.AGENT_TYPE(layer, self)


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
        :meth:`resolve_beam_widths`.
    INTERNAL_RULES : list[:class:`~timber_design.workflow.CategoryRule`]
        Default joint rules for **within-agent** pairs — elements that belong
        to this agent and are joined to each other.  Used by
        :meth:`create_joint_defs` / :meth:`get_direct_rule_from_elements`.
        Overridable per-instance via :attr:`LayerAgentConfig.joint_rule_overrides`.
    EXTERNAL_RULES : list[:class:`~timber_design.workflow.CategoryRule`]
        Default joint rules for **cross-agent** pairs — elements from this
        agent that are joined to elements from a different agent.  Used by
        :meth:`~timber_design.populators.PanelPopulator.create_cross_agent_joints`.
        Overridable per-instance via :attr:`LayerAgentConfig.joint_rule_overrides`.
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
        and mutated by :meth:`trim_within_layer` / :meth:`trim_agent_elements`.
    outline : :class:`~compas.geometry.Polyline` or None
        Closed boundary polyline in populator space.  Set by :meth:`generate_elements`.
    internal_rules : list[:class:`~timber_design.workflow.CategoryRule`]
        Active within-agent joint rules (``INTERNAL_RULES`` merged with any
        matching :attr:`LayerAgentConfig.joint_rule_overrides`).
    external_rules : list[:class:`~timber_design.workflow.CategoryRule`]
        Active cross-agent joint rules (``EXTERNAL_RULES`` merged with any
        matching :attr:`LayerAgentConfig.joint_rule_overrides`).
    beam_widths : dict[str, float]
        ``{category: width}`` mapping filled by :meth:`get_agent_from_layer`.
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
    INTERNAL_RULES = []
    EXTERNAL_RULES = []
    BOUNDARY_TYPE = AgentBoundaryType.NONE

    def __init__(self, layer, params):
        # type: (Layer, LayerAgentConfig) -> None
        super(LayerAgent, self).__init__(params)
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

    def elements_for_layer(self, layer):
        """Return the elements this agent has placed on *layer*.

        A :class:`LayerAgent` is always bound to exactly one layer, so this
        returns ``self.elements`` regardless of which layer is passed.  The
        caller is responsible for only passing layers this agent is registered
        on.

        Parameters
        ----------
        layer : :class:`~timber_design.populators.Layer`

        Returns
        -------
        list
        """
        return self.elements

    def set_elements_for_layer(self, layer, elements):
        """Replace this agent's element list for *layer*.

        For a single-layer :class:`LayerAgent`, replaces ``self.elements``
        entirely.  Called by :meth:`trim_within_layer` after trimming so the
        agent's element list reflects surviving post-trim segments.

        Parameters
        ----------
        layer : :class:`~timber_design.populators.Layer`
        elements : list
        """
        self.elements = elements

    def trim_elements(self):
        for agent in self.layer.agents:
            if agent is self:
                continue  # never apply an agent's own boundary to its own elements
            if aabb_overlap(self, agent):
                self.trim_agent_elements(agent, self.layer)

