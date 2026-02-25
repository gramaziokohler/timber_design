from __future__ import annotations

from itertools import product
from typing import TYPE_CHECKING
from typing import Optional
from typing import Union

if TYPE_CHECKING:
    from timber_design.populators import ElementGenerator
    from timber_design.workflow import DirectRule

from compas.geometry import Line
from compas.geometry import Point
from compas.geometry import Translation
from compas.geometry import Vector
from compas.geometry import dot_vectors
from compas.geometry import intersection_line_segment
from compas.geometry import intersection_segment_segment
from compas.itertools import pairwise
from compas_timber.elements import Beam


class LineGeneratorIntersection(object):
    def __init__(
        self,
        point: Point,
        dot: float,
        edge_index: int,
        line: Line,
        generator: ElementGenerator,
    ):
        self.point = point
        self.dot = dot
        self.edge_index = edge_index
        self.line = line
        self.generator = generator


class BeamGeneratorIntersectionType(object):
    """Types of beam-element generator intersections.
    SINGLE: both beam edges intersect the same edge of the element generator.
    CORNER: each beam edge intersects an adjacent edge of the element generator.
    NOTCH: one beam edge intersects adjacent edges of the element generator, but on the same
    LAP: beam edges intersect non-adjacent edges of the element generator.
    """

    SINGLE = "single"
    CORNER = "corner"
    NOTCH = "notch"
    LAP = "lap"


