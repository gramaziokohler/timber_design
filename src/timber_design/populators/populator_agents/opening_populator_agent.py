from dataclasses import dataclass

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
from compas_timber.utils import extend_line_segments
from compas_timber.utils import join_polyline_segments
from compas_timber.fabrication.free_contour import FreeContour
from compas_timber.panel_features import Opening

from timber_design.populators.agent_intersection import extend_beam_to_closest_agents
from timber_design.populators.beam2d import Beam2D
from timber_design.populators.connection_solver_2d import aabb_overlap
from timber_design.populators.connection_solver_2d import aabb_overlap_x
from timber_design.populators.layer import Layer
from timber_design.populators.populator_agents.populator_agent import FeatureBoundaryType
from timber_design.populators.populator_agents.populator_agent import FeaturePopulatorAgent
from timber_design.populators.populator_agents.populator_agent import FeaturePopulatorAgentConfig
from timber_design.populators.populator_agents.populator_agent import PopulatorAgent
from timber_design.workflow import CategoryRule


@dataclass
class OpeningPopulatorAgentConfig(FeaturePopulatorAgentConfig):
    FEATURE_TYPE = Opening
    feature: Opening = None
    lintel_posts: bool = False
    split_bottom_plate_beam: bool = False

    @property
    def __data__(self):
        data = super().__data__
        data["feature"] = self.feature
        data["lintel_posts"] = self.lintel_posts
        data["split_bottom_plate_beam"] = self.split_bottom_plate_beam
        return data


