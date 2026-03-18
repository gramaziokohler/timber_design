from typing import Union
from typing import NamedTuple

from compas.geometry import Line
from compas.geometry import Point
from compas.geometry import Vector
from compas.geometry import distance_point_point
from compas.geometry import dot_vectors
from compas.geometry import intersection_line_segment
from compas.geometry import intersection_segment_segment
from compas.geometry import closest_point_on_line
from compas.itertools import pairwise

from timber_design.populators import ElementGenerator
from timber_design.populators import Beam2D
from timber_design.workflow import DirectRule


# =============================================================================
# Internal types
# =============================================================================


class _LineEdgeIntersection(object):
    """Internal: a single intersection between one beam blank edge and one boundary edge."""

    def __init__(self, point, dot, edge_index, line):
        self.point = point
        self.dot = dot
        self.edge_index = edge_index
        self.line = line


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
    by both :class:`BeamGeneratorIntersection` and :class:`BeamBeamIntersection`.

    Attributes
    ----------
    SINGLE : str
        Both blank edges cross the **same** boundary edge.
        The beam end meets a face → **T topology**.
    CORNER : str
        Each blank edge crosses an **adjacent** boundary edge, meaning the
        beam end lands at a corner where **two other beams already meet**.
        Resolving this intersection will yield two :attr:`connecting_beams`
        and requires a three-way (Y / corner cluster) joint.
        → **L / Y topology**.
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


def _get_beam_2d_intersections(beam, edges, limit_to_segments=True):
    # type: (Beam2D, dict, bool) -> tuple[list[_LineEdgeIntersection], list[_LineEdgeIntersection]]
    """Intersect the two blank side-edges of *beam* against every edge in *edges*.

    Parameters
    ----------
    beam : :class:`~timber_design.populators.Beam2D`
        The beam whose blank edges are being intersected.
    edges : dict[int, :class:`compas.geometry.Line`]
        Ordered boundary edges, keyed by index.
    limit_to_segments : bool
        When ``True`` use segment-segment intersection; otherwise line-segment.

    Returns
    -------
    tuple of two lists of :class:`_LineEdgeIntersection`
        ``(intersections_a, intersections_b)`` for :attr:`~Beam2D.blank_a`
        and :attr:`~Beam2D.blank_b` respectively.
    """
    intersections_a = []
    intersections_b = []
    for index, edge in edges.items():
        for blank_edge, results in [(beam.edges[0], intersections_a), (beam.edges[1], intersections_b)]:
            if limit_to_segments:
                pt = intersection_segment_segment(blank_edge, edge)[0]
            else:
                pt = intersection_line_segment(blank_edge, edge)[0]
            if pt:
                d = dot_vectors(Vector.from_start_end(blank_edge.start, pt), blank_edge.direction)
                results.append(_LineEdgeIntersection(Point(*pt), d, index, blank_edge))
    return intersections_a, intersections_b


def _parse_simple_intersections(ints_a, ints_b, beam, edges):
    # type: (list, list, Beam2D, dict) -> tuple[list[_ParsedIntersection], list, list]
    """Both blank edges hit the same boundary edge → SINGLE.

        |   |
        |   |
        |   |
        |  _|____________
        |   |
        |  _|____________     
        |   |
        |   |
        |   |
        |   |

    """
    keys_a = {i.edge_index for i in ints_a}
    keys_b = {i.edge_index for i in ints_b}
    shared = keys_a & keys_b
    results = []
    for k in shared:
        ia = next(i for i in ints_a if i.edge_index == k)
        ib = next(i for i in ints_b if i.edge_index == k)
        results.append(
            _ParsedIntersection(
                type=IntersectionType.SINGLE,
                point=(ia.point + ib.point) * 0.5,
                dot=(ia.dot + ib.dot) * 0.5,
            )
        )
    leftovers_a = [i for i in ints_a if i.edge_index not in shared]
    leftovers_b = [i for i in ints_b if i.edge_index not in shared]
    return results, leftovers_a, leftovers_b