class BeamGeneratorIntersection(object):
    def __init__(
        self,
        type: Optional[str],
        point: Point,
        dot: float,
        edge_indices: Optional[list[int]],
        beam: Beam,
        generator: Optional[ElementGenerator],
    ):
        self.type = type
        self.point = point
        self.dot = dot
        self.edge_indices = edge_indices or []
        self.beam = beam
        self.generator = generator

    @classmethod
    def from_beam_and_generator(cls, beam: Beam, element_generator: ElementGenerator, limit_to_segments: bool = True, skip_notches: bool = False, skip_laps: bool = False):
        intersections_a, intersections_b = cls._get_edge_intersections(beam, element_generator, limit_to_segments)

        intersections, leftovers_a, leftovers_b = cls._parse_simple_intersections(intersections_a, intersections_b, beam, element_generator)
        if leftovers_a and leftovers_b:
            corner_intersections, leftovers_a, leftovers_b = cls._parse_corner_intersections(leftovers_a, leftovers_b, beam, element_generator)
            intersections.extend(corner_intersections)
        if leftovers_a or leftovers_b:
            if not skip_notches:
                notch_intersections, leftovers_a, leftovers_b = cls._parse_notch_intersections(leftovers_a, leftovers_b, beam, element_generator)
                intersections.extend(notch_intersections)

                if not skip_laps:
                    lap_intersections = cls._parse_lap_intersections(leftovers_a, leftovers_b, beam, element_generator)
                    intersections.extend(lap_intersections)
        return intersections

    @staticmethod
    def _parse_simple_intersections(
        intersections_a: list[LineGeneratorIntersection], intersections_b: list[LineGeneratorIntersection], beam: Beam, element_generator: ElementGenerator
    ):
        """gets BeamGeneratorIntersection objects from lists of LineGeneratorIntersection objects.
        Simple intersections are those where both beam edges intersect the same edge of the element generator."""
        leftovers_a = [i for i in intersections_a]
        leftovers_b = [i for i in intersections_b]

        simple_intersections: list[BeamGeneratorIntersection] = []
        for i_a, i_b in product(intersections_a, intersections_b):
            if i_a.edge_index == i_b.edge_index:
                simple_intersections.append(
                    BeamGeneratorIntersection(
                        type=BeamGeneratorIntersectionType.SINGLE,
                        point=(i_a.point + i_b.point) / 2,
                        dot=(i_a.dot + i_b.dot) / 2,
                        edge_indices=[i_a.edge_index],
                        beam=beam,
                        generator=element_generator,
                    )
                )
                leftovers_a.remove(i_a)
                leftovers_b.remove(i_b)

        return simple_intersections, leftovers_a, leftovers_b

    @staticmethod
    def _parse_corner_intersections(intersections_a: list[LineGeneratorIntersection], intersections_b: list[LineGeneratorIntersection], beam: Beam, generator: ElementGenerator):
        """gets corner BeamGeneratorIntersection objects from lists of LineGeneratorIntersection objects.
        corner intersections are those where each beam edge intersects an adjacent edge of the element generator.
        """
        leftovers_a = [i for i in intersections_a]
        leftovers_b = [i for i in intersections_b]
        corner_intersections = []
        for i_a, i_b in product(intersections_a, intersections_b):
            edge_difference = abs(i_a.edge_index - i_b.edge_index)
            if edge_difference == 1 or edge_difference == len(generator.edges) - 1:
                corner_intersections.append(
                    BeamGeneratorIntersection(
                        type=BeamGeneratorIntersectionType.CORNER,
                        point=(i_a.point + i_b.point) / 2,
                        dot=(i_a.dot + i_b.dot) / 2,
                        edge_indices=[i_a.edge_index, i_b.edge_index],
                        beam=beam,
                        generator=generator,
                    )
                )
                leftovers_a.remove(i_a)
                leftovers_b.remove(i_b)

        return corner_intersections, leftovers_a, leftovers_b

    @staticmethod
    def _parse_notch_intersections(intersections_a: list[LineGeneratorIntersection], intersections_b: list[LineGeneratorIntersection], beam: Beam, generator: ElementGenerator):
        """gets notch BeamGeneratorIntersection objects from lists of LineGeneratorIntersection objects.
        notch intersections are those where one beam edge intersects two adjacent edges of the element generator.
        """
        if not intersections_a and not intersections_b:
            return [], [], []

        def _get_notch_intersections_for_side(intersection_set, beam, generator):
            leftovers = [i for i in intersection_set]
            notch_intersections = []
            # in case first and last edge make a notch
            if is_point_between_beam_edges(intersection_set[0].line.start, beam):  # first int edge starts inside beam, move to end
                intersection_set.append(intersection_set.pop(0))
            i = 0
            while i < len(intersection_set) - 1:
                first_int, second_int = intersection_set[i : i + 2]
                if second_int.edge_index - first_int.edge_index == 1 or (first_int.edge_index == len(generator.edges) - 1 and second_int.edge_index == 0):
                    if is_point_between_beam_edges(first_int.line.end, beam):
                        notch_intersections.append(
                            BeamGeneratorIntersection(
                                type=BeamGeneratorIntersectionType.NOTCH,
                                point=(first_int.point + second_int.point) / 2,
                                dot=(first_int.dot + second_int.dot) / 2,
                                edge_indices=[first_int.edge_index, second_int.edge_index],
                                beam=beam,
                                generator=generator,
                            )
                        )
                        i += 1  # if match found, skip 1 additional int
                        leftovers.remove(first_int)
                        leftovers.remove(second_int)
                i += 1  # next int
            return notch_intersections, leftovers

        side_a_notches, leftovers_a = _get_notch_intersections_for_side(intersections_a, beam, generator) if intersections_a else ([], [])

        side_b_notches, leftovers_b = _get_notch_intersections_for_side(intersections_b, beam, generator) if intersections_b else ([], [])

        return side_a_notches + side_b_notches, leftovers_a, leftovers_b

    @staticmethod
    def _parse_lap_intersections(intersections_a: list[LineGeneratorIntersection], intersections_b: list[LineGeneratorIntersection], beam: Beam, generator: ElementGenerator):
        """gets lap BeamGeneratorIntersection objects from lists of LineGeneratorIntersection objects.
        lap intersections are those where beam edges intersect non-adjacent edges of the element generator
        and at least one generator edge is between the beam edges/inside the beam.
        """
        if not intersections_a and not intersections_b:
            return []
        lap_intersections = []
        intersections: list[LineGeneratorIntersection] = [i for i in intersections_a] + [i for i in intersections_b]
        intersections.sort(key=lambda x: x.edge_index)

        if is_point_between_beam_edges(intersections[0].line.start, beam):
            intersections.append(intersections.pop(0))  # lap ends at first intersection, move to end of list

        for pair in pairwise(intersections):
            if is_point_between_beam_edges(pair[0].line.end, beam):
                lap_intersections.append(
                    BeamGeneratorIntersection(
                        type=BeamGeneratorIntersectionType.LAP,
                        point=(pair[0].point + pair[1].point) / 2,
                        dot=(pair[0].dot + pair[1].dot) / 2,
                        edge_indices=[i.edge_index for i in pair],
                        beam=beam,
                        generator=generator,
                    )
                )
        return lap_intersections

    @staticmethod
    def _get_edge_intersections(
        beam: Beam, generator: ElementGenerator, limit_to_segments: bool = True
    ) -> tuple[list[LineGeneratorIntersection], list[LineGeneratorIntersection]]:
        edge_a = beam.centerline.translated(beam.frame.yaxis * -beam.width / 2)
        edge_b = beam.centerline.translated(beam.frame.yaxis * beam.width / 2)
        intersections_a = []
        intersections_b = []
        for index, edge in generator.edges.items():
            pt = intersection_line_segment(edge_a, edge)[0] if not limit_to_segments else intersection_segment_segment(edge_a, edge)[0]
            if pt:
                dot = dot_vectors(Vector.from_start_end(edge_a.start, pt), edge_a.direction)
                intersections_a.append(LineGeneratorIntersection(point=Point(*pt), dot=dot, edge_index=index, line=edge, generator=generator))

            pt = intersection_line_segment(edge_b, edge)[0] if not limit_to_segments else intersection_segment_segment(edge_b, edge)[0]
            if pt:
                dot = dot_vectors(Vector.from_start_end(edge_b.start, pt), edge_b.direction)
                intersections_b.append(LineGeneratorIntersection(point=Point(*pt), dot=dot, edge_index=index, line=edge, generator=generator))
        return intersections_a, intersections_b


