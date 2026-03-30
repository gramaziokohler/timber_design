from __future__ import annotations

from typing import TYPE_CHECKING
from typing import NamedTuple

if TYPE_CHECKING:
    from timber_design.populators import ElementGenerator
    from timber_design.workflow import DirectRule

from compas.geometry import Point
from compas.geometry import Polyline
from compas.geometry import Translation
from compas.geometry import Vector
from compas.geometry import dot_vectors
from compas.geometry import intersection_line_segment
from compas.geometry import intersection_segment_segment
from compas.itertools import pairwise

from timber_design.populators.beam2d import Beam2D


# =============================================================================
# Internal types
# =============================================================================


class _BeamOutlineIntersection(NamedTuple):
    """Internal: a single intersection between one beam blank edge and one boundary edge."""

    point: Point
    dot: float
    edge_index: int
    line: object  # the boundary edge


class _ParsedIntersection(NamedTuple):
    """Internal: a classified intersection result, neutral of source (generator or beam)."""

    type: str
    point: Point
    dot: float


# =============================================================================
# Intersection type constants  (shared by BGI and BBI)
# =============================================================================


class IntersectionType(object):
    """Geometric classification of a beam blank intersection with a boundary.

    These types describe the spatial relationship between the intersecting
    beam's blank and the boundary edges it crosses.  They map to timber joint
    topologies but are intentionally kept geometry-only so they can be used
    by :class:`BeamGeneratorIntersection` (BGI).

    Attributes
    ----------
    SINGLE : str
        Both blank edges cross the **same** boundary edge.
        The beam end meets a face → **T topology**.
    CORNER : str
        The primary beam's end lands at a corner where **two other beams
        already meet** (Y / K topology).  Not detectable from a single beam
        pair — must be assembled from multiple pairwise results at a higher
        level.  Resolving this intersection yields two
        :attr:`connecting_beams` and requires a three-way cluster joint.
        → **Y / K topology (primary beam is main_beam)**.
    NOTCH : str
        One blank edge crosses two adjacent boundary edges while the other
        does not intersect at all — the beam clips only one corner of the
        boundary.  → **notch / half-lap**.
    LAP : str
        The blank edges cross non-adjacent boundary edges and at least one
        boundary corner lies inside the beam's width.
        The beam passes fully through the boundary region → **X / lap**.
    """

    SINGLE = "single"
    CORNER = "corner"
    NOTCH = "notch"
    LAP = "lap"


# =============================================================================
# Module-level detection functions  (shared by BGI and BBI)
# =============================================================================


def _get_beam_outline_intersections(beam, outline, limit_to_segments=True):
    # type: (Beam2D, Polyline, bool) -> tuple[list[_BeamOutlineIntersection], list[_BeamOutlineIntersection]]
    """Intersect the two blank side-edges of *beam* against every segment of *outline*.

    Parameters
    ----------
    beam : :class:`~timber_design.populators.Beam2D`
        The beam whose blank edges are being intersected.
    outline : :class:`compas.geometry.Polyline`
        Closed boundary polyline.  Each segment is tested in turn; its
        position in ``outline.lines`` becomes the ``edge_index`` stored on
        the returned :class:`_LineEdgeIntersection` objects.
    limit_to_segments : bool
        When ``True`` use segment-segment intersection; otherwise line-segment.

    Returns
    -------
    tuple of two lists of :class:`_LineEdgeIntersection`
        ``(intersections_a, intersections_b)`` for :attr:`~Beam2D.edge_a`
        and :attr:`~Beam2D.edge_b` respectively.
    """
    intersections_a = []
    intersections_b = []
    for index, edge in enumerate(outline.lines):
        for blank_edge, results in zip(beam.edges, (intersections_a, intersections_b)):
            if limit_to_segments:
                pt = intersection_segment_segment(blank_edge, edge)[0]
            else:
                pt = intersection_line_segment(blank_edge, edge)[0]
            if pt:
                d = dot_vectors(Vector.from_start_end(blank_edge.start, pt), blank_edge.direction)
                results.append(_BeamOutlineIntersection(Point(*pt), d, index, edge))
    return intersections_a, intersections_b

