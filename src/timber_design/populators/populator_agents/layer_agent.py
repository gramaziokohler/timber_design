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

from timber_design.workflow import CategoryRule
from timber_design.workflow import DirectRule


class AgentBoundaryType(object):
    """Controls how an agent's outline is used to include or exclude beam segments.

    Each concrete :class:`LayerAgent` declares a ``BOUNDARY_TYPE`` class
    attribute that governs what :meth:`~LayerAgent.trim_beam` does with
    segments whose midpoints fall inside or outside the agent's
    :attr:`~LayerAgent.outline` polyline.

    Attributes
    ----------
    NONE : str
        No boundary culling — all segments are kept regardless of the outline.
        Used by agents whose elements span the full panel (studs, edge beams).
    EXCLUSIVE : str
        The outline defines a *no-go zone*.  Segments whose midpoints are inside
        the outline are discarded.  Used by :class:`~timber_design.populators.OpeningPopulatorAgent`
        so that studs passing through a door or window opening are removed.
    INCLUSIVE : str
        The outline defines an *allowed zone*.  Segments whose midpoints fall
        *outside* the outline are discarded.  Used by
        :class:`~timber_design.populators.EdgePopulatorAgent` and
        :class:`~timber_design.populators.RecessPopulatorAgent`.
    """

    EXCLUSIVE = "exclusive"
    INCLUSIVE = "inclusive"
    NONE = "none"


@dataclass
class LayerAgentConfig(PopulatorAgentConfig, ABC):
    """Base dataclass for populator agent configuration.

    All concrete config classes (e.g. :class:`~timber_design.populators.StudPopulatorAgentConfig`,
    :class:`~timber_design.populators.EdgePopulatorAgentConfig`) extend this
    class and add their own fields.

    Parameters
    ----------
    beam_width_overrides : dict, optional
        Per-category beam width overrides.  Keys are category name strings
        (e.g. ``"stud"``, ``"header"``); values are floats in model units.
        Overrides are applied by :meth:`~LayerAgent.resolve_beam_dimensions`.
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

    beam_width_overrides: Optional[dict] = None
    joint_rule_overrides: Optional[List[CategoryRule]] = None
    # Populated by resolve_beam_dimensions() before the agent is instantiated.
    # init=False keeps it out of __init__ and repr; default_factory ensures each
    # instance gets its own fresh dict instead of sharing a class-level mutable.
    beam_dimensions: dict = field(default_factory=dict, init=False)

    @property
    def __data__(self):
        return {
            "beam_width_overrides": self.beam_width_overrides,
            "joint_rule_overrides": self.joint_rule_overrides,
        }

    def resolve_beam_dimensions(self, standard_beam_width: float, frame_thickness: float) -> None:
        """Populate :attr:`beam_dimensions` from *standard_beam_width*, *frame_thickness*, and any per-category overrides.

        Called by :meth:`~PanelPopulatorConfig.resolve_beam_dimensions` before
        agents are instantiated.  When the agent is later created, it copies
        this dict so its ``beam_dimensions`` are already populated.

        Parameters
        ----------
        standard_beam_width : float
            Default beam width applied to every category that has no override.
        frame_thickness : float
            Layer thickness used as the beam height for all categories.
        """
        if self.AGENT_TYPE is None:
            return
        bwo = self.beam_width_overrides or {}
        for category in self.AGENT_TYPE.BEAM_CATEGORY_NAMES:
            if category in bwo:
                self.beam_dimensions[category] = (bwo[category], frame_thickness)
            else:
                self.beam_dimensions[category] = (standard_beam_width, frame_thickness)

    def get_agent_from_layer(self, layer):
        """Instantiate the agent for the given layer.

        Parameters
        ----------
        layer : :class:`~timber_design.populators.Layer`
            The layer to create the agent for.

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
        return self.AGENT_TYPE(layer, self)


class LayerAgent(PopulatorAgent, ABC):
    """Abstract base class for all panel populator agents.

    A ``LayerAgent`` is responsible for one logical group of framing
    elements within a panel (edge beams, studs, plates, opening surround,
    recess frame, …).  Subclasses implement :meth:`generate_elements` and
    optionally override :meth:`extend_elements` and :meth:`cull_beam_segment`.

    Every agent holds:

    - :attr:`layer` — the :class:`~timber_design.populators.Layer` it belongs
      to, which carries the panel geometry (``layer.panel``) and the layer's
      position in the cross-section stack (``layer.layer_index``).
    - :attr:`elements` — the flat list of :class:`~timber_design.populators.Beam2D`
      and :class:`~compas_timber.elements.Plate` objects it has created.
    - :attr:`outline` — a closed :class:`~compas.geometry.Polyline` that marks
      its spatial boundary in populator space, used for trimming by peer agents.
    - :attr:`rules` — :class:`~timber_design.workflow.CategoryRule` instances
      that specify which joint type to create between specific beam categories.
    - :attr:`beam_dimensions` — ``{category: (width, height)}`` populated by
      :meth:`resolve_beam_dimensions` from factory-level parameters.

    Class-level attributes
    ----------------------
    BEAM_CATEGORY_NAMES : list[str]
        The beam categories this agent can create.  Used by
        :meth:`resolve_beam_dimensions`.
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
        (``layer.panel``) and cross-section position (``layer.layer_index``).
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
        The panel geometry for this layer.  Shortcut for ``self.layer.panel``.
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
    beam_dimensions : dict[str, tuple[float, float]]
        ``{category: (width, height)}`` mapping resolved by
        :meth:`resolve_beam_dimensions`.
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
        self.layer_center_height = layer.panel.outline_a[0][2] + layer.panel.thickness / 2



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
            if aabb_overlap(self, agent):
                self.trim_agent_elements(agent, self.layer)