def split_beam_with_element_generators(
    beam: Beam, element_generators: list[ElementGenerator], ignore_notches: bool = False, ignore_laps: bool = False
) -> tuple[list[tuple[Union[Beam, None], tuple[Union[BeamGeneratorIntersection, None], Union[BeamGeneratorIntersection, None]]]], list[DirectRule]]:
    """Removes a section of a beam that intersects with a given outline.

    Parameters
    ----------
    beam : :class:`compas_timber.elements.Beam`
        The beam to trim.
    outline : :class:`compas.geometry.Polyline`
        The outline to trim the beam to.

    Returns
    -------
    list of :class:`compas_timber.elements.Beam`
        The remaining beam sections after removing the intersecting section.

    """
    intersections: list[BeamGeneratorIntersection] = [
        BeamGeneratorIntersection(type=None, point=beam.frame.point, dot=0.0, edge_indices=[], beam=beam, generator=None),
        BeamGeneratorIntersection(type=None, point=beam.frame.point + beam.frame.xaxis * beam.length, dot=beam.length, edge_indices=[], beam=beam, generator=None),
    ]

    for generator in element_generators:
        intersections.extend(BeamGeneratorIntersection.from_beam_and_generator(beam, generator, skip_notches=ignore_notches, skip_laps=ignore_notches))

    if len(intersections) == 2:  # no intersections found
        for element_generator in element_generators:
            if element_generator.cull_element_at_point(beam.centerline.midpoint):
                return [(None, (None, None))], list(beam.attributes.get("joint_defs", {}).values())
        return [(beam, (None, None))], []

    intersections.sort(key=lambda x: x.dot)

    beam_int_tuples = []
    rules_to_remove = []
    for pair in pairwise(intersections):
        # copy beam segment
        beam_seg: Beam = _get_beam_segment(beam, pair[0].dot, pair[1].dot)
        # check if beam segment should be culled
        for element_generator in [pair[0].generator, pair[1].generator]:
            if not element_generator:
                continue
            if element_generator and element_generator.cull_element_at_point(beam_seg.centerline.midpoint):
                rules_to_remove.extend(beam_seg.attributes.pop("joint_defs", {}).values())
                break
        else:
            beam_int_tuples.append((beam_seg, pair))
    return beam_int_tuples, rules_to_remove