def _parse_simple_intersections(ints_a, ints_b):
    # type: (list[_BeamOutlineIntersection], list[_BeamOutlineIntersection]) -> list[_ParsedIntersection]
    """Both blank edges hit the same boundary edge → SINGLE.

           |
           |
           |
         __|____________
        |  |
        |  |    beam
        |__|____________
           |
           |
           |
           |outline

    """
    keys_a = {i.edge_index for i in ints_a}
    keys_b = {i.edge_index for i in ints_b}
    # Single intersection if one edge hits both blank edges.
    shared = keys_a & keys_b
    simple_intersections = []
    for k in shared:
        ia = next(i for i in ints_a if i.edge_index == k)
        ib = next(i for i in ints_b if i.edge_index == k)
        simple_intersections.append(
            _ParsedIntersection(
                type=IntersectionType.SINGLE,
                point=(ia.point + ib.point) * 0.5,
                dot=(ia.dot + ib.dot) * 0.5,
            )
        )
    for i in list(ints_a):
        if i.edge_index in shared:
            ints_a.remove(i)
    for i in list(ints_b):
        if i.edge_index in shared:
            ints_b.remove(i)
    return simple_intersections

def _parse_corner_intersections(ints_a, ints_b, outline):
    # type: (list[_BeamOutlineIntersection], list[_BeamOutlineIntersection], Polyline) -> list[_ParsedIntersection]
    """Each blank edge hits an adjacent boundary edge → CORNER.

              /
             /
          __/___________
         | /
         | |    beam
         |_|____________
           |
           |
           |
           |outline

    At a CORNER the intersection point sits at a boundary corner shared by two
    beams, so :meth:`BeamGeneratorIntersection.resolve` will return two entries
    in :attr:`~BeamGeneratorIntersection.connecting_beams`.
    """
    edge_count = len(outline.lines)
    corner_intersections = []
    for ia in ints_a:
        adjacent = {(ia.edge_index - 1) % edge_count, (ia.edge_index + 1) % edge_count}
        for ib in ints_b:
            if ib.edge_index in adjacent:
                corner_intersections.append(
                    _ParsedIntersection(
                        type=IntersectionType.CORNER,
                        point=(ia.point + ib.point) * 0.5,
                        dot=(ia.dot + ib.dot) * 0.5,
                    )
                )
                if ia in ints_a:
                    ints_a.remove(ia)
                if ib in ints_b:
                    ints_b.remove(ib)
                break
    return corner_intersections

def _parse_notch_intersections(ints_a, ints_b, beam, outline):
    # type: (list[_BeamOutlineIntersection], list[_BeamOutlineIntersection], Beam2D, Polyline) -> list[_ParsedIntersection]
    """One blank edge hits two adjacent boundary edges → NOTCH.

        |    |  /    
        |    | /    
        |    |/    
        |    /    
        |   /|   
        |  /_|_____outline
        |    |
        |    |
        |    |
        |beam|

    Uses :meth:`~Beam2D.contains_point` to check whether the corner shared
    by the two consecutive boundary edges lies inside the beam's blank, which
    is more reliable than comparing edge-index adjacency alone.

    This may also result in a 3-beam corner that should be resolved using a
    ``Cluster``.
    """
    if not ints_a and not ints_b:
        return []

    edge_count = len(outline.lines)

    def _get_notch_intersections_for_side(intersection_set, beam):
        leftovers = [i for i in intersection_set]
        notch_intersections = []
        # in case the first and last edges of the boundary make a notch, rotate
        if intersection_set and beam.contains_point(intersection_set[0].line.start):
            intersection_set.append(intersection_set.pop(0))
        i = 0
        while i < len(intersection_set) - 1:
            first_int, second_int = intersection_set[i : i + 2]
            if second_int.edge_index - first_int.edge_index == 1 or (
                first_int.edge_index == edge_count - 1 and second_int.edge_index == 0
            ):
                if beam.contains_point(first_int.line.end):
                    notch_intersections.append(
                        _ParsedIntersection(
                            type=IntersectionType.NOTCH,
                            point=(first_int.point + second_int.point) * 0.5,
                            dot=(first_int.dot + second_int.dot) * 0.5,
                        )
                    )
                    i += 1  # skip next intersection — it's consumed
                    if first_int in leftovers:
                        leftovers.remove(first_int)
                    if second_int in leftovers:
                        leftovers.remove(second_int)
            i += 1
        return notch_intersections, leftovers

    side_a_notches, ints_a = _get_notch_intersections_for_side(ints_a, beam) if ints_a else ([], [])
    side_b_notches, ints_b = _get_notch_intersections_for_side(ints_b, beam) if ints_b else ([], [])
    return side_a_notches + side_b_notches