class OpeningPopulatorAgent(FeaturePopulatorAgent):
    """Generates the structural surround for a door or window opening.

    Creates the following beam categories (depending on opening type and
    ``params``):

    - **header** — horizontal beam above the opening.
    - **sill** — horizontal beam below the opening (windows only).
    - **king_stud** — full-height vertical studs flanking the opening.
    - **jack_stud** — shorter vertical studs (lintel posts) between the king
      studs and the header/sill, created only when ``params.lintel_posts`` is
      ``True``.

    The agent computes its :attr:`~PopulatorAgent.outline` from the
    outer edges of the king (and jack) studs and the header/sill, so that
    peer agents (studs) can trim their elements at the opening boundary during
    :meth:`~timber_design.populators.PanelPopulator.trim_within_layer_elements`.

    Its :attr:`~PopulatorAgent.BOUNDARY_TYPE` is
    :attr:`~FeatureBoundaryType.EXCLUSIVE`, meaning that studs whose midpoints
    fall inside the outline are discarded by :meth:`~PopulatorAgent.trim_beam`.

    The opening geometry is supplied via ``params.feature`` (set automatically
    by :meth:`~timber_design.populators.PopulatorAgentConfig.get_agent_from_feature`).
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
    INTERNAL_RULES = [
        CategoryRule(TButtJoint, "header", "king_stud"),
        CategoryRule(TButtJoint, "sill", "king_stud"),
        CategoryRule(TButtJoint, "sill", "jack_stud"),
        CategoryRule(LButtJoint, "jack_stud", "header", mill_depth=5.0),
    ]
    EXTERNAL_RULES = [
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
    ]
    BOUNDARY_TYPE = FeatureBoundaryType.EXCLUSIVE

    def __init__(self, layer, params, feature):
        # type: (Layer, OpeningPopulatorAgentConfig, Opening) -> None
        super().__init__(layer, params, feature)
        self.lintel_posts = params.lintel_posts
        self.split_bottom_plate_beam = params.split_bottom_plate_beam
        self.opening_type = self.opening.opening_type
        self.sill_angle = 0.0
        self.header_angle = 0.0
        # explicit beam attributes — populated by generate_elements()
        if self.opening_type == "door" and self.split_bottom_plate_beam:
            if self.lintel_posts:
                self.internal_rules = [r for r in self.internal_rules if not (r.category_a == "jack_stud" and r.category_b == "bottom_plate_beam")]
                self.internal_rules.append(
                    CategoryRule(
                        LButtJoint,
                        "jack_stud",
                        "bottom_plate_beam",
                    )
                )
            else:
                self.internal_rules = [r for r in self.internal_rules if not (r.category_a == "king_stud" and r.category_b == "bottom_plate_beam")]
                self.internal_rules.append(
                    CategoryRule(
                        LButtJoint,
                        "king_stud",
                        "bottom_plate_beam",
                    )
                )

    @property
    def opening(self):
        """The opening feature that drives element placement.

        Returns ``self.feature``, which is set from ``params.feature`` by the
        base :class:`~timber_design.populators.PopulatorAgent` constructor.
        """
        return self.feature

    def cull_beam_segment(self, beam: Beam) -> bool:
        """determines whether a beam segment should be culled. Typically checks for feature inclusion."""
        if super().cull_beam_segment(beam):
            return True
        # if beam.attributes.get("category", None) == "stud":
        #     return self._cull_stud(beam)
        return False

    def generate_elements(self) -> None:
        """Generate the beams for a opening."""
        print(self.feature.outline_a.points)
        frame_polyline_a, frame_polyline_b = self._create_frame_polylines(self.feature)
        print("frame_polyline_a", frame_polyline_a)
        frame_polyline = self._create_frame_polyline(frame_polyline_a, frame_polyline_b)
        print("frame_polyline", frame_polyline)

        if self.opening_type == "door":
            frame_polyline.points[0].y -= 100  # offset to avoid z-fighting
            frame_polyline.points[3].y -= 100
            frame_polyline.points[4].y -= 100
        segments = [line for line in frame_polyline.lines]
        segments[2].flip()  # align to panel populator stud direction

        # create beams and assign to explicit attributes

        edge_segs = []
        jack_offset = 0
        if self.lintel_posts:
            jack_offset = self.beam_dimensions["jack_stud"][0] / 2
            self.elements.append(self.beam_from_category(segments[0].translated([-jack_offset, 0, 0]), "jack_stud", name="left_jack_stud"))
            self.elements.append(self.beam_from_category(segments[2].translated([jack_offset, 0, 0]), "jack_stud", name="right_jack_stud"))

        king_offset = self.beam_dimensions["king_stud"][0] / 2
        self.elements.append(self.beam_from_category(segments[0].translated([-(king_offset + jack_offset * 2), 0, 0]), "king_stud", name="left_king_stud"))
        self.elements.append(self.beam_from_category(segments[2].translated([king_offset + jack_offset * 2, 0, 0]), "king_stud", name="right_king_stud"))
        print([e.attributes["category"] for e in self.elements])
        
        #edge_segs.append(segments[0].translated([-(king_offset + jack_offset) * 2, 0, 0]))

        header_offset = self.beam_dimensions["header"][0] / 2
        self.elements.append(self.beam_from_category(segments[1].translated([0, header_offset, 0]), "header", name="header"))
        #edge_segs.append(segments[1].translated([0, header_offset * 2, 0]))

        #edge_segs.append(segments[2].translated([(king_offset + jack_offset) * 2, 0, 0]))

        if self.opening_type == "window":
            sill_offset = self.beam_dimensions["sill"][0] / 2
            self.elements.append(self.beam_from_category(segments[3].translated([0, -sill_offset, 0]), "sill", name="sill"))
            #edge_segs.append(segments[3].translated([0, -sill_offset * 2, 0]))

        if self.sill is not None and not TOL.is_zero(frame_polyline_a[0][1] - frame_polyline_b[0][1]):  # angled sill
            plane = Plane.from_points([frame_polyline_a[3], frame_polyline_a[4], frame_polyline_b[3]])
            long_cut = LongitudinalCutProxy.from_plane_and_beam(plane, self.sill, is_joinery=False)
            self.sill.add_features(long_cut)

        if not TOL.is_zero(frame_polyline_a[1][1] - frame_polyline_b[1][1]):  # angled header
            plane = Plane.from_points([frame_polyline_a[1], frame_polyline_a[2], frame_polyline_b[1]])
            long_cut = LongitudinalCutProxy.from_plane_and_beam(plane, self.header, is_joinery=False)
            self.header.add_features(long_cut)

        extend_line_segments(segments, close_loop=True)
        self.outline = join_polyline_segments(segments, close_loop=True)[0][0]

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

    def _create_frame_polylines(self, opening: Opening) -> tuple[Polyline, Polyline]:
        king_dims = self.beam_dimensions.get("king_stud")
        if king_dims:
            thickness = king_dims[0] / 2  # TODO: use frame_thickness
        else:
            raise ValueError("Beam dimensions for 'king_stud' not found.")
        lines = [Line(pt_a, pt_b) for pt_a, pt_b in zip(opening.outline_a.points, opening.outline_b.points)]
        opening_a = Polyline([intersection_line_plane(line, Plane((0, 0, -thickness), (0, 0, 1))) for line in lines])
        opening_b = Polyline([intersection_line_plane(line, Plane((0, 0, thickness), (0, 0, 1))) for line in lines])
        box_a = Box.from_points(opening_a.points)
        box_b = Box.from_points(opening_b.points)
        frame_polyline_a = Polyline([box_a.corner(0), box_a.corner(1), box_a.corner(2), box_a.corner(3), box_a.corner(0)])
        frame_polyline_b = Polyline([box_b.corner(0), box_b.corner(1), box_b.corner(2), box_b.corner(3), box_b.corner(0)])
        return frame_polyline_a, frame_polyline_b

    def _create_frame_polyline(self, frame_polyline_a: Polyline, frame_polyline_b: Polyline) -> Polyline:
        """Bounding rectangle aligned orthogonal to the panel_populator.orientation."""
        return Polyline(
            [
                Point(frame_polyline_a.points[0][0], max(frame_polyline_a.points[0][1], frame_polyline_b.points[0][1]), self.layer_center_height),
                Point(frame_polyline_a.points[1][0], min(frame_polyline_a.points[1][1], frame_polyline_b.points[1][1]), self.layer_center_height),
                Point(frame_polyline_a.points[2][0], min(frame_polyline_a.points[2][1], frame_polyline_b.points[2][1]), self.layer_center_height),
                Point(frame_polyline_a.points[3][0], max(frame_polyline_a.points[3][1], frame_polyline_b.points[3][1]), self.layer_center_height),
                Point(frame_polyline_a.points[4][0], max(frame_polyline_a.points[4][1], frame_polyline_b.points[4][1]), self.layer_center_height),
            ]
        )

    def extend_elements(self, other_agents):
        intersecting_agents = []
        for a in other_agents:
            if aabb_overlap_x(self, a):
                intersecting_agents.append(a)
        if not intersecting_agents:
            return
        self._extend_studs(intersecting_agents)

    def _extend_studs(self, intersecting_agents: list[PopulatorAgent]) -> None:
        """Extend king and jack studs in-place to the nearest neighboring panel boundaries."""
        for king_stud in [s for s in self.king_studs if s is not None]:
            extend_beam_to_closest_agents(king_stud, intersecting_agents)

        for jack_stud in [s for s in self.jack_studs if s is not None]:
            extend_beam_to_closest_agents(jack_stud, intersecting_agents, only_start=True)

    # ==========================================================================
    # Opening element culling functions
    # ==========================================================================

    def affects_layer(self, layer_index: int) -> bool:
        """Return ``True`` for all layers.

        Openings cut through the entire panel cross-section, so the opening
        agent participates in both same-layer trimming (removing studs that
        pass through the opening) and cross-layer trimming (cutting openings
        into sheathing plates on other layers).
        """
        return True

    def _cull_stud(self, stud: Beam2D) -> bool:
        """Determine whether a stud coincides with a king or jack stud and should be culled."""        
        return any([aabb_overlap(b, stud) for b in self.king_studs + self.jack_studs])

    def apply_to_plate(self, plate: Plate) -> None:
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


# Set after both classes are defined so forward reference is resolved
OpeningPopulatorAgentConfig.AGENT_TYPE = OpeningPopulatorAgent
