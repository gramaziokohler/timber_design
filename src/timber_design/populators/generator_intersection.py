from re import L
from typing import Union
from typing import Optional

from attr import s
from compas.geometry import Line, distance_point_point
from compas.geometry import Point
from compas.geometry import Translation
from compas.geometry import Vector
from compas.geometry import dot_vectors
from compas.geometry import intersection_line_segment
from compas.geometry import intersection_segment_segment
from compas.geometry import closest_point_on_line
from compas.itertools import pairwise
from compas_model.elements import beam
from compas_timber.elements import Beam

from timber_design.populators import ElementGenerator
from timber_design.workflow import DirectRule

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
    def from_beam_and_generator(cls, beam: Beam, element_generator: ElementGenerator, limit_to_segments: bool = True, skip_notches:bool=False, skip_laps:bool=False):
        intersections_a, intersections_b = cls._get_edge_intersections(beam, element_generator, limit_to_segments)
        edge_count = len(element_generator.edges)

        intersections, leftovers_a, leftovers_b = cls._parse_simple_intersections(intersections_a, intersections_b, beam, element_generator)

        corner_intersections, leftovers_a, leftovers_b = cls._parse_corner_intersections(leftovers_a, leftovers_b, beam, element_generator)
        intersections.extend(corner_intersections)
        if not skip_notches:
            notch_intersections, leftovers_a, leftovers_b = cls._parse_notch_intersections(leftovers_a, leftovers_b, beam, element_generator)
            intersections.extend(notch_intersections)
            if not skip_laps:
                lap_intersections = cls._parse_lap_intersections(leftovers_a, leftovers_b, beam, element_generator)
                intersections.extend(lap_intersections)
        return intersections

    @staticmethod
    def _parse_simple_intersections(intersections_a:list[LineGeneratorIntersection], intersections_b: list[LineGeneratorIntersection], beam:Beam, element_generator:ElementGenerator):
        """gets BeamGeneratorIntersection objects from lists of LineGeneratorIntersection objects.
            Simple intersections are those where both beam edges intersect the same edge of the element generator."""
        keys_a = {i.edge_index for i in intersections_a}
        keys_b = {i.edge_index for i in intersections_b}
        simple_keys = list(keys_a.intersection(keys_b))
        simple_intersections: list[BeamGeneratorIntersection] = []
        for i in simple_keys:
            simple_intersections.append(
                BeamGeneratorIntersection(
                    type=BeamGeneratorIntersectionType.SINGLE,
                    point=(intersections_a[i].point + intersections_b[i].point) / 2,
                    dot=(intersections_a[i].dot + intersections_b[i].dot) / 2,
                    edge_indices=[i],
                    beam=beam,
                    generator=element_generator,
                )
            )
        leftovers_a = list(set(intersections_a) - set(intersections_b))
        leftovers_b = list(set(intersections_b) - set(intersections_a))
        return simple_intersections, leftovers_a, leftovers_b

    @staticmethod
    def _parse_corner_intersections(intersections_a:list[LineGeneratorIntersection], intersections_b:list[LineGeneratorIntersection], beam:Beam, generator:ElementGenerator):
        """gets corner BeamGeneratorIntersection objects from lists of LineGeneratorIntersection objects.
        corner intersections are those where each beam edge intersects an adjacent edge of the element generator.
        """
        leftovers_a = [i for i in intersections_a]
        leftovers_b = [i for i in intersections_b]
        corner_intersections = []
        for int_a in intersections_a:
            adjacent_indices = [(int_a.edge_index - 1) % len(generator.edges), (int_a.edge_index + 1) % len(generator.edges)]
            for int_b in intersections_b:
                if int_b.edge_index in adjacent_indices:
                    corner_intersections.append(
                        BeamGeneratorIntersection(
                            type=BeamGeneratorIntersectionType.CORNER,
                            point=(int_a.point + int_b.point) / 2,
                            dot=(int_a.dot + int_b.dot) / 2,
                            edge_indices=[int_a.edge_index, int_b.edge_index],
                            beam=beam,
                            generator=generator,
                        )
                    )
                    leftovers_a.remove(int_a)
                    leftovers_b.remove(int_b)
                    break
        return corner_intersections, leftovers_a, leftovers_b

    @staticmethod
    def _parse_notch_intersections(intersections_a:list[LineGeneratorIntersection], intersections_b:list[LineGeneratorIntersection], beam:Beam, generator:ElementGenerator):
        """gets notch BeamGeneratorIntersection objects from lists of LineGeneratorIntersection objects.
        notch intersections are those where one beam edge intersects two adjacent edges of the element generator.
        """
        notch_intersections = []
        ints_found = []
        for intersections in [intersections_a, intersections_b]:
            for first_int in intersections:
                adjacent_indices = [(first_int.edge_index - 1) % len(generator.edges), (first_int.edge_index + 1) % len(generator.edges)]
                for second_int in intersections:
                    if second_int.edge_index in adjacent_indices:
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
                        ints_found.extend([first_int, second_int])
                        break
        leftovers_a = [i for i in intersections_a if i not in ints_found]
        leftovers_b = [i for i in intersections_b if i not in ints_found]
        return notch_intersections, leftovers_a, leftovers_b


    @staticmethod
    def _parse_lap_intersections(intersections_a:list[LineGeneratorIntersection], intersections_b:list[LineGeneratorIntersection], beam:Beam, generator:ElementGenerator):
        """gets lap BeamGeneratorIntersection objects from lists of LineGeneratorIntersection objects.
        lap intersections are those where beam edges intersect non-adjacent edges of the element generator and at least one generator edge is between the beam edges/inside the beam.
        """
        lap_intersections = []
        intersection_indices:list[int] = [i.edge_index for i in intersections_a] + [i.edge_index for i in intersections_b]
        intersection_indices.sort()
        intersection_indices.append(intersection_indices[0] + len(generator.edges))
        lap_ranges = pairwise(intersection_indices)
        
        for range in lap_ranges:
            edge = generator.edges[range[0] % len(generator.edges)]
            centerline_point = closest_point_on_line(edge.end, beam.centerline)
            distance = distance_point_point(Point(edge.end[0], edge.end[1], 0.0), Point(centerline_point[0], centerline_point[1],0.0))
            if distance < beam.width/2:
                lap_intersections.append(
                    BeamGeneratorIntersection(
                        type=BeamGeneratorIntersectionType.LAP,
                        point=beam.centerline.midpoint,
                        dot=beam.length / 2,
                        edge_indices=[i % len(generator.edges) for i in range],
                        beam=beam,
                        generator=generator,
                    )
                )
        return lap_intersections


    @staticmethod
    def _get_edge_intersections(beam:Beam, generator:ElementGenerator, limit_to_segments:bool=True)-> tuple[list[LineGeneratorIntersection], list[LineGeneratorIntersection]]:
        edge_a = beam.centerline.translated(beam.frame.yaxis * -beam.width / 2)
        edge_b = beam.centerline.translated(beam.frame.yaxis * beam.width / 2)
        intersections_a = []
        intersections_b = []
        for index, edge in generator.edges.items():
            pt = intersection_line_segment(edge_a, edge)[0] if not limit_to_segments else intersection_segment_segment(edge_a, edge)[0]
            if pt:
                dot = dot_vectors(Vector.from_start_end(edge_a.start, pt), edge_a.direction)
                intersections_a.append(LineGeneratorIntersection(point= Point(*pt), dot= dot, edge_index=index,line=edge_a, generator= generator))

            pt = intersection_line_segment(edge_b, edge)[0] if not limit_to_segments else intersection_segment_segment(edge_b, edge)[0]
            if pt:
                dot = dot_vectors(Vector.from_start_end(edge_b.start, pt), edge_b.direction)
                intersections_b.append(LineGeneratorIntersection(point= Point(*pt), dot= dot, edge_index=index,line=edge_b, generator= generator))
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
    intersections:list[BeamGeneratorIntersection] = [
        BeamGeneratorIntersection(type=None, point=beam.frame.point, dot=0.0, edge_indices=[], beam=beam, generator= None),
        BeamGeneratorIntersection(type=None, point=beam.frame.point + beam.frame.xaxis * beam.length, dot=beam.length, edge_indices=[], beam=beam, generator= None),
    ]

    for generator in element_generators:
        intersections.extend(BeamGeneratorIntersection.from_beam_and_generator(beam, generator, skip_notches=ignore_notches,skip_laps=ignore_notches))

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
        beam_seg:Beam = _get_beam_segment(beam, pair[0].dot, pair[1].dot)

        # check if beam segment should be culled
        for element_generator in [pair[0].generator, pair[1].generator]:
            if element_generator and element_generator.cull_element_at_point(beam_seg.centerline.midpoint):
                rules_to_remove.extend(beam_seg.attributes.pop("joint_defs", {}).values())
                break
        else: 
            beam_int_tuples.append((beam_seg, pair))
    return beam_int_tuples, rules_to_remove


def _get_beam_segment(beam:Beam, start_length:float, end_length:float)-> Beam:
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

    intersections:list[BeamGeneratorIntersection] = []
    for eg in element_generators:
        if eg.outline is not None:
            intersections.extend(BeamGeneratorIntersection.from_beam_and_generator(beam, eg, limit_to_segments=False, skip_notches=True, skip_laps=True))
    if not intersections:
        return beam, None, None
    # get closest intersections above and below the beam
    intersections.sort(key=lambda x: x.dot)

    bottom_int = None
    top_int = None
    while intersections:
        previous_int = intersections.pop(0)
        if not bottom_int and intersections[0].dot > 0:
            bottom_int = previous_int
        if intersections[0].dot > beam.length:
            top_int = intersections[0]
            break

    if only_end and only_start:
        raise ValueError("Beam is overconstrained, only one of `only_below` and `only_above` can be True: {}".format(beam))
    if only_end:
        bottom_int = None
    elif bottom_int:
        beam.transform(Translation.from_vector(beam.frame.xaxis * bottom_int.dot))

        if only_start:
            beam.length = beam.length - bottom_int.dot
            top_int = None
        elif top_int:
            beam.length = top_int.dot - bottom_int.dot
    return beam, bottom_int, top_int
