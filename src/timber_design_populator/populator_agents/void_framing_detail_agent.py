from __future__ import annotations

from typing import Optional

from compas.geometry import Line
from compas.geometry import Plane
from compas.geometry import Polyline
from compas.tolerance import TOL
from compas_timber.connections import LButtJoint
from compas_timber.connections import TButtJoint
from compas_timber.fabrication import LongitudinalCutProxy

from timber_design_populator.connections_2d.beam2d import Beam2D
from timber_design_populator.connections_2d.connection_solver_2d import ConnectionSolver2D
from timber_design_populator.connections_2d.connection_solver_2d import aabb_overlap
from timber_design_populator.populator_agents.populator_agent import PopulatorAgent
from timber_design_populator.populator_agents.populator_agent import AgentBoundaryType
from timber_design_populator.populator_agents.void_geometry import frame_segments
from timber_design_rules import CategoryRule
from timber_design_rules import CompositeRule


class VoidFramingDetailAgent(PopulatorAgent):
    """Frames a void (opening, penetration, niche) in one framing layer.

    Creates the surround of a rectangular frame:

    - **header**: horizontal beam above the void;
    - **king_stud**: full-height studs either side of the void;
    - **jack_stud**: shorter studs between the king studs and the header (lintel posts), when
      :attr:`lintel_posts` is set;
    - **sill**: horizontal beam below the void, when :attr:`sill` is set.

    Headers and sills on a sloped frame get a longitudinal cut.  Regular studs that coincide
    with a king or jack stud are removed, and when :attr:`boundary` is set, it is this agent's
    exclusive boundary on the framing layer: studs inside it are split and removed.

    The agent does not read the feature: a :class:`~timber_design_populator.detail_sets.DetailAgentSet`
    derives the frame, the boundary and the options from the feature and the panel's layers.

    Parameters
    ----------
    frame_outline_a, frame_outline_b : :class:`~compas.geometry.Polyline`
        The frame on the framing layer's two faces (rectangles, populator space).
    boundary : :class:`~compas.geometry.Polyline`, optional
        The exclusive boundary on the framing layer.  ``None``: the framing does not trim the
        framing layer (e.g. a blind niche).
    sill : bool, optional
        Create a sill.
    bottom_offset : float, optional
        Moves the bottom of the frame down, e.g. to keep a door's frame clear of the bottom plate.
    lintel_posts : bool, optional
        Create jack studs under the header.
    split_bottom_plate_beam : bool, optional
        Split the bottom plate at the void and L-butt it to the king (or jack) studs, instead of
        T-butting the studs onto a continuous bottom plate.  Only matters for a void that
        reaches the bottom plate (a door).
    header_width, sill_width, king_stud_width, jack_stud_width : float, optional
        Explicit beam widths; unset ones are filled with the populator's ``standard_beam_width``.
    feature, element_layers, trimming_layers, internal_joint_overrides, external_joint_overrides, composite_joint_overrides : optional
        See :class:`~timber_design_populator.PopulatorAgent`.  The element layer is the framing layer.
    """

    NAME = "VoidFramingDetailAgent"
    IS_DETAIL = True
    BEAM_CATEGORY_NAMES = ["header", "king_stud", "jack_stud", "sill"]
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
        CategoryRule(TButtJoint, "stud", "sill"),
    ]
    # A jack/king stud that extends to the corner where two edge beams meet forms a
    # 3-element TOPO_Y/TOPO_K cluster, resolved as one CompositeJoint.  CompositeRule needs
    # every pairwise candidate in the cluster to match a sub-rule, so the edge_stud/plate
    # corner pair (normally the edge agent's own rule) is included too, at its normal mill
    # depth; only the stud's own joints to the two edge beams get zero depth.
    COMPOSITE_RULES = [
        CompositeRule(
            name="opening_edge_corner",
            max_element_count=3,
            max_distance=1.0,
            rules=[
                CategoryRule(LButtJoint, "jack_stud", "top_plate_beam", mill_depth=0.0, max_distance=1.0, modify_cross=False),
                CategoryRule(LButtJoint, "jack_stud", "bottom_plate_beam", mill_depth=0.0, max_distance=1.0, modify_cross=False),
                CategoryRule(LButtJoint, "jack_stud", "edge_stud", mill_depth=0.0, max_distance=1.0, modify_cross=False),
                CategoryRule(LButtJoint, "king_stud", "top_plate_beam", mill_depth=0.0, max_distance=1.0, modify_cross=False),
                CategoryRule(LButtJoint, "king_stud", "bottom_plate_beam", mill_depth=0.0, max_distance=1.0, modify_cross=False),
                CategoryRule(LButtJoint, "king_stud", "edge_stud", mill_depth=0.0, max_distance=1.0, modify_cross=False),
                CategoryRule(LButtJoint, "edge_stud", "top_plate_beam", mill_depth=10.0, max_distance=1.0),
                CategoryRule(LButtJoint, "edge_stud", "bottom_plate_beam", mill_depth=10.0, max_distance=1.0),
            ],
        ),
    ]
    BOUNDARY_TYPE = AgentBoundaryType.EXCLUSIVE

    def __init__(
        self,
        frame_outline_a: Optional[Polyline] = None,
        frame_outline_b: Optional[Polyline] = None,
        boundary: Optional[Polyline] = None,
        sill: bool = False,
        bottom_offset: float = 0.0,
        lintel_posts: bool = False,
        split_bottom_plate_beam: bool = False,
        header_width: Optional[float] = None,
        sill_width: Optional[float] = None,
        king_stud_width: Optional[float] = None,
        jack_stud_width: Optional[float] = None,
        feature=None,
        element_layers=None,
        trimming_layers=None,
        internal_joint_overrides=None,
        external_joint_overrides=None,
        composite_joint_overrides=None,
        **kwargs,
    ):
        super().__init__(
            element_layers=element_layers,
            trimming_layers=trimming_layers,
            feature=feature,
            internal_joint_overrides=internal_joint_overrides,
            external_joint_overrides=external_joint_overrides,
            composite_joint_overrides=composite_joint_overrides,
            **kwargs,
        )
        self.frame_outline_a = frame_outline_a
        self.frame_outline_b = frame_outline_b
        self.boundary = boundary
        self.sill = sill
        self.bottom_offset = bottom_offset
        self.lintel_posts = lintel_posts
        self.split_bottom_plate_beam = split_bottom_plate_beam
        self.beam_widths["header"] = header_width
        self.beam_widths["sill"] = sill_width
        self.beam_widths["king_stud"] = king_stud_width
        self.beam_widths["jack_stud"] = jack_stud_width
        self._apply_bottom_plate_rule()

    @property
    def __data__(self):
        data = super().__data__
        data["frame_outline_a"] = self.frame_outline_a
        data["frame_outline_b"] = self.frame_outline_b
        data["boundary"] = self.boundary
        data["sill"] = self.sill
        data["bottom_offset"] = self.bottom_offset
        data["lintel_posts"] = self.lintel_posts
        data["split_bottom_plate_beam"] = self.split_bottom_plate_beam
        data["header_width"] = self.beam_widths.get("header")
        data["sill_width"] = self.beam_widths.get("sill")
        data["king_stud_width"] = self.beam_widths.get("king_stud")
        data["jack_stud_width"] = self.beam_widths.get("jack_stud")
        return data

    # ------------------------------------------------------------------
    # generation
    # ------------------------------------------------------------------

    def generate_elements_for_layer(self, layer):
        a, b = self.frame_outline_a, self.frame_outline_b
        segments = frame_segments(a, b, layer.center_height, self.bottom_offset)
        elements = []
        jack_offset = 0
        if self.lintel_posts:
            jack_offset = self.beam_width("jack_stud") / 2
            elements.append(self.beam_from_category(segments[0].translated([-jack_offset, 0, 0]), "jack_stud", layer=layer, name="left_jack_stud"))
            elements.append(self.beam_from_category(segments[2].translated([jack_offset, 0, 0]), "jack_stud", layer=layer, name="right_jack_stud"))

        king_offset = self.beam_width("king_stud") / 2
        elements.append(self.beam_from_category(segments[0].translated([-(king_offset + jack_offset * 2), 0, 0]), "king_stud", layer=layer, name="left_king_stud"))
        elements.append(self.beam_from_category(segments[2].translated([king_offset + jack_offset * 2, 0, 0]), "king_stud", layer=layer, name="right_king_stud"))

        header_seg = segments[1].translated([0, self.beam_width("header") / 2, 0])
        if self.lintel_posts:
            header_seg = Line(header_seg.start - [self.beam_width("jack_stud"), 0, 0], header_seg.end + [self.beam_width("jack_stud"), 0, 0])
        header = self.beam_from_category(header_seg, "header", layer=layer, name="header")
        if not TOL.is_zero(a[1][1] - b[1][1]):  # sloped header
            header.add_features(LongitudinalCutProxy.from_plane_and_beam(Plane.from_points([a[1], a[2], b[1]]), header, is_joinery=False))
        elements.append(header)

        if self.sill:
            sill = self.beam_from_category(segments[3].translated([0, -self.beam_width("sill") / 2, 0]), "sill", layer=layer, name="sill")
            if not TOL.is_zero(a[0][1] - b[0][1]):  # sloped sill
                sill.add_features(LongitudinalCutProxy.from_plane_and_beam(Plane.from_points([a[3], a[4], b[3]]), sill, is_joinery=False))
            elements.append(sill)

        return elements, self.boundary

    def compute_outline_for_layer(self, layer):
        return self.boundary if layer in self.element_layers else None

    def extend_elements(self, boundary_outlines, layer) -> None:
        """Extend the king studs to the neighbouring boundaries, and the jack studs downwards only."""
        for beam in self.elements_for_layer(layer):
            category = beam.attributes.get("category")
            if category == "king_stud":
                ConnectionSolver2D.extend_beam_to_polylines(beam, boundary_outlines)
            elif category == "jack_stud":
                ConnectionSolver2D.extend_beam_to_polylines(beam, boundary_outlines, only_start=True)

    # ------------------------------------------------------------------
    # trimming peers
    # ------------------------------------------------------------------

    def split_beam(self, beam: Beam2D) -> list[Beam2D]:
        """Split like any exclusive agent, except the bottom plate, which stays whole unless it is to be split."""
        if beam.attributes.get("category") == "bottom_plate_beam" and not self.split_bottom_plate_beam:
            return [beam]
        return super().split_beam(beam)

    def cull_beam(self, beam: Beam2D) -> bool:
        """Remove beams inside the boundary (except a bottom plate kept whole) and studs coinciding with a king or jack stud."""
        category = beam.attributes.get("category")
        if category == "bottom_plate_beam" and not self.split_bottom_plate_beam:
            return False
        if super().cull_beam(beam):
            return True
        if category == "stud":
            own = [b for b in self.elements_for_layer(beam.parent) if b.attributes.get("category") in ("king_stud", "jack_stud")]
            return any(aabb_overlap(b, beam) for b in own)
        return False

    def _apply_bottom_plate_rule(self):
        """One rule for the (king or jack stud, bottom_plate_beam) joint: an L-butt when the bottom plate is split, else a T-butt.

        This joint is between this agent's stud and the edge agent's bottom plate, so it is an
        external rule.  It replaces the base rule for that pair outright, whatever its topology.
        """
        main = "jack_stud" if self.lintel_posts else "king_stud"
        if self.split_bottom_plate_beam:
            rule = CategoryRule(LButtJoint, main, "bottom_plate_beam")
        else:
            rule = CategoryRule(TButtJoint, main, "bottom_plate_beam", mill_depth=5.0)
        self.external_rules = [r for r in self.external_rules if not (isinstance(r, CategoryRule) and r.category_a == main and r.category_b == "bottom_plate_beam")] + [rule]
