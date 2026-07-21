
from typing import Optional

from compas.geometry import Box
from compas.geometry import Line
from compas.geometry import Plane
from compas.geometry import Point
from compas.geometry import Polyline
from compas.geometry import intersection_line_plane
from compas.tolerance import TOL
from compas_timber.connections import LButtJoint
from compas_timber.connections import TButtJoint
from compas_timber.elements import Beam
from compas_timber.elements import Plate
from compas_timber.fabrication import LongitudinalCutProxy
from compas_timber.fabrication.free_contour import FreeContour
from compas_timber.panel_features import Opening
from compas_timber.panel_features import OpeningType
from compas_timber.utils import extend_line_segments
from compas_timber.utils import join_polyline_segments

from timber_design.connections_2d.beam2d import Beam2D
from timber_design.connections_2d.connection_solver_2d import ConnectionSolver2D
from timber_design.connections_2d.connection_solver_2d import aabb_overlap
from timber_design.populators.populator_agents.feature_agent import FeatureAgent
from timber_design.populators.populator_agents.layer_agent import AgentBoundaryType
from timber_design.workflow import CategoryRule
from timber_design.workflow import DirectRule


class OpeningPopulatorAgent(FeatureAgent):
    """Generates the structural surround for a door or window opening.

    This is the shared base for :class:`DoorPopulatorAgent` and
    :class:`WindowPopulatorAgent`, which hold the behaviour that differs
    between the two opening types.  It creates the framing common to both:

    - **header** — horizontal beam above the opening.
    - **king_stud** — full-height vertical studs flanking the opening.
    - **jack_stud** — shorter vertical studs (lintel posts) between the king
      studs and the header/sill, created only when ``params.lintel_posts`` is
      ``True``.

    :class:`WindowPopulatorAgent` additionally creates a **sill** — the
    horizontal beam below the opening.  :class:`DoorPopulatorAgent`
    additionally understands ``split_bottom_plate_beam``.

    Dispatch to the right subclass
    -------------------------------
    Panel populator configs register a single prototype agent per feature
    *class* (``default_feature_configs[Opening] = OpeningPopulatorAgent(...)``)
    because :class:`~compas_timber.panel_features.Opening` is used for both
    doors and windows — there is no separate Python class per opening type to
    key the dispatch on.  To still get door/window-specific behaviour from
    that single registration, binding a concrete :class:`Opening` feature to a
    **plain** ``OpeningPopulatorAgent`` (i.e. not already a subclass instance)
    swaps ``self.__class__`` to :class:`DoorPopulatorAgent` or
    :class:`WindowPopulatorAgent` based on ``feature.opening_type`` — see the
    :attr:`feature` setter.  Instantiating a subclass directly
    (``DoorPopulatorAgent(feature=...)``) is respected as-is and never
    re-dispatched.

    The agent computes its :attr:`~LayerAgent.outline` from the
    outer edges of the king (and jack) studs and the header (and sill), so
    that peer agents (studs) can trim their elements at the opening boundary
    via :meth:`~timber_design.populators.PopulatorAgent.trim_elements`.

    Its :attr:`~LayerAgent.BOUNDARY_TYPE` is
    :attr:`~FeatureBoundaryType.EXCLUSIVE`, meaning that studs whose midpoints
    fall inside the outline are discarded by :meth:`~LayerAgent.trim_beam`.

    The opening geometry is supplied via ``params.feature`` (set automatically
    by :meth:`~timber_design.populators.LayerAgentConfig.get_agent_from_feature`).
    Access it via :attr:`opening`.

    Parameters
    ----------
    layer : :class:`~timber_design.populators.Layer`
        The framing layer in which the opening surround is placed.
    params : :class:`OpeningPopulatorAgentConfig`
        Beam dimension and joint-rule settings.
    feature : :class:`compas_timber.panel_features.Opening`
        The (possibly transformed) opening feature that drives element
        placement.  Stored as ``self.feature`` and accessible via the
        :attr:`opening` alias.

    Attributes
    ----------
    opening : :class:`compas_timber.panel_features.Opening`
        The opening feature that drives element placement.
        Alias for ``self.feature``.
    opening_type : :class:`compas_timber.panel_features.OpeningType`
        The opening type read from the opening feature.
    lintel_posts : bool
        Whether jack studs (lintel posts) are generated.
    split_bottom_plate_beam : bool
        For doors: if ``True`` the bottom plate is L-butted to the king/jack
        studs rather than T-butted, allowing it to be split at the opening.
        No effect on windows.
    """

    FEATURE_TYPE = Opening
    BEAM_CATEGORY_NAMES = ["header", "king_stud", "jack_stud"]
    NAME = "OpeningPopulatorAgent"
    INTERNAL_JOINT_RULES = [
        CategoryRule(TButtJoint, "header", "king_stud"),
        CategoryRule(LButtJoint, "jack_stud", "header", mill_depth=5.0),
        CategoryRule(TButtJoint, "sill", "jack_stud", mill_depth=5.0),
        CategoryRule(TButtJoint, "sill", "king_stud", mill_depth=5.0),
    ]
    EXTERNAL_JOINT_RULES = [
        CategoryRule(TButtJoint, "jack_stud", "bottom_plate_beam", mill_depth=5.0),
        CategoryRule(TButtJoint, "jack_stud", "top_plate_beam", mill_depth=5.0),
        CategoryRule(TButtJoint, "jack_stud", "edge_stud"),
        CategoryRule(TButtJoint, "jack_stud", "header", mill_depth=5.0),
        CategoryRule(TButtJoint, "king_stud", "bottom_plate_beam", mill_depth=5.0),
        CategoryRule(TButtJoint, "king_stud", "top_plate_beam", mill_depth=5.0),
        CategoryRule(TButtJoint, "king_stud", "edge_stud"),
        CategoryRule(TButtJoint, "king_stud", "header", mill_depth=5.0),
        CategoryRule(TButtJoint, "king_stud", "sill", mill_depth=5.0),
        CategoryRule(TButtJoint, "stud", "header"),
        # HACK: the following are for when the studs extend and hit a corner in the edge beams. This should eventually be replaced by proper Y_TOPO/K_TOPO joint rules.
        CategoryRule(LButtJoint, "jack_stud", "top_plate_beam", mill_depth=0.0, max_distance=1.0, modify_cross=False),
        CategoryRule(LButtJoint, "jack_stud", "bottom_plate_beam", mill_depth=0.0, max_distance=1.0, modify_cross=False),
        CategoryRule(LButtJoint, "jack_stud", "edge_stud", mill_depth=0.0, max_distance=1.0, modify_cross=False),
        CategoryRule(LButtJoint, "king_stud", "top_plate_beam", mill_depth=0.0, max_distance=1.0, modify_cross=False),
        CategoryRule(LButtJoint, "king_stud", "bottom_plate_beam", mill_depth=0.0, max_distance=1.0, modify_cross=False),
        CategoryRule(LButtJoint, "king_stud", "edge_stud", mill_depth=0.0, max_distance=1.0, modify_cross=False),
    ]
    BOUNDARY_TYPE = AgentBoundaryType.EXCLUSIVE

    def __init__(
        self,
        feature: Opening = None,
        element_layers=None,
        trimming_layers=None,
        header_width: Optional[float] = None,
        sill_width: Optional[float] = None,
        king_stud_width: Optional[float] = None,
        jack_stud_width: Optional[float] = None,
        internal_joint_overrides=None,
        external_joint_overrides=None,
        lintel_posts: bool = False,
        split_bottom_plate_beam: bool = False,
        **kwargs,
    ):
        # type: (Opening, list, list, Optional[float], Optional[float], Optional[float], Optional[float], Optional[list], Optional[list], bool, bool) -> None
        super().__init__(feature, element_layers, trimming_layers, internal_joint_overrides, external_joint_overrides, **kwargs)
        self.beam_widths["header"] = header_width
        self.beam_widths["sill"] = sill_width
        self.beam_widths["king_stud"] = king_stud_width
        self.beam_widths["jack_stud"] = jack_stud_width
        self.lintel_posts = lintel_posts
        self.split_bottom_plate_beam = split_bottom_plate_beam
        self._split_rules_applied = False

    @property
    def __data__(self):
        data = super().__data__
        data["header_width"] = self.beam_widths.get("header")
        data["sill_width"] = self.beam_widths.get("sill")
        data["king_stud_width"] = self.beam_widths.get("king_stud")
        data["jack_stud_width"] = self.beam_widths.get("jack_stud")
        data["lintel_posts"] = self.lintel_posts
        data["split_bottom_plate_beam"] = self.split_bottom_plate_beam
        return data

    @property
    def feature(self):
        return self._feature

    @feature.setter
    def feature(self, value):
        self._feature = value
        if type(self) is OpeningPopulatorAgent and value is not None:
            subclass = _AGENT_CLASS_BY_OPENING_TYPE.get(value.opening_type)
            if subclass is not None:
                self.__class__ = subclass

    @property
    def opening(self):
        """The opening feature that drives element placement (alias for ``feature``)."""
        return self.feature

    @property
    def opening_type(self):
        """:class:`~compas_timber.panel_features.OpeningType` of the bound opening, or ``None`` if unbound."""
        return self.opening.opening_type if self.opening is not None else None

    def cull_beam_segment(self, beam: Beam, layer=None) -> bool:
        """Return ``True`` if *beam* is a stud that overlaps a king or jack stud.

        Only called from :meth:`trim_elements` on segments that already
        survived the midpoint / outline-crossing cull.  The check is restricted
        to ``"stud"`` category beams so that plate-beam segments (``"top_plate_beam"``,
        ``"bottom_plate_beam"``, ``"edge_stud"``, …) flanking the opening are
        never accidentally culled by AABB overlap with the king/jack studs.
        """
        if beam.attributes.get("category") != "stud":
            return False
        return self._cull_stud(beam, layer)

    def _offset_frame_polyline(self, frame_polyline: Polyline) -> None:
        """Hook: adjust *frame_polyline* points in place. No-op by default.

        :class:`DoorPopulatorAgent` overrides this to offset the sill-side
        points so a door's (nonexistent) sill edge doesn't z-fight with the
        bottom plate.
        """

    def _add_type_specific_elements(self, layer, frame_polyline_a, frame_polyline_b, segments, layer_elements) -> None:
        """Hook: append type-specific elements to *layer_elements* in place. No-op by default.

        :class:`WindowPopulatorAgent` overrides this to add the sill beam.
        """

    def _build_frame(self, layer):
        """Build this opening's frame polyline and outline segments on *layer*.

        Shared by :meth:`generate_elements_for_layer` and
        :meth:`_compute_outline_for_layer` so the frame geometry (including
        the type-specific offset from :meth:`_offset_frame_polyline`) is
        computed identically by both.
        """
        frame_polyline_a, frame_polyline_b = self._create_frame_polylines(self.feature, layer)
        frame_polyline = self._create_frame_polyline(frame_polyline_a, frame_polyline_b, layer)
        self._offset_frame_polyline(frame_polyline)
        segments = [line for line in frame_polyline.lines]
        segments[2].flip()  # align to panel populator stud direction
        return frame_polyline_a, frame_polyline_b, segments

    def generate_elements_for_layer(self, layer):
        frame_polyline_a, frame_polyline_b, segments = self._build_frame(layer)

        layer_elements = []
        jack_offset = 0

        if self.lintel_posts:
            jack_offset = self.beam_widths["jack_stud"] / 2
            layer_elements.append(self.beam_from_category(segments[0].translated([-jack_offset, 0, 0]), "jack_stud", layer=layer, name="left_jack_stud"))
            layer_elements.append(self.beam_from_category(segments[2].translated([jack_offset, 0, 0]), "jack_stud", layer=layer, name="right_jack_stud"))

        king_offset = self.beam_widths["king_stud"] / 2
        layer_elements.append(self.beam_from_category(segments[0].translated([-(king_offset + jack_offset * 2), 0, 0]), "king_stud", layer=layer, name="left_king_stud"))
        layer_elements.append(self.beam_from_category(segments[2].translated([king_offset + jack_offset * 2, 0, 0]), "king_stud", layer=layer, name="right_king_stud"))
        header_offset = self.beam_widths["header"] / 2
        header = self.beam_from_category(segments[1].translated([0, header_offset, 0]), "header", layer=layer, name="header")
        layer_elements.append(header)

        # Apply longitudinal cut for an angled header.
        if not TOL.is_zero(frame_polyline_a[1][1] - frame_polyline_b[1][1]):
            plane = Plane.from_points([frame_polyline_a[1], frame_polyline_a[2], frame_polyline_b[1]])
            long_cut = LongitudinalCutProxy.from_plane_and_beam(plane, header, is_joinery=False)
            header.add_features(long_cut)

        self._add_type_specific_elements(layer, frame_polyline_a, frame_polyline_b, segments, layer_elements)

        return layer_elements, self._compute_outline_for_layer(layer)

    def _compute_outline_for_layer(self, layer):
        """Compute this opening's footprint outline on *layer* (no beams generated).

        The footprint is the opening's frame polyline at the layer's
        through-thickness position, so it is recomputed per layer (correct even
        for openings whose two faces differ in plan).  Used both for the framing
        layer's outline and — via :meth:`define_trimming_outlines` — for every
        layer the opening only trims.
        """
        _, _, segments = self._build_frame(layer)
        extend_line_segments(segments, close_loop=True)
        return join_polyline_segments(segments, close_loop=True)[0][0]

    def _create_frame_polylines(self, opening: Opening, layer) -> tuple[Polyline, Polyline]:

        if "king_stud" not in self.beam_widths:
            raise ValueError("Beam width for 'king_stud' not set — use get_agent_from_feature() to construct this agent so beam widths are filled automatically.")
        opening_a_pts = []
        opening_b_pts = []
        for pt_a, pt_b in zip(opening.outline_a.points, opening.outline_b.points):

            line = Line(pt_a, pt_b)
            int_a = intersection_line_plane(line, Plane(layer.outline_a[0], [0,0,1]))
            int_b = intersection_line_plane(line, Plane(layer.outline_b[0], [0,0,1]))
            if int_a:
                opening_a_pts.append(int_a)
            if int_b:
                opening_b_pts.append(int_b)
        box_a = Box.from_points(opening_a_pts)
        box_b = Box.from_points(opening_b_pts)
        frame_polyline_a = Polyline([box_a.corner(0), box_a.corner(1), box_a.corner(2), box_a.corner(3), box_a.corner(0)])
        frame_polyline_b = Polyline([box_b.corner(0), box_b.corner(1), box_b.corner(2), box_b.corner(3), box_b.corner(0)])
        return frame_polyline_a, frame_polyline_b

    def _create_frame_polyline(self, frame_polyline_a: Polyline, frame_polyline_b: Polyline, layer) -> Polyline:
        """Bounding rectangle aligned orthogonal to the panel.orientation."""
        center_height = layer.center_height
        return Polyline(
            [
                Point(frame_polyline_a.points[0][0], max(frame_polyline_a.points[0][1], frame_polyline_b.points[0][1]), center_height),
                Point(frame_polyline_a.points[1][0], min(frame_polyline_a.points[1][1], frame_polyline_b.points[1][1]), center_height),
                Point(frame_polyline_a.points[2][0], min(frame_polyline_a.points[2][1], frame_polyline_b.points[2][1]), center_height),
                Point(frame_polyline_a.points[3][0], max(frame_polyline_a.points[3][1], frame_polyline_b.points[3][1]), center_height),
                Point(frame_polyline_a.points[4][0], max(frame_polyline_a.points[4][1], frame_polyline_b.points[4][1]), center_height),
            ]
        )

    def extend_elements(self, boundary_agents, layer):
        """Extend king/jack studs to neighboring boundaries — one layer at a time.

        The opening may frame on several layers.  Each layer's king/jack studs
        are extended only against the peer agents *on that same layer*, so a
        stud is never extended to a boundary that belongs to a different layer.
        """
        layer_elements = self.elements_by_layer.get(layer, [])
        king_studs = [b for b in layer_elements if b.attributes.get("category") == "king_stud"]
        jack_studs = [b for b in layer_elements if b.attributes.get("category") == "jack_stud"]
        agent_layer_boundaries = [a.outline_by_layer[layer] for a in boundary_agents]
        if not (king_studs or jack_studs):
            return
        for king_stud in king_studs:
            if king_stud is not None:
                ConnectionSolver2D.extend_beam_to_polylines(king_stud, agent_layer_boundaries)

        for jack_stud in jack_studs:
            if jack_stud is not None:
                ConnectionSolver2D.extend_beam_to_polylines(jack_stud, agent_layer_boundaries, only_start=True)

    # ==========================================================================
    # Cross-layer trimming
    # ==========================================================================

    def _cull_stud(self, stud: Beam2D, layer=None) -> bool:
        """Determine whether a stud coincides with a king or jack stud and should be culled."""
        layer_elements = self.elements_by_layer.get(layer, []) if layer is not None else self.elements
        king_and_jack = [b for b in layer_elements if b.attributes.get("category") in ("king_stud", "jack_stud")]
        for b in king_and_jack:
            if aabb_overlap(b, stud):
                return True
        return False

    def trim_plate(self, plate: Plate) -> None:
        """Apply the opening contour to the given plate.

        Parameters
        ----------
        plate : :class:`compas_timber.elements.Plate`
            The plate to which the opening will be applied.
        """
        opening_a = Polyline([p for p in self.feature.outline_a])
        opening_b = Polyline([p for p in self.feature.outline_b])
        lines = [Line(pt_a, pt_b) for pt_a, pt_b in zip(opening_a.points, opening_b.points)]
        outline_a_projected = Polyline([intersection_line_plane(line, plate.planes[0]) for line in lines])
        outline_b_projected = Polyline([intersection_line_plane(line, plate.planes[1]) for line in lines])
        free_contour = FreeContour.from_top_bottom_and_elements(outline_a_projected, outline_b_projected, plate, interior=True, is_joinery=False)
        plate.add_feature(free_contour)
        return [plate]

    def create_joint_defs(self) -> list[DirectRule]:
        """Build within-agent :class:`~timber_design.workflow.DirectRule` joint defs.

        With *layer* given, only element pairs on that layer are considered;
        otherwise every framing layer is.  :attr:`joint_defs` is reset on each
        call and the freshly built list is returned, so the populator can drive
        this per layer without defs accumulating across layers.
        """
        self.joint_defs = []
        for layer in self.element_layers:
            element_dict = {}

            for element in self.elements_by_layer[layer]:
                category = element.attributes.get("category")
                if category:
                    if category not in element_dict:
                        element_dict[category] = [element]
                    else:
                        element_dict[category].append(element)

            header = element_dict.get("header")[0]
            kings = element_dict.get("king_stud")
            for ks in kings:
                rule = self.get_direct_rule_from_elements(header, ks)
                if rule is not None:
                    self.joint_defs.append(rule)

            jacks = element_dict.get("jack_stud")
            if jacks:
                for js in jacks:
                    rule = self.get_direct_rule_from_elements(header, js)
                    if rule is not None:
                        self.joint_defs.append(rule)
            sill = element_dict.get("sill")
            if not sill:
                return self.joint_defs
            print("sill found")
            sill_sides = jacks or kings
            for ss in sill_sides:
                print(ss.attributes.get("category"))
                rule = self.get_direct_rule_from_elements(sill[0], ss)
                if rule is not None:
                        self.joint_defs.append(rule)
        return self.joint_defs

