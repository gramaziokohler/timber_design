from collections import OrderedDict
from typing import Union

from compas.geometry import Box
from compas.geometry import Line
from compas.geometry import Plane
from compas.geometry import Point
from compas.geometry import Polyline
from compas.geometry import Translation
from compas.geometry import intersection_line_plane
from compas.tolerance import TOL
from compas_timber.connections import LButtJoint
from compas_timber.connections import TButtJoint
from compas_timber.elements import Beam
from compas_timber.elements import Opening
from compas_timber.elements import Plate
from compas_timber.fabrication import LongitudinalCutProxy
from compas_timber.fabrication.free_contour import FreeContour
from compas_timber.utils import do_segments_overlap
from compas_timber.utils import extend_line_segments
from compas_timber.utils import get_polyline_segment_perpendicular_vector
from compas_timber.utils import join_polyline_segments

from timber_design.populators import ElementGenerator
from timber_design.populators import FeatureBoundaryType
from timber_design.workflow import CategoryRule
from timber_design.workflow import DirectRule

from timber_design.populators import extend_beam_to_closest_element_generators


class OpeningElementGenerator(ElementGenerator):
    """A panel detail set that uses the edge beams and plates but no studs."""

    BEAM_CATEGORY_NAMES = ["header", "sill", "king_stud", "jack_stud"]
    NAME = "OpeningElementGenerator"
    RULES = [
        CategoryRule(TButtJoint, "header", "king_stud"),
        CategoryRule(TButtJoint, "sill", "jack_stud"),
        CategoryRule(TButtJoint, "jack_stud", "header"),
        CategoryRule(TButtJoint, "jack_stud", "bottom_plate_beam"),
        CategoryRule(TButtJoint, "jack_stud", "edge_stud"),
        CategoryRule(TButtJoint, "king_stud", "bottom_plate_beam"),
        CategoryRule(TButtJoint, "king_stud", "top_plate_beam"),
        CategoryRule(TButtJoint, "king_stud", "header"),
        CategoryRule(TButtJoint, "king_stud", "sill"),
        CategoryRule(TButtJoint, "king_stud", "edge_stud"),
        CategoryRule(TButtJoint, "stud", "header"),
        CategoryRule(TButtJoint, "stud", "sill"),
    ]

    def __init__(
        self,
        opening: Opening,
        standard_beam_width: float,
        lintel_posts: bool = False,
        beam_width_overrides: Union[dict, None] = None,
        joint_rule_overrides: Union[list[CategoryRule], None] = None,
        split_bottom_plate_beam: bool = False,
    ):
        super().__init__(opening, standard_beam_width, beam_width_overrides, joint_rule_overrides)
        self.lintel_posts = lintel_posts
        self.split_bottom_plate_beam = split_bottom_plate_beam
        self.opening_type = opening.opening_type
        self.sill_angle = 0.0
        self.header_angle = 0.0
        if self.opening_type == "door" and self.split_bottom_plate_beam:
            if self.lintel_posts:
                self.rules = [r for r in self.rules if not (r.category_a == "jack_stud" and r.category_b == "bottom_plate_beam")]
                self.rules.append(
                    CategoryRule(
                        LButtJoint,
                        "jack_stud",
                        "bottom_plate_beam",
                    )
                )
            else:
                self.rules = [r for r in self.rules if not (r.category_a == "king_stud" and r.category_b == "bottom_plate_beam")]
                self.rules.append(
                    CategoryRule(
                        LButtJoint,
                        "king_stud",
                        "bottom_plate_beam",
                    )
                )

    def generate_elements(self, feature: Opening):
        """Populates the panel with elements and joints according to the detail set.

        Parameters
        ----------
        feature : :class:`compas_timber.elements.Opening`
            The opening feature to populate.
        """
        return self._create_elements(feature)

    def join_elements(self, populator_direct_rules: list[DirectRule], element_generators: list[ElementGenerator]) -> list[DirectRule]:
        """Join the elements for WindowDetailB."""
        intersecting_groups = [g for g in element_generators if g != self]
        rules = []
        rules.extend(self._get_external_joints(intersecting_groups))
        rules.extend(self._get_internal_joints())
        return [rule for rule in rules if rule is not None]

    def cull_beam_segment(self, beam: Beam) -> bool:
        """determines whether a beam segment should be culled. Typically checks for feature inclusion."""
        if super().cull_beam_segment(beam):
            return True
        if beam.attributes.get("category", None) == "stud":
            return self._cull_stud(beam)
        return False

    def apply_to_plate(self, plate: Plate) -> None:
        """Apply the opening contour to the given plate.

        Parameters
        ----------
        plate : :class:`compas_timber.elements.Plate`
            The plate to which the opening will be applied.
        """
        self.cut_out_of_plate(plate)

    def _create_elements(self, opening: Opening) -> None:
        """Generate the beams for a opening."""
        frame_polyline_a, frame_polyline_b = self._create_frame_polylines(opening)
        frame_polyline = OpeningElementGenerator._create_frame_polyline(frame_polyline_a, frame_polyline_b)

        if self.opening_type == "door":
            frame_polyline.points[0].y -= 100  # offset to avoid z-fighting
            frame_polyline.points[3].y -= 100
            frame_polyline.points[4].y -= 100
        segments = [line for line in frame_polyline.lines]
        segments[2].flip()  # align to panel populator stud direction

        # create beams
        edge_elements = OrderedDict()
        edge_elements[0] = [self.beam_from_category(segments[0], "king_stud", name="left_king_stud")]
        edge_elements[1] = [self.beam_from_category(segments[1], "header")]
        edge_elements[2] = [self.beam_from_category(segments[2], "king_stud", name="right_king_stud")]
        edge_elements[3] = [self.beam_from_category(segments[3], "sill")] if self.opening_type == "window" else []
        if self.lintel_posts:
            edge_elements[0].append(self.beam_from_category(segments[0], "jack_stud", name="left_jack_stud"))
            edge_elements[2].append(self.beam_from_category(segments[2], "jack_stud", name="right_jack_stud"))

        elements = []
        for beams in edge_elements.values():
            elements.extend(beams)

        OpeningElementGenerator._offset_frame_beams(edge_elements, frame_polyline)

        if not TOL.is_zero(frame_polyline_a[0][1] - frame_polyline_b[0][1]):  # angled opening at sill
            sill = edge_elements[3][0]
            plane = Plane.from_points([frame_polyline_a[3], frame_polyline_a[4], frame_polyline_b[3]])
            long_cut = LongitudinalCutProxy.from_plane_and_beam(plane, sill, is_joinery=False)
            sill.add_features(long_cut)

        if not TOL.is_zero(frame_polyline_a[1][1] - frame_polyline_b[1][1]):  # angled opening at header
            header = edge_elements[1][0]
            plane = Plane.from_points([frame_polyline_a[1], frame_polyline_a[2], frame_polyline_b[1]])
            long_cut = LongitudinalCutProxy.from_plane_and_beam(plane, header, is_joinery=False)
            header.add_features(long_cut)

        self.edges = OpeningElementGenerator._get_edge_dict(edge_elements, frame_polyline)
        self.edge_elements = edge_elements
        self.outline = join_polyline_segments(list(self.edges.values()), close_loop=True)
        self.boundary_type = FeatureBoundaryType.EXCLUSIVE

    def _create_frame_polylines(self, opening: Opening) -> tuple[Polyline, Polyline]:
        king_dims = self.beam_dimensions.get("king_stud")
        if king_dims:
            thickness = king_dims[1] / 2  # TODO: use frame_thickness
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

    @staticmethod
    def _create_frame_polyline(frame_polyline_a: Polyline, frame_polyline_b: Polyline) -> Polyline:
        """Bounding rectangle aligned orthogonal to the panel_populator.stud_direction."""
        return Polyline(
            [
                Point(frame_polyline_a.points[0][0], max(frame_polyline_a.points[0][1], frame_polyline_b.points[0][1]), 0),
                Point(frame_polyline_a.points[1][0], min(frame_polyline_a.points[1][1], frame_polyline_b.points[1][1]), 0),
                Point(frame_polyline_a.points[2][0], min(frame_polyline_a.points[2][1], frame_polyline_b.points[2][1]), 0),
                Point(frame_polyline_a.points[3][0], max(frame_polyline_a.points[3][1], frame_polyline_b.points[3][1]), 0),
                Point(frame_polyline_a.points[4][0], max(frame_polyline_a.points[4][1], frame_polyline_b.points[4][1]), 0),
            ]
        )

    @staticmethod
    def _offset_frame_beams(edge_elements: dict, frame_polyline: Polyline) -> None:
        """Apply an offset to the beams so that their edges align with the frame polyline."""
        for edge_index, beams in edge_elements.items():
            vector = get_polyline_segment_perpendicular_vector(frame_polyline, edge_index)
            distance = 0
            for beam in beams[::-1]:
                beam.transform(Translation.from_vector(vector * (distance + beam.width * 0.5)))
                distance += beam.width

    @staticmethod
    def _get_edge_dict(edge_elements: OrderedDict[int, list[Beam]], frame_polyline: Polyline) -> dict[int, Line]:
        """Get the edge lines for the element group based on the frame polyline and edge beams"""
        segs = []
        for index, segment in enumerate(frame_polyline.lines):
            beams = edge_elements.get(index)
            if not beams:  # in case there is no sill
                segs.append(segment)
                continue
            vector = get_polyline_segment_perpendicular_vector(frame_polyline, index)
            segs.append(beams[0].centerline.translated(vector * beams[0].width / 2))
        edges = {}
        extend_line_segments(segs, close_loop=True)
        for i, segment in enumerate(segs):
            edges[i] = segment
        return edges

    # ==========================================================================
    # Opening element joining functions
    # ==========================================================================

    def _get_internal_joints(self) -> list[DirectRule]:
        """Join the sill and header to king and jack studs."""
        sills: list[Beam] = list(filter(lambda x: x.attributes["category"] == "sill", self.elements))

        header = list(filter(lambda x: x.attributes["category"] == "header", self.elements))[0]
        king_studs = filter(lambda x: x.attributes["category"] == "king_stud", self.elements)
        jack_studs = filter(lambda x: x.attributes["category"] == "jack_stud", self.elements)
        rules = []
        # join header
        for king in king_studs:
            rules.append(self.get_direct_rule_from_elements(header, king, max_distance=king.width / 2))
        for jack in jack_studs:
            if jack:
                rules.append(self.get_direct_rule_from_elements(jack, header, max_distance=jack.width / 2))
        # join sill
        if sills:
            sill: Beam = sills[0]
            for jack, king in zip(jack_studs, king_studs):
                if jack:
                    rules.append(self.get_direct_rule_from_elements(sill, jack, max_distance=jack.width / 2))
                else:
                    rules.append(self.get_direct_rule_from_elements(sill, king, max_distance=king.width / 2))
        return [rule for rule in rules if rule is not None]

    def _get_external_joints(self, intersecting_generators: list[ElementGenerator]) -> list[DirectRule]:
        """Join the king and jack studs to neighboring panel populator beams."""
        rules = []
        for king_stud in filter(lambda x: x.attributes["category"] == "king_stud", self.elements):
            if king_stud is None:
                continue  # TODO: error handling
            # extend king stud to closest intersecting features
            king_stud, bottom_int, top_int = extend_beam_to_closest_element_generators(king_stud, intersecting_generators)
            # create joints
            if not king_stud:
                raise ValueError("Failed to extend king stud to intersecting elements.")
            for intersection in [bottom_int, top_int]:
                if intersection is not None:
                    for index in intersection.edge_indices:
                        beams = intersection.generator.edge_elements.get(index, []) if intersection.generator else []
                        for beam in beams:
                            rules.append(self.get_direct_rule_from_elements(king_stud, beam))

        for jack_stud in filter(lambda x: x.attributes["category"] == "jack_stud", self.elements):
            if jack_stud is None:
                continue  # TODO: error handling
            # extend jack stud to closest intersecting features
            jack_stud, bottom_int, _ = extend_beam_to_closest_element_generators(jack_stud, intersecting_generators, only_start=True)
            # create joints
            if not jack_stud:
                raise ValueError("Failed to extend jack stud to intersecting elements.")
            if not bottom_int:
                continue
            for index in bottom_int.edge_indices:
                beams = bottom_int.generator.edge_elements.get(index, []) if bottom_int.generator else []
                for beam in beams:
                    rules.append(self.get_direct_rule_from_elements(jack_stud, beam))
        return [rule for rule in rules if rule is not None]

    # ==========================================================================
    # Opening element culling functions
    # ==========================================================================

    def _cull_stud(self, stud: Beam) -> bool:
        """Split the bottom plate beam for door openings."""
        self.elements.sort(key=lambda x: x.frame.point[0])  # sort left to right
        king_studs = filter(lambda x: x.attributes["category"] == "king_stud", self.elements)
        jack_studs = filter(lambda x: x.attributes["category"] == "jack_stud", self.elements)

        stud_x = stud.frame.point[0]
        for king, jack, side in zip(king_studs, jack_studs, ["left", "right"]):
            king_x = king.frame.point[0]
            bounds = (king_x - (king.width / 2), king_x + (king.width / 2))
            # check king stud overlap
            if do_segments_overlap(stud.centerline, king.centerline):
                if stud_x + stud.width / 2 > bounds[0] and stud_x - stud.width / 2 < bounds[1]:
                    return True
            if all(jack_studs):
                # check jack stud overlap
                if do_segments_overlap(stud.centerline, jack.centerline):
                    jack_x = jack.frame.point[0]
                    if side == "left":
                        bounds = (king_x - (king.width / 2), jack_x + (jack.width / 2))
                    else:  # right jack stud
                        bounds = (jack_x - (jack.width / 2), king_x + (king.width / 2))
                    if stud_x + stud.width / 2 > bounds[0] and stud_x - stud.width / 2 < bounds[1]:
                        return True
        return False

    def cut_out_of_plate(self, plate: Plate) -> None:
        """Apply the opening contour to the given plate.

        Parameters
        ----------
        plate : :class:`compas_timber.elements.Plate`
            The plate to which the opening will be applied.
        """
        opening_a = Polyline([p for p in self.feature.outline_a])
        opening_b = Polyline([p for p in self.feature.outline_b])

        if self.opening_type == "door":
            lines = [(i, l) for i, l in enumerate(opening_a.lines)]
            bottom_edge_index = min(lines, key=lambda x: x[1].midpoint.y)[0]
            opening_a[bottom_edge_index].y -= 0.1
            opening_a[(bottom_edge_index + 1) % len(opening_a)].y -= 0.1
            opening_a[-1] = opening_a[0]
            opening_b[bottom_edge_index].y -= 0.1
            opening_b[(bottom_edge_index + 1) % len(opening_b)].y -= 0.1
            opening_b[-1] = opening_b[0]

        lines = [Line(pt_a, pt_b) for pt_a, pt_b in zip(opening_a.points, opening_b.points)]
        outline_a_projected = Polyline([intersection_line_plane(line, plate.planes[0]) for line in lines])
        outline_b_projected = Polyline([intersection_line_plane(line, plate.planes[1]) for line in lines])
        free_contour = FreeContour.from_top_bottom_and_elements(outline_a_projected, outline_b_projected, plate, interior=True, is_joinery=False)
        plate.add_feature(free_contour)