def _parse_corner_intersections(ints_a, ints_b, beam, edges):
    # type: (list, list, Beam2D, dict) -> tuple[list[_ParsedIntersection], list, list]
    """Each blank edge hits an adjacent boundary edge → CORNER.

           /   /
          /   /        
         / __/___________
        /   /
        |  _|____________     
        |   |
        |   |
        |   |
        |   |

    At a CORNER the intersection point sits at a boundary corner shared by two
    beams, so :meth:`BeamGeneratorIntersection.resolve` will return two entries
    in :attr:`~BeamGeneratorIntersection.connecting_beams`.
    """
    edge_count = len(edges)
    leftovers_a = list(ints_a)
    leftovers_b = list(ints_b)
    results = []
    for ia in ints_a:
        adjacent = {(ia.edge_index - 1) % edge_count, (ia.edge_index + 1) % edge_count}
        for ib in ints_b:
            if ib.edge_index in adjacent:
                results.append(
                    _ParsedIntersection(
                        type=IntersectionType.CORNER,
                        point=(ia.point + ib.point) * 0.5,
                        dot=(ia.dot + ib.dot) * 0.5,
                    )
                )
                if ia in leftovers_a:
                    leftovers_a.remove(ia)
                if ib in leftovers_b:
                    leftovers_b.remove(ib)
                break
    return results, leftovers_a, leftovers_b


def _parse_notch_intersections(ints_a, ints_b, beam, edges):
    # type: (list, list, Beam2D, dict) -> tuple[list[_ParsedIntersection], list, list]
    """One blank edge hits two adjacent boundary edges → NOTCH.

        |   |  /    /
        |   | /    /
        |   |/    /
        |   /    /
        |  /|   /
        |  \|   \
        |   \    \
        |   |\    \
        |   | \    \
        |   |  \    \


        This may also result in a 3-Beam corner that should be resolved using a `Cluster`
    """



    edge_count = len(edges)
    results = []
    consumed = []
    for group in [ints_a, ints_b]:
        for first in group:
            if first in consumed:
                continue
            adjacent = {(first.edge_index - 1) % edge_count, (first.edge_index + 1) % edge_count}
            for second in group:
                if second is not first and second not in consumed and second.edge_index in adjacent:
                    results.append(
                        _ParsedIntersection(
                            type=IntersectionType.NOTCH,
                            point=(first.point + second.point) * 0.5,
                            dot=(first.dot + second.dot) * 0.5,
                        )
                    )
                    consumed.extend([first, second])
                    break
    leftovers_a = [i for i in ints_a if i not in consumed]
    leftovers_b = [i for i in ints_b if i not in consumed]
    return results, leftovers_a, leftovers_b


