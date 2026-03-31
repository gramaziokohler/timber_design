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

from timber_design.populators.beam2d import Beam2D


# =============================================================================
# Internal types
# =============================================================================


class _BeamEdgeOutlineIntersection(object):
    """Internal: a single intersection between one beam blank edge and one boundary edge.

    Used by :func:`_get_beam_edge_outline_intersections` for the TOPO_X test
    in :mod:`~timber_design.populators.model2d`.
    """

    def __init__(self, point, dot, edge_index, line):
        self.point = point
        self.dot = dot
        self.edge_index = edge_index
        self.line = line

    @classmethod
    def from_beam_and_outline(cls, beam, outline, limit_to_segments=True):
        # type: (Beam2D, Polyline, bool) -> tuple[list, list]
        """Intersect the two blank side-edges of *beam* against every segment of *outline*.

        Returns
        -------
        tuple of two lists of :class:`_BeamEdgeOutlineIntersection`
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
                    results.append(cls(Point(*pt), d, index, edge))
        return intersections_a, intersections_b


class _ParsedIntersection(NamedTuple):
    """Internal: a classified intersection result."""

    type: str
    point: Point
    dots: list


# =============================================================================
# Intersection type constants
# =============================================================================


class IntersectionType(object):
    """Geometric classification of a beam blank intersection with a generator boundary.

    Attributes
    ----------
    SINGLE : str
        One generator outline edge spans the full beam width — both long blank
        edges crossed by the same boundary segment.  T-topology.
    CORNER : str
        The beam blank crosses from one long face to the other through a single
        generator corner.  Adjacent boundary edges cross different long faces.
        Y / K topology (primary beam is the main/end beam).
    NOTCH : str
        One generator corner dips into the same long face it entered from.
        Adjacent boundary edges both cross the same long blank face.
    LAP : str
        Two or more generator corners lie inside the beam blank.
        The beam passes through a generator region.  X / lap topology.
    """

    SINGLE = "single"
    CORNER = "corner"
    NOTCH = "notch"
    LAP = "lap"


# =============================================================================
# New core: outline-walk crossing detection
# =============================================================================

# beam.blank_outline.lines indices
# 0  bl→br   edge_a direction   (long face, -yaxis side)
# 1  br→tr   end cap            (beam end)
# 2  tr→tl   edge_b reversed    (long face, +yaxis side)
# 3  tl→bl   start cap          (beam start)
_LONG_FACE_INDICES = frozenset({0, 2})


def _find_crossings(beam, outline, limit_to_segments=True, skip_notches=False, skip_laps=False):
    # type: (Beam2D, Polyline, bool, bool, bool) -> list[_ParsedIntersection]
    """Walk every edge of *outline* and detect how it enters and exits *beam*'s blank.

    Algorithm
    ---------
    1. For each outline edge, find intersections with every edge of
       ``beam.blank_outline`` (the four-sided beam rectangle).
    2. Determine whether each outline edge is **entering** or **exiting** the
       beam blank by checking ``beam.contains_point`` on the edge endpoints.
    3. Pair consecutive entry/exit crossings, counting how many outline corners
       between them lie inside the beam blank.
    4. Classify each pair by the *beam blank edge indices* crossed:

       * **Same outline edge** (0 corners between): **SINGLE**
       * **1 corner inside, different long faces** (0↔2): **CORNER**
       * **1 corner inside, same long face** (0→0 or 2→2): **NOTCH**
       * **≥2 corners inside**: **LAP**

    Only crossings through the long faces (blank_outline indices 0 and 2) are
    used for intersection classification.  End-cap crossings are ignored because
    they correspond to the beam travelling *along* the generator boundary, which
    is not a trim-worthy event.

    Parameters
    ----------
    beam : :class:`~timber_design.populators.Beam2D`
    outline : :class:`compas.geometry.Polyline`
    limit_to_segments : bool
        When ``False``, the long blank edges are treated as infinite lines so
        that intersections outside the beam's current extents are found (used
        for extending beams to a generator boundary).
    skip_notches : bool
    skip_laps : bool

    Returns
    -------
    list[:class:`_ParsedIntersection`]
    """
    blank_lines = beam.blank_outline.lines  # 4 edges: edge_a(0), end-cap(1), edge_b-rev(2), start-cap(3)
    n_outline = len(outline.lines)

    def _beam_dot(pt):
        return dot_vectors(Vector.from_start_end(beam.frame.point, pt), beam.frame.xaxis)

    def _intersect_with_blank_edge(gen_edge, blank_idx):
        blank_edge = blank_lines[blank_idx]
        if not limit_to_segments and blank_idx in _LONG_FACE_INDICES:
            result = intersection_line_segment(blank_edge, gen_edge)
        else:
            result = intersection_segment_segment(gen_edge, blank_edge)
        pt = result[0] if result else None
        return Point(*pt) if pt else None

    # ------------------------------------------------------------------
    # Step 1: collect all (outline_idx, blank_idx, point) intersections
    # ------------------------------------------------------------------
    all_hits = []  # list of (outline_idx, blank_idx, Point)
    for i, gen_edge in enumerate(outline.lines):
        for j in range(4):
            pt = _intersect_with_blank_edge(gen_edge, j)
            if pt is not None:
                all_hits.append((i, j, pt))

    # Filter to long-face hits only (indices 0 and 2)
    long_hits = [(i, j, pt) for (i, j, pt) in all_hits if j in _LONG_FACE_INDICES]

    if not long_hits:
        return []

    # Group long_hits by outline edge index
    by_outline = {}
    for i, j, pt in all_hits:
        by_outline.setdefault(i, []).append((j, pt))

    # ------------------------------------------------------------------
    # Step 2: walk outline edges, track inside/outside, pair entry/exit
    # ------------------------------------------------------------------

    def _corners_between(entry_i, exit_i):
        """Outline corner points between edge entry_i and edge exit_i (wrap-aware).

        The corner *after* edge k is ``outline.lines[k].end``.  We collect
        every such corner from ``entry_i`` up to (but not including) ``exit_i``,
        wrapping around the closed outline when ``entry_i > exit_i``.
        """
        if entry_i <= exit_i:
            k_range = range(entry_i, exit_i)
        else:
            k_range = list(range(entry_i, n_outline)) + list(range(0, exit_i))
        return [
            outline.lines[k].end
            for k in k_range
            if beam.contains_point(outline.lines[k].end)
        ]

    inside = beam.contains_point(outline.lines[0].start)
    current_entry = None       # (outline_idx, blank_idx, Point)
    pending_initial_exit = None  # exit recorded before any entry (outline started inside beam)
    crossings = []             # list of (entry, exit, corners_inside)

    for i in range(n_outline):
        hits = by_outline.get(i, [])

        if len(hits) == 2 and not inside:
            # Outline edge traverses the full beam width in one step
            gen_edge = outline.lines[i]
            direction = Vector.from_start_end(gen_edge.start, gen_edge.end)
            hits_sorted = sorted(
                hits,
                key=lambda h: dot_vectors(Vector.from_start_end(gen_edge.start, h[1]), direction),
            )
            entry = (i, hits_sorted[0][0], hits_sorted[0][1])
            exit_ = (i, hits_sorted[1][0], hits_sorted[1][1])
            crossings.append((entry, exit_, []))
            # inside stays False

        elif len(hits) == 1:
            j, pt = hits[0]
            if not inside:
                current_entry = (i, j, pt)
                inside = True
            else:
                # Exiting
                exit_ = (i, j, pt)
                if current_entry is not None:
                    corners_inside = _corners_between(current_entry[0], i)
                    crossings.append((current_entry, exit_, corners_inside))
                    current_entry = None
                else:
                    # Outline started inside the beam — save exit for wrap-around pairing
                    pending_initial_exit = exit_
                inside = False

        # 0 hits: continuing inside or outside with no crossing

    # Wrap-around: entry near the end of the outline, exit at the beginning.
    # This happens when the outline's first point (corner) is inside the beam.
    if current_entry is not None and pending_initial_exit is not None:
        corners_inside = _corners_between(current_entry[0], pending_initial_exit[0])
        crossings.append((current_entry, pending_initial_exit, corners_inside))

    # ------------------------------------------------------------------
    # Step 3: classify each (entry, exit, corners_inside) crossing
    # ------------------------------------------------------------------
    parsed = []
    for entry, exit_, corners_inside in crossings:
        entry_i, entry_b, entry_pt = entry
        exit_i, exit_b, exit_pt = exit_
        n_corners = len(corners_inside)
        midpt = (entry_pt + exit_pt) * 0.5
        d_entry = _beam_dot(entry_pt)
        d_exit = _beam_dot(exit_pt)

        if entry_i == exit_i:
            # Same outline edge — SINGLE (T-type transverse cut)
            parsed.append(_ParsedIntersection(
                type=IntersectionType.SINGLE,
                point=midpt,
                dots=[d_entry, d_exit],
            ))

        elif n_corners == 1:
            corner_dot = _beam_dot(corners_inside[0])
            if entry_b == exit_b:
                # Same long faces — NOTCH
                parsed.append(_ParsedIntersection(
                    type=IntersectionType.NOTCH,
                    point=midpt,
                    dots=[d_entry, d_exit, corner_dot],
                ))
            elif entry_b in _LONG_FACE_INDICES and exit_b in _LONG_FACE_INDICES:
                # Different long face or mixed with end cap — CORNER
                if not skip_notches:
                    parsed.append(_ParsedIntersection(
                        type=IntersectionType.CORNER,
                        point=midpt,
                        dots=[d_entry, d_exit, corner_dot],
                    ))
            elif entry_b in _LONG_FACE_INDICES or exit_b in _LONG_FACE_INDICES:
                # Different long face or mixed with end cap — CORNER
                if not skip_laps:
                    parsed.append(_ParsedIntersection(
                        type=IntersectionType.LAP,
                        point=midpt,
                        dots=[d_entry, d_exit, corner_dot],
                    ))
            else:
                # Both entry and exit through end caps raise error
                raise ValueError("Invalid crossing with entry and exit through beam end faces")
        elif n_corners >= 2:
            if not skip_laps:
                parsed.append(_ParsedIntersection(
                    type=IntersectionType.LAP,
                    point=midpt,
                    dots=[d_entry, d_exit]+[_beam_dot(pt) for pt in corners_inside],
                ))

    return parsed


# =============================================================================
# Module-level utility  (used by model2d for TOPO_X detection)
# =============================================================================


def _get_beam_edge_outline_intersections(beam, outline, limit_to_segments=True):
    # type: (Beam2D, Polyline, bool) -> tuple[list, list]
    """Return ``(ints_a, ints_b)`` lists of :class:`_BeamEdgeOutlineIntersection`.

    Intersects :attr:`~Beam2D.edge_a` and :attr:`~Beam2D.edge_b` against every
    segment of *outline*.  Used by
    :func:`~timber_design.populators.model2d.ConnectionSolver2D.find_topology`
    for TOPO_X detection.
    """
    return _BeamEdgeOutlineIntersection.from_beam_and_outline(beam, outline, limit_to_segments)


# =============================================================================
# Public intersection class
# =============================================================================


class BeamGeneratorIntersection(object):
    """Records where a :class:`~timber_design.populators.Beam2D` blank intersects a generator outline.

    Parameters
    ----------
    type : str
        One of :class:`IntersectionType`.
    dots : list[float] or float
        Positions along the beam centreline where the generator boundary
        crosses the blank.  Two values for SINGLE / LAP; three values (two
        crossing dots + one corner dot) for CORNER / NOTCH.  A bare scalar is
        accepted for the synthetic sentinel objects used inside
        :func:`split_beam_with_element_generators`.
    generator : :class:`~timber_design.populators.ElementGenerator` or None
    """

    def __init__(self, type, dots, generator):
        self.type = type
        self.dots = dots if isinstance(dots, list) else [dots, dots]
        self.generator = generator

    @property
    def dot(self):
        """Midpoint of the two crossing positions — used for sorting.

        Returns
        -------
        float
        """
        return (self.dots[0] + self.dots[1]) / 2.0

    @property
    def dot_start(self):
        """Outermost position toward the beam start across all stored dot values.

        Considers every dot in :attr:`dots` — including the corner dot stored
        for CORNER and NOTCH intersections — so that the full extent of the
        intersection zone is accounted for when maximising segment length.

        Returns
        -------
        float
        """
        return min(self.dots)

    @property
    def dot_end(self):
        """Outermost position toward the beam end across all stored dot values.

        Considers every dot in :attr:`dots` — including the corner dot stored
        for CORNER and NOTCH intersections — so that the full extent of the
        intersection zone is accounted for when maximising segment length.

        Returns
        -------
        float
        """
        return max(self.dots)

    @classmethod
    def from_beam_and_generator(cls, beam, element_generator, limit_to_segments=True, skip_notches=False, skip_laps=False):
        # type: (Beam2D, ElementGenerator, bool, bool, bool) -> list[BeamGeneratorIntersection]
        """Detect and classify intersections between *beam*'s blank and *element_generator*'s outline.

        Uses the outline-walk algorithm: iterates over every edge of the
        generator outline, finds where it enters and exits the beam blank, and
        classifies each entry/exit pair as SINGLE, CORNER, NOTCH, or LAP.

        Parameters
        ----------
        beam : :class:`~timber_design.populators.Beam2D`
        element_generator : :class:`~timber_design.populators.ElementGenerator`
        limit_to_segments : bool
            When ``False``, the beam's long blank edges are extended as
            infinite lines.  Use for :func:`extend_beam_to_closest_element_generators`.
        skip_notches : bool
        skip_laps : bool
        """
        if element_generator.outline is None:
            return []
        parsed = _find_crossings(
            beam,
            element_generator.outline,
            limit_to_segments=limit_to_segments,
            skip_notches=skip_notches,
            skip_laps=skip_laps,
        )
        return [cls(pi.type, pi.dots, element_generator) for pi in parsed]


# =============================================================================
# Public functions
# =============================================================================


def split_beam_with_element_generators(beam, element_generators, skip_notches=False, skip_laps=False):
    # type: (Beam2D, list[ElementGenerator], bool, bool) -> tuple[list, list]
    """Split *beam* at every intersection with the outlines of *element_generators*.

    Parameters
    ----------
    beam : :class:`~timber_design.populators.Beam2D`
    element_generators : list[:class:`~timber_design.populators.ElementGenerator`]
    skip_notches : bool
    skip_laps : bool

    Returns
    -------
    beam_segs : list[:class:`~timber_design.populators.Beam2D`]
    rules_to_cull : list
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
    only_end : bool
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
        """Highest negative dot (closest to 0 from below), consuming all negative entries."""
        if not intersections or intersections[0].dot > 0:
            return None
        bottom = intersections.pop(0)
        while intersections:
            if intersections[0].dot > 0:
                break
            bottom = intersections.pop(0)
        return bottom.dot_start  # outermost = farthest from beam centre

    def get_top_dot(beam, intersections):
        """Lowest dot beyond beam.length, consuming all such entries."""
        if not intersections or intersections[-1].dot < beam.length:
            return None
        top = intersections.pop()
        while intersections:
            if intersections[-1].dot < beam.length:
                break
            top = intersections.pop(-1)
        return top.dot_end  # outermost = farthest from beam centre

    bottom_dot = get_bottom_dot(intersections) if not only_end else None
    top_dot = get_top_dot(beam, intersections) if not only_start else None

    if bottom_dot is not None:
        beam.transform(Translation.from_vector(beam.frame.xaxis * bottom_dot))

    start = bottom_dot if bottom_dot is not None else 0
    end = top_dot if top_dot is not None else beam.length
    beam.length = end - start
