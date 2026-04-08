from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from timber_design.populators import ElementGenerator

from compas.geometry import Point
from compas.geometry import Polyline
from compas.geometry import Translation
from compas.geometry import Vector
from compas.geometry import dot_vectors
from compas.geometry import intersection_line_segment
from compas.geometry import intersection_segment_segment

from timber_design.populators.beam2d import Beam2D


# =============================================================================
# Intersection data
# =============================================================================


class BeamOutlineIntersectionData(object):
    """Stores dot-position data for one entry/exit crossing of a generator outline through a beam blank.

    Parameters
    ----------
    start_dot : float or None
        Position along the beam centreline where the outline enters the blank.
        ``None`` when the outline began inside the beam (wrap-around case).
    end_dot : float or None
        Position along the beam centreline where the outline exits the blank.
        ``None`` when the outline ended inside the beam (wrap-around case).
    internal_dots : list[float]
        Positions of outline corners that lie inside the beam blank between
        ``start_dot`` and ``end_dot``.
    """

    def __init__(self, start_dot=None, end_dot=None, internal_dots=None):
        self.start_dot = start_dot
        self.end_dot = end_dot
        self.internal_dots = internal_dots or []

    @property
    def all_dots(self):
        """All dot positions: start, end (if not None), plus internal corners."""
        return [d for d in [self.start_dot, self.end_dot] if d is not None] + self.internal_dots

    @property
    def average_dot(self):
        """Mean of all dot positions, or ``None`` if no dots are available."""
        dots = self.all_dots
        return sum(dots) / len(dots) if dots else None


# =============================================================================
# Outline-walk crossing detection
# =============================================================================

# beam.blank_outline.lines indices
# 0  bl→br   edge_a direction   (long face, -yaxis side)
# 1  br→tr   end cap            (beam end)
# 2  tr→tl   edge_b reversed    (long face, +yaxis side)
# 3  tl→bl   start cap          (beam start)
_LONG_FACE_INDICES = frozenset({0, 2})


def find_beam_outline_crossings(beam, outline, limit_to_segments=True, skip_notches=False, skip_laps=False):
    # type: (Beam2D, Polyline, bool, bool, bool) -> list[BeamOutlineIntersectionData]
    """Walk every edge of *outline* and detect how it enters and exits *beam*'s blank.

    Parameters
    ----------
    beam : :class:`~timber_design.populators.Beam2D`
    outline : :class:`compas.geometry.Polyline`
    limit_to_segments : bool
        When ``False``, the long blank edges are treated as infinite lines so
        that intersections outside the beam's current extents are found (used
        for extending beams to a generator boundary).
    skip_notches : bool
        (reserved for future classification filtering)
    skip_laps : bool
        (reserved for future classification filtering)

    Returns
    -------
    list[:class:`BeamOutlineIntersectionData`]
    """
    blank_lines = beam.blank_outline.lines  # 4 edges: edge_a(0), end-cap(1), edge_b-rev(2), start-cap(3)
    n_outline = len(outline) - 1  # number of segments (points - 1 for closed polyline)

    def _beam_dot(pt):
        """Project *pt* onto the beam centreline and return the signed distance from beam start."""
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
    # Step 1: collect all dot-position intersection hits per outline segment
    # ------------------------------------------------------------------
    dots_by_outline = {}
    for i, gen_edge in enumerate(outline.lines):
        dots_by_outline[i] = []
        for j in range(4):
            pt = _intersect_with_blank_edge(gen_edge, j)
            if pt is not None:
                dots_by_outline[i].append(_beam_dot(pt))

    if not any(dots_by_outline.values()):
        return []

    # ------------------------------------------------------------------
    # Step 2: walk outline edges, track inside/outside, pair entry/exit
    # ------------------------------------------------------------------
    inside = beam.contains_point(outline.lines[0].start)
    current_entry = BeamOutlineIntersectionData() if inside else None
    crossings_as_dots = [current_entry] if inside else []

    for i in range(n_outline):
        hit_dots = dots_by_outline.get(i, [])

        if len(hit_dots) == 0 and inside:
            # entire edge lies within the beam blank — record the corner
            current_entry.internal_dots.append(_beam_dot(outline[i + 1]))

        elif len(hit_dots) == 1:
            # edge crosses beam boundary once: either entering or exiting
            inside = not inside
            if inside:
                # entered the beam blank
                current_entry = BeamOutlineIntersectionData(
                    start_dot=hit_dots[0],
                    internal_dots=[_beam_dot(outline[i + 1])],
                )
                crossings_as_dots.append(current_entry)
            else:
                # exited the beam blank
                current_entry.end_dot = hit_dots[0]
                current_entry = None

        elif len(hit_dots) == 2:
            # outline edge traverses the full beam width in one step (SINGLE)
            crossings_as_dots.append(BeamOutlineIntersectionData(
                start_dot=min(hit_dots),
                end_dot=max(hit_dots),
            ))
            current_entry = None

    # ------------------------------------------------------------------
    # Wrap-around: outline started inside the beam.
    # The first crossing has no start_dot; find it from the last crossing.
    # ------------------------------------------------------------------
    if not crossings_as_dots:
        return []

    if crossings_as_dots[0].start_dot is None:
        if not crossings_as_dots or len(crossings_as_dots) < 2:
            return []
        # The last entry (crossings_as_dots[-1]) is the wrap-around entry that
        # never exited because the outline ended inside where it started.
        end_int = crossings_as_dots.pop()
        crossings_as_dots[0].start_dot = end_int.start_dot
        crossings_as_dots[0].internal_dots = end_int.internal_dots + crossings_as_dots[0].internal_dots

    return crossings_as_dots


