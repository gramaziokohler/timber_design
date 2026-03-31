from __future__ import annotations

from poplib import CR
from tkinter import NO
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
# New core: outline-walk crossing detection
# =============================================================================

# beam.blank_outline.lines indices
# 0  bl→br   edge_a direction   (long face, -yaxis side)
# 1  br→tr   end cap            (beam end)
# 2  tr→tl   edge_b reversed    (long face, +yaxis side)
# 3  tl→bl   start cap          (beam start)
_LONG_FACE_INDICES = frozenset({0, 2})

class BeamOutlineIntersectionData:
    def __init__(self, start_dot=None, end_dot=None, internal_dots=None):
        self.start_dot = start_dot
        self.end_dot = end_dot
        self.internal_dots = internal_dots or []

    @property
    def all_dots(self):
        return [d for d in [self.start_dot, self.end_dot] if d is not None] + self.internal_dots

    @property
    def average_dot(self):
        dots = self.all_dots
        return sum(dots) / len(dots) if all(dots) else None


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
    skip_laps : bool

    Returns
    -------
    list[:class:`BeamOutlineIntersectionLocations`]
    """
    blank_lines = beam.blank_outline.lines  # 4 edges: edge_a(0), end-cap(1), edge_b-rev(2), start-cap(3)
    n_outline = len(outline)-1

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
                all_hits.append((i, _beam_dot(pt)))

    # Group long_hits by outline edge index
    dots_by_outline = {}
    for i, pt in all_hits:
        dots_by_outline.setdefault(i, []).append((pt))

    # ------------------------------------------------------------------
    # Step 2: walk outline edges, track inside/outside, pair entry/exit
    # ------------------------------------------------------------------



    inside = beam.contains_point(outline.lines[0].start)
    current_entry = BeamOutlineIntersectionData() if inside else None
    crossings_as_dots = [current_entry] if inside else [] 


    for i in range(n_outline):
        hit_dots = dots_by_outline.get(i, [])

        if len(hit_dots) == 0 and inside:
            # entire edge within beam outline
            current_entry.internal_dots.append(_beam_dot(outline[i+1]))

        elif len(hit_dots) == 1:
            # edge crosses beam boundary once: either entering or exiting
            inside = not inside
            if inside:
                # edge crossed INTO the beam outline
                current_entry=BeamOutlineIntersectionData(start_dot = hit_dots[0], internal_dots=[_beam_dot(outline[i+1])])
                crossings_as_dots.append(current_entry)
            else:
                # edge crossed OUT OF the beam outline
                current_entry.end_dot = hit_dots[0]
                current_entry = None

        if len(hit_dots) == 2:
            # Outline edge traverses the full beam width in one step
            crossings_as_dots.append((BeamOutlineIntersectionData(*hit_dots)))
            current_entry = None

    if crossings_as_dots[0].start_dot is None:
        if crossings_as_dots[-1].end_dot is not None:
            raise ValueError("Invalid crossing sequence: outline starts inside but ends outside the beam blank")
        end_int = crossings_as_dots.pop()
        crossings_as_dots[0].start_dot = end_int.start_dot
        crossings_as_dots[0].internal_dots.extend(end_int.internal_dots)

    return crossings_as_dots


# =============================================================================
# Public intersection class
# =============================================================================


def trim_generator_elements_with_genenrator(generator_a, generator_b, skip_notches=False, skip_laps=False):
    # type: (ElementGenerator, ElementGenerator, bool, bool) -> tuple[list, list]
    """Split *generator_a*'s elements at every intersection with *generator_b*'s outline.
    Parameters
    ----------
    generator_a : :class:`~timber_design.populators.ElementGenerator`
    generator_b : :class:`~timber_design.populators.ElementGenerator`
    skip_notches : bool
    skip_laps : bool
    Returns
    -------
    new_elements : list[:class:`~timber_design.populators.elements.Element`]
    rules_to_cull : list
    """
    new_elements = []
    rules_to_cull = []
    for element in generator_a.elements:
        if element.is_beam:
            new_elements.extend(generator_b.trim_beam(element))
    return new_elements


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
