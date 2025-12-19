from typing import Union

from compas.geometry import Line
from compas.geometry import Point
from compas.geometry import Translation
from compas.geometry import Vector
from compas.geometry import dot_vectors
from compas.geometry import intersection_line_segment
from compas.geometry import intersection_segment_segment
from compas.itertools import pairwise
from compas_timber.elements import Beam

from timber_design.populators import ElementGenerator
from timber_design.workflow import DirectRule


def get_beam_element_generator_intersection(beam: Beam, element_generator: ElementGenerator) -> dict[int, dict]:
    intersections = {}
    for index, edge in element_generator.edges.items():
        pt = intersection_line_segment(beam.centerline, edge)[0]
        if pt:
            intersections[index] = {
                "point": Point(*pt),
                "dot": dot_vectors(Vector.from_start_end(beam.frame.point, pt), beam.frame.xaxis),
                "beam": element_generator.edge_elements[index][0],
                "element_generator": element_generator,
            }
    return intersections


def get_beam_edges_element_generator_intersection(
    beam: Beam, element_generator: ElementGenerator, limit_to_segments: bool = True, ignore_notches: bool = False, ignore_laps: bool = False
) -> list[dict]:
    edge_a = beam.centerline.translated(beam.frame.yaxis * -beam.width / 2)
    edge_b = beam.centerline.translated(beam.frame.yaxis * beam.width / 2)
    intersections_a = {}
    intersections_b = {}
    for index, edge in element_generator.edges.items():
        pt = intersection_line_segment(edge_a, edge)[0] if not limit_to_segments else intersection_segment_segment(edge_a, edge)[0]
        if pt:
            dot = dot_vectors(Vector.from_start_end(edge_a.start, pt), edge_a.direction)
            intersections_a[index] = {"point": Point(*pt), "dot": dot, "element_generator": element_generator}
        pt = intersection_line_segment(edge_b, edge)[0] if not limit_to_segments else intersection_segment_segment(edge_b, edge)[0]
        if pt:
            dot = dot_vectors(Vector.from_start_end(edge_b.start, pt), edge_b.direction)
            intersections_b[index] = {"point": Point(*pt), "dot": dot, "element_generator": element_generator}

    s, c, n, l = _classify_intersections(intersections_a, intersections_b, element_generator)
    if ignore_notches:
        n = []
    if ignore_laps:
        l = []
    return s + c + n + l