# =============================================================================
# Public functions
# =============================================================================


def extend_beam_to_closest_element_generators(beam, element_generators, only_start=False, only_end=False):
    # type: (Beam2D, list[ElementGenerator], bool, bool) -> None
    """Extend *beam* in-place so its ends reach the nearest generator outlines.

    Parameters
    ----------
    beam : :class:`~timber_design.populators.Beam2D`
    element_generators : list[:class:`~timber_design.populators.ElementGenerator`]
    only_start : bool
        Only extend toward the beam start (negative dot direction).
    only_end : bool
        Only extend toward the beam end (positive dot direction).
    """
    if only_end and only_start:
        raise ValueError("Beam is overconstrained; only one of `only_start` and `only_end` can be True: {}".format(beam))

    intersections = []
    for eg in element_generators:
        if eg.outline is not None:
            intersections.extend(
                find_beam_outline_crossings(beam, eg.outline, limit_to_segments=False)
            )

    if not intersections:
        return

    def _avg(x):
        return x.average_dot if x.average_dot is not None else 0.0

    intersections.sort(key=_avg)

    def get_bottom_dot(intersections):
        """Dot of the crossing closest to 0 from the negative side."""
        neg = [x for x in intersections if _avg(x) <= 0]
        if not neg:
            return None
        bottom = max(neg, key=_avg)  # closest to 0 from below
        return min(bottom.all_dots)  # outermost point of that crossing

    def get_top_dot(beam, intersections):
        """Dot of the crossing closest to beam.length from the positive side."""
        pos = [x for x in intersections if _avg(x) >= beam.length]
        if not pos:
            return None
        top = min(pos, key=_avg)  # closest to beam.length from above
        return max(top.all_dots)  # outermost point of that crossing

    bottom_dot = get_bottom_dot(intersections) if not only_end else None
    top_dot = get_top_dot(beam, intersections) if not only_start else None

    if bottom_dot is not None:
        beam.transform(Translation.from_vector(beam.frame.xaxis * bottom_dot))

    start = bottom_dot if bottom_dot is not None else 0
    end = top_dot if top_dot is not None else beam.length
    new_length = end - start
    if new_length <= 0:
        raise ValueError(
            "extend_beam_to_closest_element_generators produced degenerate length {} "
            "(bottom_dot={}, top_dot={}, original_length={}) on beam '{}'".format(
                new_length, bottom_dot, top_dot, beam.length, beam.attributes.get("name", "?")
            )
        )
    beam.length = new_length
