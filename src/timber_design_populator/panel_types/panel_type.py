from __future__ import annotations

from compas.data import Data
from compas.data.encoders import cls_from_dtype
from timber_design_arch.elements import LayerRole
from timber_design_arch.elements import LayerStructure

from timber_design_populator.populator import PanelPopulator


class PanelType(Data):
    """A named panel buildup: its cross-section, how each layer is built, and how its features are built.

    A wall, floor or roof type such as the buildups of a catalogue (e.g. dataholz.eu):

    - :attr:`layer_structure`, the cross-section: layers with thicknesses and materials;
    - :attr:`agents`, how each layer is built: panel-wide agents (studs, plates, battens,
      cladding) referring to their layers by path;
    - :attr:`default_detail_sets`, how features in this type are built (openings, services);
    - the populator settings (beam width, joint rules) that go with them.

    It is panel-agnostic, so one type serves every panel of that type.  :meth:`apply` gives a
    panel the cross-section (a design step: panel joints then see the real layers), and
    :meth:`populator` makes the populator that builds it.

    Parameters
    ----------
    name : str
        The type's name, e.g. ``"awrhho05b"``.
    layer_structure : :class:`~timber_design_arch.elements.LayerStructure`, optional
        The cross-section.  Default: one core layer.
    agents : list[:class:`~timber_design_populator.PopulatorAgent`], optional
        Panel-wide agent prototypes.  Their layers are paths in *layer_structure*, or names:
        a layer's name (e.g. ``"battens"``) or, for a root layer, its role (``"core"``).
        Names are resolved to paths here.
    default_detail_sets : dict[type, :class:`~timber_design_populator.DetailAgentSet`], optional
        The detail set per feature type, see :class:`~timber_design_populator.PanelPopulator`.
    standard_beam_width : float, optional
        The populator's default beam width.
    joint_rule_overrides : list, optional
        The populator's panel-level joint rules.
    max_distance : float, optional
        The populator's joint distance.
    reference : dict, optional
        Where the type comes from, e.g. ``{"source": "dataholz.eu", "id": "awrhho05b", "url": ...}``.
    attributes : dict, optional
        Properties as the source states them, e.g. ``{"U": 0.27, "REI": "REI 60"}``.  Recorded,
        not checked: a type that follows a catalogue buildup in geometry and materials does not
        verify its fire, sound or thermal performance.

    Raises
    ------
    ValueError
        If an agent refers to a layer *layer_structure* does not have, an agent is a detail
        agent, or a detail set is given for a feature type it does not build.
    """

    @property
    def __data__(self):
        return {
            "name": self.name,
            "layer_structure": self.layer_structure,
            "agents": self.agents,
            "default_detail_sets": [["{}/{}".format(".".join(cls.__module__.split(".")[:2]), cls.__name__), detail_set] for cls, detail_set in self.default_detail_sets.items()],
            "standard_beam_width": self.standard_beam_width,
            "joint_rule_overrides": self.joint_rule_overrides,
            "max_distance": self.max_distance,
            "reference": self.reference,
            "attributes": self.attributes,
        }

    @classmethod
    def __from_data__(cls, data):
        data = dict(data)
        data["default_detail_sets"] = {cls_from_dtype(dtype): detail_set for dtype, detail_set in data.get("default_detail_sets") or []}
        return cls(**data)

    def __init__(
        self,
        name,
        layer_structure=None,
        agents=None,
        default_detail_sets=None,
        standard_beam_width=None,
        joint_rule_overrides=None,
        max_distance=None,
        reference=None,
        attributes=None,
    ):
        super().__init__(name=name)
        self.layer_structure = layer_structure or LayerStructure()
        self.default_detail_sets = dict(default_detail_sets) if default_detail_sets else {}
        self.standard_beam_width = standard_beam_width
        self.joint_rule_overrides = list(joint_rule_overrides) if joint_rule_overrides else []
        self.max_distance = max_distance
        self.reference = dict(reference) if reference else {}
        self.attributes = dict(attributes) if attributes else {}
        self.agents = [self._bound(agent) for agent in agents or []]
        self._check_detail_sets()

    def __repr__(self):
        return "PanelType({!r}, {} layers, {} agents)".format(self.name, len(self.layer_paths()), len(self.agents))

    # ------------------------------------------------------------------
    # layers
    # ------------------------------------------------------------------

    @property
    def thickness(self):
        """The fixed thickness of the cross-section, or ``None`` when a layer fills what a panel leaves."""
        defs = self.layer_structure.layer_defs
        if any(d.thickness is None for d in defs):
            return None
        return sum(d.thickness for d in defs)

    def layer_paths(self):
        """The paths of every layer of :attr:`layer_structure`."""
        paths = []

        def walk(defs):
            for def_ in defs:
                paths.append(tuple(def_.layer_path))
                walk(def_.sublayer_defs)

        walk(self.layer_structure.layer_defs)
        return paths

    def layer_path(self, name_or_path):
        """The path of a layer given by path, name or (for a root layer) role.

        Raises
        ------
        ValueError
            If there is no such layer.
        """
        if isinstance(name_or_path, (list, tuple)):
            path = tuple(name_or_path)
            if path in self.layer_paths():
                return path
        else:
            path = self.layer_structure.get_path_for_name(name_or_path)
            if path is None and name_or_path in LayerRole._value2member_map_:
                path = self.layer_structure.get_path_for_role(name_or_path)
            if path is not None:
                return tuple(path)
        raise ValueError("Panel type {!r} has no layer {!r}; its layers are {}.".format(self.name, name_or_path, self._layer_names()))

    def _layer_names(self):
        names = []

        def walk(defs):
            for def_ in defs:
                names.append(def_.name or str(tuple(def_.layer_path)))
                walk(def_.sublayer_defs)

        walk(self.layer_structure.layer_defs)
        return ", ".join(names)

    def _bound(self, agent):
        """A clone of *agent* whose layers are paths of this type's layers."""
        if agent.IS_DETAIL:
            raise ValueError("{} is a detail agent; detail sets create these.  A panel type takes panel-wide agents.".format(type(agent).__name__))
        agent = agent.clone()
        agent.element_layer_paths = [self.layer_path(p) for p in agent.element_layer_paths]
        agent.trimming_layer_paths = [self.layer_path(p) for p in agent.trimming_layer_paths]
        return agent

    def _check_detail_sets(self):
        for feature_type, detail_set in self.default_detail_sets.items():
            if not issubclass(feature_type, tuple(type(detail_set).FEATURE_TYPES)):
                raise ValueError("{} does not build {} features.".format(type(detail_set).__name__, feature_type.__name__))

    # ------------------------------------------------------------------
    # use
    # ------------------------------------------------------------------

    def apply(self, panel):
        """Give *panel* this type's cross-section, and record the type's name in its attributes.

        Parameters
        ----------
        panel : :class:`~timber_design_arch.elements.Panel`

        Raises
        ------
        ValueError
            If the type has a fixed :attr:`thickness` and *panel* is not that thick.
        """
        self.check_thickness(panel)
        panel.layer_structure = self.layer_structure.copy()
        panel.attributes["panel_type"] = self.name

    def populator(self, panel):
        """A :class:`~timber_design_populator.PanelPopulator` that builds *panel* as this type: ``PanelPopulator(panel, self)``.

        The populator carries the type's layer structure and gives it to the panel when it
        populates (or rebinds to a model), unless the panel's layers are already in its model,
        e.g. after :meth:`apply`.  So the panel may enter the model without layers.

        Raises
        ------
        ValueError
            If the type has a fixed :attr:`thickness` and *panel* is not that thick.
        """
        return PanelPopulator(panel, self)

    def derive(self, name=None, agents=None, default_detail_sets=None, standard_beam_width=None, joint_rule_overrides=None, max_distance=None):
        """A copy of this type with more agents or other settings, e.g. for one panel.

        Parameters
        ----------
        name : str, optional
            Default: this type's name.
        agents : list, optional
            More panel-wide agents, added to the type's own.  Their layers are resolved like the
            type's.
        default_detail_sets : dict, optional
            Detail sets per feature type, replacing the type's for those types.
        standard_beam_width, joint_rule_overrides, max_distance : optional
            Replace the type's settings.

        Returns
        -------
        :class:`PanelType`
        """
        sets = dict(self.default_detail_sets)
        sets.update(default_detail_sets or {})
        return PanelType(
            name or self.name,
            self.layer_structure.copy(),
            agents=[agent.clone() for agent in self.agents] + list(agents or []),
            default_detail_sets=sets,
            standard_beam_width=standard_beam_width if standard_beam_width is not None else self.standard_beam_width,
            joint_rule_overrides=joint_rule_overrides if joint_rule_overrides is not None else self.joint_rule_overrides,
            max_distance=max_distance if max_distance is not None else self.max_distance,
            reference=self.reference,
            attributes=self.attributes,
        )

    def check_thickness(self, panel):
        """Raise ``ValueError`` if the type has a fixed :attr:`thickness` and *panel* is not that thick."""
        if self.thickness is not None and abs(panel.thickness - self.thickness) > 1e-3:
            raise ValueError("Panel type {!r} is {} thick; panel {!r} is {}.".format(self.name, self.thickness, panel.name, panel.thickness))

    def check_panel(self, panel):
        """Raise ``ValueError`` if *panel* lacks a layer the type's agents build."""
        have = set()

        def walk(layers):
            for layer in layers:
                if layer.layer_path is not None:  # sublayers assigned directly (as Grasshopper does) have none
                    have.add(tuple(layer.layer_path))
                walk(layer.sublayers)

        walk(panel.layers)
        missing = sorted({p for agent in self.agents for p in agent.element_layer_paths + agent.trimming_layer_paths} - have)
        if missing:
            raise ValueError("Panel {!r} has no layer at {} for panel type {!r}: apply the type to the panel first.".format(panel.name, ", ".join(map(str, missing)), self.name))