def _get_beam_segment(beam: Beam, start_length: float, end_length: float) -> Beam:
    beam_seg = beam.copy()
    beam_seg.transform(Translation.from_vector(beam.frame.xaxis * start_length))
    beam_seg.length = end_length - start_length
    for feature in beam.features:
        feature.beam = beam_seg

    for dot, rule in beam.attributes.get("joint_defs", {}):
        if start_length < dot < end_length:
            rule.elements[rule.elements.index(beam)] = beam_seg
            dot = dot - start_length
            if beam_seg.attributes.get("joint_defs") is None:
                beam_seg.attributes["joint_defs"] = {}
            beam_seg.attributes["joint_defs"][dot] = rule
    return beam_seg


def extend_beam_to_closest_element_generators(
    beam: Beam, element_generators: list[ElementGenerator], only_start: bool = False, only_end: bool = False
) -> tuple[Union[Beam, None], Union[BeamGeneratorIntersection, None], Union[BeamGeneratorIntersection, None]]:
    """Extends a beam to fit within a given outline.

    Parameters
    ----------
    beam : :class:`compas_timber.elements.Beam`
        The beam to extend.
    outline : :class:`compas.geometry.Polyline`
        The outline to extend the beam to.

    Returns
    -------
    :class:`compas_timber.elements.Beam` or None
        The extended beam, or None if the beam does not intersect the outline.

    """
    if only_end and only_start:
        raise ValueError("Beam is overconstrained, only one of `only_below` and `only_above` can be True: {}".format(beam))

    intersections: list[BeamGeneratorIntersection] = []
    for eg in element_generators:
        if eg.outline is not None:
            intersections.extend(BeamGeneratorIntersection.from_beam_and_generator(beam, eg, limit_to_segments=False, skip_notches=True, skip_laps=True))
    if not intersections:
        return beam, None, None
    intersections.sort(key=lambda x: x.dot)

    def get_bottom_int(intersections) -> Union[BeamGeneratorIntersection, None]:
        """get intersection with highest negative .dot value.
        requires intersections to be sorted by .dot value.
        will operate on intersections list and remove all intersections with negative .dot value.
        """
        if not intersections or intersections[0].dot > 0:
            return None
        bottom = intersections.pop(0)  # this dot is negative
        while intersections:
            if intersections[0].dot > 0:
                break
            bottom = intersections.pop(0)
        return bottom

    def get_top_int(beam, intersections):
        """get intersection with lowest .dot value > beam.length.
        will operate on intersections list and remove all intersections with .dot value > beam.length.
        """
        if not intersections or intersections[-1].dot < beam.length:
            return None
        top = intersections.pop()  # this dot is > beam.length
        while intersections:
            if intersections[-1].dot < beam.length:
                break
            top = intersections.pop(-1)
        return top

    bottom_int = get_bottom_int(intersections) if not only_end else None
    top_int = get_top_int(beam, intersections) if not only_start else None

    if bottom_int:
        beam.transform(Translation.from_vector(beam.frame.xaxis * bottom_int.dot))

    start = bottom_int.dot if bottom_int else 0
    end = top_int.dot if top_int else beam.length
    beam.length = end - start

    return beam, bottom_int, top_int


def is_point_between_beam_edges(point: Point, beam: Beam) -> bool:
    """checks if a point is inside the 2D projection of a beam (ignores beam thickness in Z direction)"""
    edge_a = beam.centerline.translated(beam.frame.yaxis * -beam.width / 2)
    edge_b = beam.centerline.translated(beam.frame.yaxis * beam.width / 2)
    vector_a_b = Vector.from_start_end(edge_a.start, edge_b.start)
    dot_a_p = dot_vectors(Vector.from_start_end(point, edge_a.start), vector_a_b)
    dot_b_p = dot_vectors(Vector.from_start_end(point, edge_b.start), vector_a_b)
    return (dot_a_p > 0) ^ (dot_b_p > 0)