class DoorPopulatorAgent(OpeningPopulatorAgent):
    """A :class:`OpeningPopulatorAgent` for door openings: no sill, optional split bottom plate.

    See :class:`OpeningPopulatorAgent` for the shared header/king/jack-stud
    framing.  A door's bottom-plate beam is normally T-butted to the king (or
    jack) studs, like any other stud; setting :attr:`split_bottom_plate_beam`
    swaps that cross-agent joint for an L-butt instead, so the bottom plate
    can be split and removed at the opening rather than notched around it.
    """

    NAME = "DoorPopulatorAgent"

    def _offset_frame_polyline(self, frame_polyline: Polyline) -> None:
        # Offset to avoid z-fighting with the bottom plate: doors have no
        # sill, so their frame's bottom edge otherwise sits flush on it.
        frame_polyline.points[0].y -= 100
        frame_polyline.points[3].y -= 100
        frame_polyline.points[4].y -= 100

    def generate_elements_for_layer(self, layer):
        self._apply_split_bottom_plate_rules()
        return super().generate_elements_for_layer(layer)

    def _apply_split_bottom_plate_rules(self):
        """Swap in an L-butt rule at the king/jack-stud base for split-bottom-plate doors.

        Deferred from ``__init__`` because it depends on ``opening_type`` (and
        therefore on the bound feature) — for direct construction the feature
        may not be bound yet.  Runs once, at the start of generation.

        The (king_stud/jack_stud, bottom_plate_beam) joint is between elements
        from two different agents (the bottom plate belongs to the edge
        agent), so it is a **cross-agent** rule and must be edited on
        :attr:`external_rules`, not :attr:`internal_rules`.
        """
        if self._split_rules_applied:
            return
        self._split_rules_applied = True
        if not self.split_bottom_plate_beam:
            return
        main = "jack_stud" if self.lintel_posts else "king_stud"
        self.external_rules = [r for r in self.external_rules if not (r.category_a == main and r.category_b == "bottom_plate_beam")]
        self.external_rules.append(CategoryRule(LButtJoint, main, "bottom_plate_beam"))

    def split_agent_elements(self, other_agent, layer):
        """Split *other_agent*'s elements on *layer* at this agent's boundary (no culling).

        Each beam is split at outline crossings; all resulting segments are kept.
        Plates receive the agent's feature via :meth:`trim_plate` (which modifies
        them in-place rather than splitting).  Call :meth:`cull_agent_elements`
        in a second pass to discard out-of-zone segments.

        The bottom-plate beam is only split when :attr:`split_bottom_plate_beam`
        is ``True`` — otherwise it is kept whole (unsplit) so it stays
        continuous through the opening.
        """
        result = []
        for element in other_agent.elements_by_layer.get(layer, []):
            if element.is_plate:
                result.extend(self.trim_plate(element))
            if element.is_beam:
                if element.attributes.get("category") == "bottom_plate_beam" and not self.split_bottom_plate_beam:
                    result.append(element)
                    continue
                result.extend(self.split_beam(element, layer))
        other_agent.elements_by_layer[layer] = result

    def cull_agent_elements(self, other_agent, layer):
        """Remove *other_agent*'s elements on *layer* that this agent's zone would discard.

        Applies :meth:`cull_beam` to every beam; elements that return ``True``
        are dropped.  Non-beam elements (plates) are always kept — their trimming
        is handled geometrically by :meth:`split_agent_elements`.

        The bottom-plate beam is only culled when :attr:`split_bottom_plate_beam`
        is ``True`` — otherwise it is never removed, matching
        :meth:`split_agent_elements` leaving it unsplit.
        """
        results = []
        for element in other_agent.elements_by_layer.get(layer, []):
            if element.is_beam and element.attributes.get("category") == "bottom_plate_beam" and not self.split_bottom_plate_beam:
                results.append(element)
            elif not (element.is_beam and self.cull_beam(element, layer)):
                results.append(element)
        other_agent.elements_by_layer[layer] = results