def _classify_intersections(
    intersections_a: dict[int, dict], intersections_b: dict[int, dict], element_generator: ElementGenerator
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    edge_count = len(element_generator.edges)
    simple_keys = list(set(intersections_a).intersection(set(intersections_b)))
    simple_intersections = []
    for i in simple_keys:
        simple_intersections.append(
            {
                "point": (intersections_a[i]["point"] + intersections_b[i]["point"]) / 2,
                "dot": (intersections_a[i]["dot"] + intersections_b[i]["dot"]) / 2,
                "edge_indices": [i],
                "element_generator": element_generator,
                "type": "simple",
            }
        )
    leftovers_a = list(set(intersections_a) - set(intersections_b))
    leftovers_b = list(set(intersections_b) - set(intersections_a))
    corner_intersections = []
    notch_intersections = []
    lap_intersections = []

    while leftovers_a:
        ia = leftovers_a.pop()
        for i_adjacent in [(ia - 1) % edge_count, (ia + 1) % edge_count]:
            if i_adjacent in leftovers_b:
                ib = leftovers_b.pop(leftovers_b.index(i_adjacent))
                intersection = {
                    "point": (intersections_a[ia]["point"] + intersections_b[ib]["point"]) / 2,
                    "dot": (intersections_a[ia]["dot"] + intersections_b[ib]["dot"]) / 2,
                    "edge_indices": [ia, ib],
                    "element_generator": element_generator,
                    "type": "corner",
                }
                corner_intersections.append(intersection)
                break
            elif i_adjacent in leftovers_a:
                ia_b = leftovers_a.pop(leftovers_a.index(i_adjacent))
                intersection = {
                    "point": (intersections_a[ia]["point"] + intersections_a[ia_b]["point"]) / 2,
                    "dot": (intersections_a[ia]["dot"] + intersections_a[ia_b]["dot"]) / 2,
                    "edge_indices": [ia, ia_b],
                    "element_generator": element_generator,
                    "type": "notch",
                }
                notch_intersections.append(intersection)
                break
        else:
            lap_intersections.append(
                {"point": intersections_a[ia]["point"], "dot": intersections_a[ia]["dot"], "edge_indices": [ia], "element_generator": element_generator, "type": "lap"}
            )

    while leftovers_b:
        ib = leftovers_b.pop()
        for i_adjacent in [(ib - 1) % edge_count, (ib + 1) % edge_count]:
            if i_adjacent in leftovers_b:
                ib_b = leftovers_b.pop(leftovers_b.index(i_adjacent))
                intersection = {
                    "point": (intersections_b[ib]["point"] + intersections_b[ib_b]["point"]) / 2,
                    "dot": (intersections_b[ib]["dot"] + intersections_b[ib_b]["dot"]) / 2,
                    "edge_indices": [ib, ib_b],
                    "element_generator": element_generator,
                    "type": "notch",
                }
                notch_intersections.append(intersection)
                break
        else:
            lap_intersections.append(
                {"point": intersections_b[ib]["point"], "dot": intersections_b[ib]["dot"], "edge_indices": [ib], "element_generator": element_generator, "type": "lap"}
            )
    return simple_intersections, corner_intersections, notch_intersections, lap_intersections


def intersection_line_feature_definition(line: Line, element_generator: ElementGenerator) -> list[dict]:
    intersections = []
    for index, edge in element_generator.edges.items():
        pt = intersection_line_segment(line, edge)[0]
        if pt:
            intersections.append(
                {"point": Point(*pt), "dot": dot_vectors(Vector.from_start_end(line.start, pt), line.direction), "edge_index": index, "element_generator": element_generator}
            )
    return intersections


def split_beam_with_element_generators(
    beam: Beam, element_generators: list[ElementGenerator], ignore_notches: bool = False, ignore_laps: bool = False
) -> tuple[list[tuple[Union[Beam, None], tuple[Union[dict, None], Union[dict, None]]]], list[DirectRule]]:
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
    intersections = [
        {"point": beam.frame.point, "dot": 0.0, "edge_indices": [], "element_generator": None},
        {"point": beam.frame.point + beam.frame.xaxis * beam.length, "dot": beam.length, "edge_indices": [], "element_generator": None},
    ]
    for generator in element_generators:
        intersections.extend(get_beam_edges_element_generator_intersection(beam, generator, ignore_notches=ignore_notches, ignore_laps=ignore_laps))

    if len(intersections) == 2:  # no intersections found
        for element_generator in element_generators:
            if element_generator.cull_element_at_point(beam.centerline.midpoint, beam):
                return [(None, (None, None))], list(beam.attributes.get("joint_defs", {}).values())
        return [(beam, (None, None))], []
    intersections.sort(key=lambda x: x["dot"])

    beam_int_tuples = []
    old_rules = beam.attributes.get("joint_defs", {})
    beam.attributes.pop("joint_defs", None)
    rules_to_remove = []
    for pair in pairwise(intersections):
        if any([i.get("type") == "notch" or i.get("type") == "lap" for i in pair]):
            # skip notches and laps, can't handle. TODO: pass these out for special handling?
            continue

        # copy beam segment
        beam_seg = beam.copy()
        beam_seg.transform(Translation.from_vector(beam.frame.xaxis * pair[0]["dot"]))
        beam_seg.length = pair[1]["dot"] - pair[0]["dot"]

        # cull studs outside inner outline
        skip_pair = False
        test_point = (pair[0]["point"] + pair[1]["point"]) / 2
        for element_generator in [pair[0]["element_generator"], pair[1]["element_generator"]]:
            if element_generator and element_generator.cull_element_at_point(test_point, beam_seg):
                skip_pair = True
                break
        if skip_pair:
            for dot, rule in old_rules.items():
                if pair[0]["dot"] < dot < pair[1]["dot"]:
                    rules_to_remove.append(old_rules[dot])
            continue

        # reassign joint defs
        for dot, rule in old_rules.items():
            if pair[0]["dot"] < dot < pair[1]["dot"]:
                rule.elements[rule.elements.index(beam)] = beam_seg
                dot = dot - pair[0]["dot"]
                if beam_seg.attributes.get("joint_defs") is None:
                    beam_seg.attributes["joint_defs"] = {}
                beam_seg.attributes["joint_defs"][dot] = rule
        for feature in beam.features:
            feature.beam = beam_seg
        beam_int_tuples.append((beam_seg, pair))
    return beam_int_tuples, rules_to_remove


def extend_beam_to_closest_element_generators(
    beam: Beam, element_generators: list[ElementGenerator], only_start: bool = False, only_end: bool = False
) -> tuple[Union[Beam, None], Union[dict, None], Union[dict, None]]:
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

    intersections = []
    for ft in element_generators:
        if ft.outline is not None:
            intersections.extend(get_beam_edges_element_generator_intersection(beam, ft, limit_to_segments=False, ignore_notches=True, ignore_laps=True))
    if not intersections:
        return beam, None, None
    # get closest intersections above and below the beam
    intersections.sort(key=lambda x: x["dot"])

    bottom_int = None
    top_int = None
    while intersections:
        previous_int = intersections.pop(0)
        if not bottom_int and intersections[0]["dot"] > 0:
            bottom_int = previous_int
        if intersections[0]["dot"] > beam.length:
            top_int = intersections[0]
            break

    if only_end and only_start:
        raise ValueError("Beam is overconstrained, only one of `only_below` and `only_above` can be True: {}".format(beam))
    if only_end:
        bottom_int = None
    else:
        beam.transform(Translation.from_vector(beam.frame.xaxis * bottom_int["dot"]))

    if only_start:
        beam.length = beam.length - bottom_int["dot"]
        top_int = None
    else:
        beam.length = top_int["dot"] - bottom_int["dot"]
    return beam, bottom_int, top_int
