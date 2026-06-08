
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
from compas_timber.utils import extend_line_segments
from compas_timber.utils import join_polyline_segments

from timber_design.populators.agent_intersection import extend_beam_to_closest_agent_outlines
from timber_design.populators.beam2d import Beam2D
from timber_design.populators.connection_solver_2d import aabb_overlap
from timber_design.populators.connection_solver_2d import aabb_overlap_x
from timber_design.populators.populator_agents.feature_agent import FeatureAgent
from timber_design.populators.populator_agents.layer_agent import AgentBoundaryType
from timber_design.populators.populator_agents.layer_agent import LayerAgent
from timber_design.workflow import CategoryRule


class OpeningPopulatorAgent(FeatureAgent):
    """Generates the structural surround for a door or window opening.

    Creates the following beam categories (depending on opening type and
    ``params``):

    - **header** — horizontal beam above the opening.
    - **sill** — horizontal beam below the opening (windows only).
    - **king_stud** — full-height vertical studs flanking the opening.
    - **jack_stud** — shorter vertical studs (lintel posts) between the king
      studs and the header/sill, created only when ``params.lintel_posts`` is
      ``True``.

    The agent computes its :attr:`~LayerAgent.outline` from the
    outer edges of the king (and jack) studs and the header/sill, so that
    peer agents (studs) can trim their elements at the opening boundary via
    :meth:`~timber_design.populators.PopulatorAgent.trim_elements`.

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
    opening_type : str
        ``"door"`` or ``"window"``, read from the opening feature.
    lintel_posts : bool
        Whether jack studs (lintel posts) are generated.
    split_bottom_plate_beam : bool
        For doors: if ``True`` the bottom plate is L-butted to the king/jack
        studs rather than T-butted, allowing it to be split at the opening.
    header : :class:`~timber_design.populators.Beam2D`
        The header beam (read-only property).
    sill : :class:`~timber_design.populators.Beam2D` or None
        The sill beam (``None`` for door openings).
    king_studs : list[:class:`~timber_design.populators.Beam2D`]
        Both king studs.
    jack_studs : list[:class:`~timber_design.populators.Beam2D`]
        Jack studs (empty list when ``lintel_posts`` is ``False``).
    left_king_stud : :class:`~timber_design.populators.Beam2D` or None
        King stud with the smaller X coordinate.
    right_king_stud : :class:`~timber_design.populators.Beam2D` or None
        King stud with the larger X coordinate.
    """

    FEATURE_TYPE = Opening
    BEAM_CATEGORY_NAMES = ["header", "sill", "king_stud", "jack_stud"]
    NAME = "OpeningPopulatorAgent"
    INTERNAL_JOINT_RULES = [
        CategoryRule(TButtJoint, "header", "king_stud"),
        CategoryRule(TButtJoint, "sill", "king_stud"),
        CategoryRule(TButtJoint, "sill", "jack_stud"),
        CategoryRule(LButtJoint, "jack_stud", "header", mill_depth=5.0),
    ]
    EXTERNAL_JOINT_RULES = [
        CategoryRule(TButtJoint, "jack_stud", "bottom_plate_beam", mill_depth=5.0),
        CategoryRule(TButtJoint, "jack_stud", "top_plate_beam", mill_depth=5.0),
        CategoryRule(TButtJoint, "jack_stud", "edge_stud"),
        CategoryRule(TButtJoint, "jack_stud", "header", mill_depth=5.0),
        CategoryRule(TButtJoint, "jack_stud", "sill", mill_depth=5.0),
        CategoryRule(TButtJoint, "king_stud", "bottom_plate_beam", mill_depth=5.0),
        CategoryRule(TButtJoint, "king_stud", "top_plate_beam", mill_depth=5.0),
        CategoryRule(TButtJoint, "king_stud", "edge_stud"),
        CategoryRule(TButtJoint, "king_stud", "header", mill_depth=5.0),
        CategoryRule(TButtJoint, "king_stud", "sill", mill_depth=5.0),
        CategoryRule(TButtJoint, "stud", "header"),
        CategoryRule(TButtJoint, "stud", "sill"),
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
    ):
        # type: (Opening, list, list, Optional[float], Optional[float], Optional[float], Optional[float], Optional[list], Optional[list], bool, bool) -> None
        super().__init__(feature, element_layers, trimming_layers, internal_joint_overrides, external_joint_overrides)
        self.beam_widths["header"] = header_width
        self.beam_widths["sill"] = sill_width
        self.beam_widths["king_stud"] = king_stud_width
        self.beam_widths["jack_stud"] = jack_stud_width
        self.lintel_posts = lintel_posts
        self.split_bottom_plate_beam = split_bottom_plate_beam
        self.sill_angle = 0.0
        self.header_angle = 0.0
        # Feature-dependent rule setup is deferred until the feature is bound and
        # generation starts (see _apply_split_bottom_plate_rules): this agent is
        # often constructed as a prototype with ``feature=None`` and the concrete
        # feature is assigned later, so nothing here may dereference ``feature``.
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
    def opening(self):
        """The opening feature that drives element placement (alias for ``feature``)."""
        return self.feature

    @property
    def opening_type(self):
        """``"door"`` / ``"window"`` of the bound opening, or ``None`` if unbound."""
        return self.opening.opening_type if self.opening is not None else None

    def _apply_split_bottom_plate_rules(self):
        """Swap in L-butt rules at the king/jack-stud base for split-bottom-plate doors.

        Deferred from ``__init__`` because it depends on ``opening_type`` (and
        therefore on the bound feature).  Runs once, at the start of generation.
        """
        if self._split_rules_applied:
            return
        self._split_rules_applied = True
        if not (self.opening_type == "door" and self.split_bottom_plate_beam):
            return
        main = "jack_stud" if self.lintel_posts else "king_stud"
        self.internal_rules = [r for r in self.internal_rules if not (r.category_a == main and r.category_b == "bottom_plate_beam")]
        self.internal_rules.append(CategoryRule(LButtJoint, main, "bottom_plate_beam"))

    def cull_beam_segment(self, beam: Beam) -> bool:
        """Return ``True`` if *beam* is a stud that overlaps a king or jack stud.

        Only called from :meth:`trim_elements` on segments that already
        survived the midpoint / outline-crossing cull.  The check is restricted
        to ``"stud"`` category beams so that plate-beam segments (``"top_plate_beam"``,
        ``"bottom_plate_beam"``, ``"edge_stud"``, …) flanking the opening are
        never accidentally culled by AABB overlap with the king/jack studs.
        """
        if beam.attributes.get("category") != "stud":
            return False
        return self._cull_stud(beam)

    def generate_elements_for_layer(self, layer):
        self._apply_split_bottom_plate_rules()

        frame_polyline_a, frame_polyline_b = self._create_frame_polylines(self.feature, layer)
        frame_polyline = self._create_frame_polyline(frame_polyline_a, frame_polyline_b, layer)
        if self.opening_type == "door":
            frame_polyline.points[0].y -= 100  # offset to avoid z-fighting
            frame_polyline.points[3].y -= 100
            frame_polyline.points[4].y -= 100
        segments = [line for line in frame_polyline.lines]
        segments[2].flip()  # align to panel populator stud direction

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

        # Window-only sill
        sill = None
        if self.opening_type == "window":
            sill_offset = self.beam_widths["sill"] / 2
            sill = self.beam_from_category(segments[3].translated([0, -sill_offset, 0]), "sill", layer=layer, name="sill")
            layer_elements.append(sill)

        # Apply longitudinal cuts for angled sills / headers (use local vars —
        # self.sill / self.header search self.elements which is not yet updated).
        if sill is not None and not TOL.is_zero(frame_polyline_a[0][1] - frame_polyline_b[0][1]):
            plane = Plane.from_points([frame_polyline_a[3], frame_polyline_a[4], frame_polyline_b[3]])
            long_cut = LongitudinalCutProxy.from_plane_and_beam(plane, sill, is_joinery=False)
            sill.add_features(long_cut)

        if not TOL.is_zero(frame_polyline_a[1][1] - frame_polyline_b[1][1]):
            plane = Plane.from_points([frame_polyline_a[1], frame_polyline_a[2], frame_polyline_b[1]])
            long_cut = LongitudinalCutProxy.from_plane_and_beam(plane, header, is_joinery=False)
            header.add_features(long_cut)

        extend_line_segments(segments, close_loop=True)
        outline = join_polyline_segments(segments, close_loop=True)[0][0]
        return layer_elements, outline

    @property
    def header(self):
        return [b for b in self.elements if b.attributes.get("category") == "header"][0]

    @property
    def sill(self):
        sills = [b for b in self.elements if b.attributes.get("category") == "sill"]
        return sills[0] if sills else None

    @property
    def king_studs(self):
        return [b for b in self.elements if b.attributes.get("category") == "king_stud"]

    @property
    def jack_studs(self):
        return [b for b in self.elements if b.attributes.get("category") == "jack_stud"]

    @property
    def left_king_stud(self):
        return min(self.king_studs, key=lambda s: s.frame.point[0]) if self.king_studs else None

    @property
    def right_king_stud(self):
        return max(self.king_studs, key=lambda s: s.frame.point[0]) if self.king_studs else None

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

    def extend_elements(self, layer_agents, layer):
        """Extend king/jack studs to neighboring boundaries — one layer at a time.

        The opening may frame on several layers.  Each layer's king/jack studs
        are extended only against the peer agents *on that same layer*, so a
        stud is never extended to a boundary that belongs to a different layer.
        """
        layer_elements = self.elements_by_layer.get(layer, [])
        king_studs = [b for b in layer_elements if b.attributes.get("category") == "king_stud"]
        jack_studs = [b for b in layer_elements if b.attributes.get("category") == "jack_stud"]
        agent_layer_boundaries = [a.outline_by_layer[layer] for a in layer_agents]
        if not (king_studs or jack_studs):
            return
        for king_stud in king_studs:
            if king_stud is not None:
                print("extending_king_stud")
                extend_beam_to_closest_agent_outlines(king_stud, agent_layer_boundaries)

        for jack_stud in jack_studs:
            if jack_stud is not None:
                print("extending_king_stud")

                extend_beam_to_closest_agent_outlines(jack_stud, agent_layer_boundaries, only_start=True)

    # ==========================================================================
    # Cross-layer trimming
    # ==========================================================================

    def _cull_stud(self, stud: Beam2D) -> bool:
        """Determine whether a stud coincides with a king or jack stud and should be culled."""
        return any([aabb_overlap(b, stud) for b in self.king_studs + self.jack_studs])

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