class WindowPopulatorAgent(OpeningPopulatorAgent):
    """A :class:`OpeningPopulatorAgent` for window openings: adds a sill beam."""

    NAME = "WindowPopulatorAgent"
    BEAM_CATEGORY_NAMES = OpeningPopulatorAgent.BEAM_CATEGORY_NAMES + ["sill"]
    INTERNAL_JOINT_RULES = OpeningPopulatorAgent.INTERNAL_JOINT_RULES + [
        CategoryRule(TButtJoint, "sill", "king_stud"),
        CategoryRule(TButtJoint, "sill", "jack_stud"),
    ]
    EXTERNAL_JOINT_RULES = OpeningPopulatorAgent.EXTERNAL_JOINT_RULES + [
        CategoryRule(TButtJoint, "stud", "sill"),
    ]

    def _add_type_specific_elements(self, layer, frame_polyline_a, frame_polyline_b, segments, layer_elements) -> None:
        sill_offset = self.beam_widths["sill"] / 2
        sill = self.beam_from_category(segments[3].translated([0, -sill_offset, 0]), "sill", layer=layer, name="sill")
        layer_elements.append(sill)

        # Apply longitudinal cut for an angled sill.
        if not TOL.is_zero(frame_polyline_a[0][1] - frame_polyline_b[0][1]):
            plane = Plane.from_points([frame_polyline_a[3], frame_polyline_a[4], frame_polyline_b[3]])
            long_cut = LongitudinalCutProxy.from_plane_and_beam(plane, sill, is_joinery=False)
            sill.add_features(long_cut)


_AGENT_CLASS_BY_OPENING_TYPE = {
    OpeningType.DOOR: DoorPopulatorAgent,
    OpeningType.WINDOW: WindowPopulatorAgent,
}