def _parse_lap_intersections(ints_a, ints_b, beam, edges):
    # type: (list, list, Beam2D, dict) -> list[_ParsedIntersection]
    """Blank edges cross non-adjacent boundary edges with a corner inside the beam → LAP.

        |       |
        |       |
        |       |
        |       |
        |    ___|___
        |   |   |   |
        |   |   |   |
        |   |   |   |
        |   |   |   |
        |   |   |   |
        |   |   |   |
        |___|___|   |
            |       |
            |       |
            |       |
            |       |


    """
    edge_count = len(edges)
    indices = sorted({i.edge_index for i in ints_a + ints_b})
    if len(indices) < 2:
        return []
    indices.append(indices[0] + edge_count)
    results = []
    for lo, hi in pairwise(indices):
        corner = edges[lo % edge_count].end
        closest = closest_point_on_line(corner, beam.centerline)
        dist = distance_point_point(
            Point(corner[0], corner[1], 0.0),
            Point(closest[0], closest[1], 0.0),
        )
        if dist < beam.width / 2.0:
            results.append(
                _ParsedIntersection(
                    type=IntersectionType.LAP,
                    point=beam.centerline.midpoint,
                    dot=beam.length / 2.0,
                )
            )
    return results


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
    point : :class:`compas.geometry.Point`
        Approximate 2D location of the intersection.
    dot : float
        Signed distance from the beam's start to the intersection along its
        centerline.  Used to determine the split position.
    beam : :class:`~timber_design.populators.Beam2D`
        The beam whose blank was intersected.
    generator : :class:`~timber_design.populators.ElementGenerator` or None
        The generator whose outline was intersected.  ``None`` for the
        synthetic start/end sentinels inside
        :func:`split_beam_with_element_generators`.

    Attributes
    ----------
    connecting_beams : list[:class:`~timber_design.populators.Beam2D`]
        Generator elements whose blank contains :attr:`point`.  Empty until
        :meth:`resolve` is called.

        For :attr:`~IntersectionType.CORNER` intersections this list will
        contain **two** beams (the two beams meeting at that boundary corner).
        These should be joined as a cluster rather than as two independent
        joints.

        .. todo::

            Use ``compas_timber.connections.Cluster`` (via
            ``MaxNCompositeAnalyzer``) when resolving CORNER joints with two
            connecting beams instead of creating two separate
            :class:`~timber_design.workflow.DirectRule` objects.
    """

    def __init__(self, type, point, dot, beam, generator):
        self.type = type
        self.point = point
        self.dot = dot
        self.beam = beam
        self.generator = generator
        self.connecting_beams = []  # type: list[Beam2D]

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
        edges = element_generator.edges
        ints_a, ints_b = _get_beam_2d_intersections(beam, edges, limit_to_segments)

        parsed, ints_a, ints_b = _parse_simple_intersections(ints_a, ints_b, beam, edges)
        corners, ints_a, ints_b = _parse_corner_intersections(ints_a, ints_b, beam, edges)
        parsed.extend(corners)

        if not skip_notches:
            notches, ints_a, ints_b = _parse_notch_intersections(ints_a, ints_b, beam, edges)
            parsed.extend(notches)
            if not skip_laps:
                parsed.extend(_parse_lap_intersections(ints_a, ints_b, beam, edges))

        return [cls(pi.type, pi.point, pi.dot, beam, element_generator) for pi in parsed]

    def resolve(self):
        """Populate :attr:`connecting_beams` from the generator's current elements.

        A generator element is *connecting* when :attr:`point` falls inside its
        2D blank (see :meth:`~timber_design.populators.Beam2D.contains_point`).

        For :attr:`~IntersectionType.CORNER` intersections two beams will be
        found — one for each of the adjacent boundary edges.  The caller is
        responsible for handling the multi-beam case appropriately.
        """
        if not self.generator:
            return
        self.connecting_beams = [
            e for e in self.generator.elements
            if isinstance(e, Beam2D) and e.contains_point(self.point)
        ]


class BeamBeamIntersection(object):
    """Records a 2D blank-space intersection between two :class:`~timber_design.populators.Beam2D` beams.

    Used for joint creation in both the generator-boundary and the
    cross-generator collision-detection workflows.

    The :attr:`type` maps directly to timber joint topologies:

    +---------+------------------+-------------------------------+
    | Type    | Topology         | Typical joint                 |
    +=========+==================+===============================+
    | SINGLE  | T                | TButtJoint                    |
    +---------+------------------+-------------------------------+
    | CORNER  | L / Y            | LButtJoint / corner cluster   |
    +---------+------------------+-------------------------------+
    | LAP     | X                | XLapJoint                     |
    +---------+------------------+-------------------------------+
    | NOTCH   | half-lap / notch | custom                        |
    +---------+------------------+-------------------------------+

    Parameters
    ----------
    type : str
        One of :class:`IntersectionType`.
    point : :class:`compas.geometry.Point`
        Approximate 2D location of the intersection.
    dot_a : float
        Position of the intersection along *beam_a*'s centerline (signed
        distance from start).
    beam_a : :class:`~timber_design.populators.Beam2D`
        The beam whose blank was intersected against *beam_b*.
    beam_b : :class:`~timber_design.populators.Beam2D`
        The beam whose blank boundary was used as the intersection target.
    """

    def __init__(self, type, point, dot_a, beam_a, beam_b):
        self.type = type
        self.point = point
        self.dot_a = dot_a
        self.beam_a = beam_a
        self.beam_b = beam_b

    @classmethod
    def from_beam_pair(cls, beam_a, beam_b, limit_to_segments=True):
        # type: (Beam2D, Beam2D, bool) -> list[BeamBeamIntersection]
        """Detect all blank-space intersections between *beam_a* and *beam_b*.

        *beam_b*'s :attr:`~Beam2D.blank_edges` are used as the boundary, so
        the result describes how *beam_a* relates to *beam_b*.

        For a symmetric result (e.g. to find joints regardless of element
        ordering) call this twice with swapped arguments and deduplicate by
        type.

        Parameters
        ----------
        beam_a : :class:`~timber_design.populators.Beam2D`
        beam_b : :class:`~timber_design.populators.Beam2D`
        limit_to_segments : bool
            When ``True`` (default) only overlapping blank regions produce
            results.
        """
        edges = beam_b.blank_edges
        ints_a, ints_b = _get_beam_2d_intersections(beam_a, edges, limit_to_segments)

        parsed, ints_a, ints_b = _parse_simple_intersections(ints_a, ints_b, beam_a, edges)
        corners, ints_a, ints_b = _parse_corner_intersections(ints_a, ints_b, beam_a, edges)
        parsed.extend(corners)
        notches, ints_a, ints_b = _parse_notch_intersections(ints_a, ints_b, beam_a, edges)
        parsed.extend(notches)
        parsed.extend(_parse_lap_intersections(ints_a, ints_b, beam_a, edges))

        return [cls(pi.type, pi.point, pi.dot, beam_a, beam_b) for pi in parsed]


# =============================================================================
# Public functions
# =============================================================================


def split_beam_with_element_generators(beam, element_generators, ignore_notches=False, ignore_laps=False):
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
    from compas.geometry import Translation

    intersections = [
        BeamGeneratorIntersection(None, beam.frame.point, 0.0, beam, None),
        BeamGeneratorIntersection(None, beam.frame.point + beam.frame.xaxis * beam.length, beam.length, beam, None),
    ]

    for generator in element_generators:
        intersections.extend(
            BeamGeneratorIntersection.from_beam_and_generator(
                beam, generator, skip_notches=ignore_notches, skip_laps=ignore_laps
            )
        )

    if len(intersections) == 2:  # no intersections found
        for element_generator in element_generators:
            if element_generator.cull_element_at_point(beam.centerline.midpoint):
                return [(None, (None, None))], list(beam.attributes.get("joint_defs", {}).values())
        return [(beam, (None, None))], []

    intersections.sort(key=lambda x: x.dot)

    # Resolve connecting_beams now that all generators' elements are finalised.
    for bgi in intersections:
        bgi.resolve()

    beam_int_tuples = []
    rules_to_remove = []
    for pair in pairwise(intersections):
        beam_seg = _get_beam_segment(beam, pair[0].dot, pair[1].dot)
        for element_generator in [pair[0].generator, pair[1].generator]:
            if element_generator and element_generator.cull_element_at_point(beam_seg.centerline.midpoint):
                rules_to_remove.extend(beam_seg.attributes.pop("joint_defs", {}).values())
                break
        else:
            beam_int_tuples.append((beam_seg, pair))
    return beam_int_tuples, rules_to_remove


def _get_beam_segment(beam, start_length, end_length):
    # type: (Beam2D, float, float) -> Beam2D
    from compas.geometry import Translation

    beam_seg = beam.copy()
    beam_seg.transform(Translation.from_vector(beam.frame.xaxis * start_length))
    beam_seg.length = end_length - start_length
    for feature in beam.features:
        feature.beam = beam_seg
    for dot, rule in beam.attributes.get("joint_defs", {}).items():
        if start_length < dot < end_length:
            rule.elements[rule.elements.index(beam)] = beam_seg
            shifted_dot = dot - start_length
            if beam_seg.attributes.get("joint_defs") is None:
                beam_seg.attributes["joint_defs"] = {}
            beam_seg.attributes["joint_defs"][shifted_dot] = rule
    return beam_seg


def extend_beam_to_closest_element_generators(beam, element_generators, only_start=False, only_end=False):
    # type: (Beam2D, list[ElementGenerator], bool, bool) -> tuple[Union[Beam2D, None], Union[BeamGeneratorIntersection, None], Union[BeamGeneratorIntersection, None]]
    """Extend *beam* so its ends reach the nearest generator outlines.

    Parameters
    ----------
    beam : :class:`~timber_design.populators.Beam2D`
    element_generators : list[:class:`~timber_design.populators.ElementGenerator`]
    only_start : bool
        Extend only the start end.
    only_end : bool
        Extend only the end.

    Returns
    -------
    beam : :class:`~timber_design.populators.Beam2D` or None
    bottom_int : :class:`BeamGeneratorIntersection` or None
    top_int : :class:`BeamGeneratorIntersection` or None
    """
    from compas.geometry import Translation

    intersections = []
    for eg in element_generators:
        if eg.outline is not None:
            intersections.extend(
                BeamGeneratorIntersection.from_beam_and_generator(
                    beam, eg, limit_to_segments=False, skip_notches=True, skip_laps=True
                )
            )
    if not intersections:
        return beam, None, None

    intersections.sort(key=lambda x: x.dot)

    bottom_int = None
    top_int = None
    while intersections:
        previous_int = intersections.pop(0)
        if not bottom_int and intersections and intersections[0].dot > 0:
            bottom_int = previous_int
        if intersections and intersections[0].dot > beam.length:
            top_int = intersections[0]
            break

    if only_end and only_start:
        raise ValueError("Beam is overconstrained; only one of `only_start` and `only_end` can be True: {}".format(beam))

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