def _parse_lap_intersections(ints_a, ints_b, beam, outline):
    # type: (list[_BeamOutlineIntersection], list[_BeamOutlineIntersection], Beam2D, Polyline) -> list[_ParsedIntersection]
    """Blank edges cross non-adjacent boundary edges with a corner inside the beam → LAP.
        _________
        |       |
        |       |
        |    ___|___
        |   |   |   
        |   |   |   
        |   |   |   
        |   |   |   
        |   |___|___ outline
        |       |
        |       |
        |       |
        |    ___|___outline
        |   |   |   
        |   |   |   
        |   |   |   
        |   |   |   
     ___|___|   |
        |       |
        |       |
        | beam  |
        |_______|

    Uses :meth:`~Beam2D.contains_point` to check whether the boundary
    corner between each consecutive pair of intersected edges lies inside the
    beam's blank, which is more accurate than a distance check.
    """
    if not ints_a and not ints_b:
        return []

    lap_intersections = []
    intersections = [i for i in ints_a] + [i for i in ints_b]
    intersections.sort(key=lambda x: x.edge_index)

    # handle wrap-around: if the boundary starts inside the beam, rotate list
    if intersections and beam.contains_point(intersections[0].line.start):
        intersections.append(intersections.pop(0))

    for pair in pairwise(intersections):
        if beam.contains_point(pair[0].line.end):
            lap_intersections.append(
                _ParsedIntersection(
                    type=IntersectionType.LAP,
                    point=(pair[0].point + pair[1].point) * 0.5,
                    dot=(pair[0].dot + pair[1].dot) * 0.5,
                )
            )
    return lap_intersections


# =============================================================================
# Public intersection classes
# =============================================================================


class BeamGeneratorIntersection(object):
    """Records where a :class:`~timber_design.populators.Beam2D` blank intersects a generator outline.

    Used for splitting and culling beams along a generator boundary.  Call
    :meth:`resolve` after all generators have finished
    :meth:`~timber_design.populators.ElementGenerator.generate_elements` to
    populate :attr:`connecting_beams`.

    Parameters
    ----------
    type : str
        One of :class:`IntersectionType`.
    dot : float
        Signed distance from the beam's start to the intersection along its
        centerline.  Used to determine the split position.
    generator : :class:`~timber_design.populators.ElementGenerator` or None
        The generator whose outline was intersected.  ``None`` for the
        synthetic start/end sentinels inside
        :func:`split_beam_with_element_generators`.
    """

    def __init__(self, type, dot, generator):
        self.type = type
        self.dot = dot
        self.generator = generator

    @classmethod
    def from_beam_and_generator(cls, beam, element_generator, limit_to_segments=True, skip_notches=False, skip_laps=False):
        # type: (Beam2D, ElementGenerator, bool, bool, bool) -> list[BeamGeneratorIntersection]
        """Detect and classify intersections between *beam*'s blank and *element_generator*'s outline.

        Parameters
        ----------
        beam : :class:`~timber_design.populators.Beam2D`
        element_generator : :class:`~timber_design.populators.ElementGenerator`
        limit_to_segments : bool
            When ``True`` (default) only segment-segment intersections are
            considered.  Set to ``False`` when extending beams to the nearest
            boundary.
        skip_notches : bool
            Skip :attr:`~IntersectionType.NOTCH` classification (also implies
            ``skip_laps``).
        skip_laps : bool
            Skip :attr:`~IntersectionType.LAP` classification only.
        """
        if element_generator.outline is None:
            return []
        outline = element_generator.outline
        ints_a, ints_b = _get_beam_outline_intersections(beam, outline, limit_to_segments)

        parsed = _parse_simple_intersections(ints_a, ints_b)
        parsed.extend(_parse_corner_intersections(ints_a, ints_b, outline))

        if not skip_notches:
            parsed.extend(_parse_notch_intersections(ints_a, ints_b, beam, outline))
            if not skip_laps:
                parsed.extend(_parse_lap_intersections(ints_a, ints_b, beam, outline))

        return [cls(pi.type, pi.dot, element_generator) for pi in parsed]


# =============================================================================
# Public functions
# =============================================================================

def split_beam_with_element_generators(beam, element_generators, skip_notches=False, skip_laps=False):
    # type: (Beam2D, list[ElementGenerator], bool, bool) -> tuple[list[tuple], list[DirectRule]]
    """Split *beam* at every intersection with the outlines of *element_generators*.

    Returns a list of ``(beam_segment, (start_bgi, end_bgi))`` tuples.  Each
    :class:`BeamGeneratorIntersection` has its
    :attr:`~BeamGeneratorIntersection.connecting_beams` already resolved so
    callers can iterate them directly.

    Parameters
    ----------
    beam : :class:`~timber_design.populators.Beam2D`
    element_generators : list[:class:`~timber_design.populators.ElementGenerator`]
    ignore_notches : bool
        Skip NOTCH (and LAP) classification.
    ignore_laps : bool
        Skip LAP classification only.

    Returns
    -------
    beam_int_tuples : list of ``(Beam2D | None, (BGI | None, BGI | None))``
    rules_to_remove : list[:class:`~timber_design.workflow.DirectRule`]
        Joint rules that were on culled segments and must be removed from the
        populator's rule list.
    """
    beam_segs = [beam]
    rules_to_cull = []
    for generator in element_generators:
        temp_beams = []        
        for seg in beam_segs:
            temp_segs, rules = generator.trim_beam(seg)
            temp_beams.extend(temp_segs)
            rules_to_cull.extend(rules)
        beam_segs = temp_beams

    return beam_segs, rules_to_cull

def extend_beam_to_closest_element_generators(beam, element_generators, only_start=False, only_end=False):
    # type: (Beam2D, list[ElementGenerator], bool, bool) -> None
    """Extend *beam* in-place so its ends reach the nearest generator outlines.

    Parameters
    ----------
    beam : :class:`~timber_design.populators.Beam2D`
    element_generators : list[:class:`~timber_design.populators.ElementGenerator`]
    only_start : bool
        Extend only the start end.
    only_end : bool
        Extend only the end.
    """
    if only_end and only_start:
        raise ValueError("Beam is overconstrained; only one of `only_start` and `only_end` can be True: {}".format(beam))

    intersections = []
    for eg in element_generators:
        intersections.extend(
            BeamGeneratorIntersection.from_beam_and_generator(
                beam, eg, limit_to_segments=False, skip_notches=True, skip_laps=True
            )
        )
    if not intersections:
        return

    intersections.sort(key=lambda x: x.dot)

    def get_bottom_dot(intersections):
        """Get the highest negative .dot value, consuming all negative entries."""
        if not intersections or intersections[0].dot > 0:
            return None
        bottom = intersections.pop(0)
        while intersections:
            if intersections[0].dot > 0:
                break
            bottom = intersections.pop(0)
        return bottom.dot

    def get_top_dot(beam, intersections):
        """Get the lowest .dot value beyond beam.length, consuming all such entries."""
        if not intersections or intersections[-1].dot < beam.length:
            return None
        top = intersections.pop()
        while intersections:
            if intersections[-1].dot < beam.length:
                break
            top = intersections.pop(-1)
        return top.dot

    bottom_dot = get_bottom_dot(intersections) if not only_end else None
    top_dot = get_top_dot(beam, intersections) if not only_start else None

    if bottom_dot is not None:
        beam.transform(Translation.from_vector(beam.frame.xaxis * bottom_dot))

    start = bottom_dot if bottom_dot is not None else 0
    end = top_dot if top_dot is not None else beam.length
    beam.length = end - start
