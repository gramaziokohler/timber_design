from __future__ import annotations

from itertools import combinations
from itertools import product
from typing import TYPE_CHECKING
from typing import Optional

if TYPE_CHECKING:
    from compas.geometry import Polyline  # noqa: F401

from compas.geometry import Point
from compas.geometry import Translation
from compas.geometry import Vector
from compas.geometry import distance_point_line
from compas.geometry import dot_vectors
from compas.geometry import intersection_line_segment
from compas.geometry import intersection_segment_segment
from compas_timber.connections import Cluster
from compas_timber.connections.solver import JointTopology
from compas_timber.utils import StrEnum


def _average_point(points: list[Point]) -> Point:
    n = len(points)
    return Point(
        sum(p.x for p in points) / n,
        sum(p.y for p in points) / n,
        sum(p.z for p in points) / n,
    )


def _dot_range(beam, points: list[Point]) -> Optional[tuple[float, float]]:
    """Project *points* onto *beam*'s centreline and return ``(min_dot, max_dot)``."""
    if not points:
        return None
    dots = [dot_vectors(Vector.from_start_end(beam.frame.point, pt), beam.frame.xaxis) for pt in points]
    return (min(dots), max(dots))


def _beam_dot(beam, pt: Point) -> float:
    """Project *pt* onto *beam*'s centreline axis."""
    return dot_vectors(Vector.from_start_end(beam.frame.point, pt), beam.frame.xaxis)


def _merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Merge overlapping 1-D intervals (sorted by start).  Non-overlapping intervals stay separate."""
    if not intervals:
        return []
    sorted_ivs = sorted(intervals)
    merged = [sorted_ivs[0]]
    for start, end in sorted_ivs[1:]:
        if start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def aabb_overlap(a, b, tolerance: float = 0.0) -> bool:
    """Return ``True`` if the axis-aligned bounding boxes of two blanks overlap in XY.

    Parameters
    ----------
    a, b : :class:`~timber_design.populators.Beam2D` or :class:`~timber_design.populators.populator_agents.LayerAgent`
        Objects with an ``aabb`` attribute exposing ``xmin``, ``xmax``, ``ymin``, ``ymax``.
    tolerance : float
        Each AABB is expanded by this amount in every direction before the
        overlap test.  Use a small positive value so that blanks that merely
        *touch* are still considered overlapping.
    """
    if not (a.aabb and b.aabb):
        return False
    return (
        a.aabb.xmax + tolerance >= b.aabb.xmin - tolerance
        and b.aabb.xmax + tolerance >= a.aabb.xmin - tolerance
        and a.aabb.ymax + tolerance >= b.aabb.ymin - tolerance
        and b.aabb.ymax + tolerance >= a.aabb.ymin - tolerance
    )


# blank_outline.lines indices:
# 0  bl→br   edge_a direction   (long face, -yaxis side)
# 1  br→tr   end cap            (beam end)
# 2  tr→tl   edge_b reversed    (long face, +yaxis side)
# 3  tl→bl   start cap          (beam start)
_LONG_FACE_INDICES = frozenset({0, 2})


class BeamEnd(StrEnum):
    START = "start"
    END = "end"


class Beam2DPolylineIntersectionResult:
    """Dot-position data for one entry/exit crossing of a polyline through a beam blank.

    Parameters
    ----------
    start_dot : float or None
        Position along the beam centreline where the polyline enters the blank.
        ``None`` when the polyline began inside the beam (wrap-around case).
    end_dot : float or None
        Position along the beam centreline where the polyline exits the blank.
        ``None`` when the polyline ended inside the beam (wrap-around case).
    internal_dots : list[float], optional
        Positions of polyline corners that lie inside the beam blank between
        ``start_dot`` and ``end_dot``.

    Attributes
    ----------
    start_dot : float or None
    end_dot : float or None
    internal_dots : list[float]
    all_dots : list[float]
        All valid dot positions combined.
    average_dot : float or None
        Mean of :attr:`all_dots`, or ``None`` when no dots are available.
    """

    def __init__(
        self,
        start_dot: Optional[float] = None,
        end_dot: Optional[float] = None,
        internal_dots: Optional[list[float]] = None,
    ) -> None:
        self.start_dot = start_dot
        self.end_dot = end_dot
        self.internal_dots = internal_dots or []

    def __repr__(self) -> str:
        return "Beam2DPolylineIntersectionResult(start_dot={}, end_dot={}, internal_dots={})".format(self.start_dot, self.end_dot, self.internal_dots)

    @property
    def all_dots(self) -> list[float]:
        """All dot positions: start, end (if not None), plus internal corners."""
        return [d for d in [self.start_dot, self.end_dot] if d is not None] + self.internal_dots

    @property
    def average_dot(self) -> Optional[float]:
        """Mean of all dot positions, or ``None`` if no dots are available."""
        dots = self.all_dots
        return sum(dots) / len(dots) if dots else None


class Beam2DSolverResult:
    """Results of 2D blank-outline topology analysis between two beams.

    Parameters
    ----------
    beam_a : :class:`~timber_design.populators.Beam2D`
        The first beam.  For ``TOPO_T``, this is always the *end* beam.
    beam_b : :class:`~timber_design.populators.Beam2D`
        The second beam.  For ``TOPO_T``, this is always the *body* beam.
    distance : float
        Separation between the blanks (0.0 when they overlap).
    topology : int
        One of the ``TOPO_*`` constants from :class:`~compas_timber.connections.JointTopology`.
    location : :class:`~compas.geometry.Point`
        Approximate location of the intersection.
    dot_range_on_a : tuple[float, float] or None
        The ``(min, max)`` dot-product range of the intersection projected onto
        *beam_a*'s centreline.  Used by :class:`Cluster2DFinder` for Y/K detection.
    dot_range_on_b : tuple[float, float] or None
        The ``(min, max)`` dot-product range of the intersection projected onto
        *beam_b*'s centreline.

    Attributes
    ----------
    beam_a, beam_b : :class:`~timber_design.populators.Beam2D`
    distance : float
    topology : int
    location : :class:`~compas.geometry.Point`
    dot_range_on_a : tuple[float, float] or None
    dot_range_on_b : tuple[float, float] or None
    """

    def __init__(
        self,
        beam_a,
        beam_b,
        distance: float,
        topology: int,
        location: Point,
        dot_range_on_a: Optional[tuple[float, float]] = None,
        dot_range_on_b: Optional[tuple[float, float]] = None,
    ) -> None:
        self.beam_a = beam_a
        self.beam_b = beam_b
        self.distance = distance
        self.topology = topology
        self.location = location
        self.dot_range_on_a = dot_range_on_a
        self.dot_range_on_b = dot_range_on_b

    @property
    def elements(self) -> tuple:
        """The two beams as a tuple, so this result can serve as a joint in a :class:`~compas_timber.connections.Cluster`."""
        return (self.beam_a, self.beam_b)

    def __repr__(self) -> str:
        return "Beam2DSolverResult(topology={}, beam_a={!r}, beam_b={!r})".format(JointTopology.get_name(self.topology), self.beam_a, self.beam_b)


class ConnectionSolver2D:
    """2D blank-outline-aware solver for beam adjacency, topology detection, and beam-polyline intersection.

    Mirrors the interface of :class:`~compas_timber.connections.ConnectionSolver`
    but uses blank-outline containment and crossing tests on
    :class:`~timber_design.populators.Beam2D` objects instead of 3D centerline distance.

    Parameters
    ----------
    max_distance : float
        Maximum gap between two AABBs still considered overlapping.  Defaults
        to ``1.0`` so that blanks that merely *touch* (or drift slightly apart
        due to floating-point error) are still paired.  Pass ``0.0`` for strict
        overlap only.

    Attributes
    ----------
    max_distance : float
    """

    def __init__(self, max_distance: float = 0.0) -> None:
        self.max_distance = max_distance

    # ------------------------------------------------------------------
    # Pair finding
    # ------------------------------------------------------------------

    def find_intersecting_pairs(self, items):
        """Yield ``(beam_a, beam_b)`` pairs whose blank AABBs overlap.

        Parameters
        ----------
        beams : list[:class:`~timber_design.populators.Beam2D`]

        Yields
        ------
        tuple[:class:`~timber_design.populators.Beam2D`, :class:`~timber_design.populators.Beam2D`]
        """
        for item_a, item_b in combinations(items, 2):
            if aabb_overlap(item_a, item_b, tolerance=self.max_distance):
                yield item_a, item_b

    # ------------------------------------------------------------------
    # Topology classification
    # ------------------------------------------------------------------

    def find_topology(self, beam_a, beam_b) -> Optional[Beam2DSolverResult]:
        """Return the 2D blank-overlap topology between *beam_a* and *beam_b*.

        Detection order:

        1. **Face-to-face** — parallel beams on opposite sides of a shared
           long edge (``TOPO_FACE_FACE``).
        2. **Corner containment** — checks which end (start or end) of each
           beam is inside the other's blank via
           :meth:`~timber_design.populators.Beam2D.contains_point`.
        3. **Outline-outline intersections** — collects all segment crossings;
           end-cap crossings (indices 1 and 3) refine end detection for beams
           that only touch at their caps without corner overlap.
        4. **Topology assignment** — ``TOPO_L`` (both ends), ``TOPO_T`` (one
           end), or ``TOPO_X`` (no end involved) from the combined evidence.

        Parameters
        ----------
        beam_a : :class:`~timber_design.populators.Beam2D`
        beam_b : :class:`~timber_design.populators.Beam2D`

        Returns
        -------
        :class:`Beam2DSolverResult` or None
            ``None`` when the blanks do not overlap.
        """
        if not all([b.is_beam for b in [beam_a, beam_b]]):
            return None
        if not aabb_overlap(beam_a, beam_b, tolerance=self.max_distance):
            return None

        # FACE_FACE: parallel beams on opposite sides of a shared long edge
        if abs(abs(dot_vectors(beam_a.frame.xaxis, beam_b.frame.xaxis)) - 1.0) < 1e-6:
            perp_vec = beam_a.frame.yaxis
            for ea, eb in product([beam_a.edge_a, beam_a.edge_b], [beam_b.edge_a, beam_b.edge_b]):
                dist = distance_point_line(eb.start, ea)
                if dist <= self.max_distance:
                    dot_a = dot_vectors(Vector.from_start_end(ea.start, beam_a.frame.point), perp_vec)
                    dot_b = dot_vectors(Vector.from_start_end(ea.start, beam_b.frame.point), perp_vec)
                    if dot_a * dot_b < 0:
                        dot_pts = [ea.start, ea.end, eb.start, eb.end]
                        return Beam2DSolverResult(
                            beam_a,
                            beam_b,
                            dist,
                            JointTopology.TOPO_FACE_FACE,
                            _average_point(dot_pts),
                            _dot_range(beam_a, dot_pts),
                            _dot_range(beam_b, dot_pts),
                        )

        # Corner containment: which end of each beam is at the joint?
        b_contains_a_start = any(beam_b.contains_point(p) for p in (beam_a.edge_a.start, beam_a.edge_b.start))
        b_contains_a_end = any(beam_b.contains_point(p) for p in (beam_a.edge_a.end, beam_a.edge_b.end))
        a_contains_b_start = any(beam_a.contains_point(p) for p in (beam_b.edge_a.start, beam_b.edge_b.start))
        a_contains_b_end = any(beam_a.contains_point(p) for p in (beam_b.edge_a.end, beam_b.edge_b.end))

        if b_contains_a_start and b_contains_a_end:
            raise ValueError("Both ends of a beam are inside another: {!r} / {!r}".format(beam_a, beam_b))
        if a_contains_b_start and a_contains_b_end:
            raise ValueError("Both ends of a beam are inside another: {!r} / {!r}".format(beam_b, beam_a))
        beam_a_end: Optional[BeamEnd] = None
        if b_contains_a_start:
            beam_a_end = BeamEnd.START
        elif b_contains_a_end:
            beam_a_end = BeamEnd.END

        beam_b_end: Optional[BeamEnd] = None
        if a_contains_b_start:
            beam_b_end = BeamEnd.START
        elif a_contains_b_end:
            beam_b_end = BeamEnd.END

        # Outline-outline intersections; end-segment crossings fill in beam_a_end/beam_b_end
        # when corner containment missed the touching-at-end case.
        points: list[Point] = []
        for i, seg_a in enumerate(beam_a.blank_outline.lines):
            for j, seg_b in enumerate(beam_b.blank_outline.lines):
                result = intersection_segment_segment(seg_a, seg_b)
                if result[0]:
                    points.append(Point(*result[0]))
                    if beam_a_end is None:
                        if i == 1:
                            beam_a_end = BeamEnd.END
                        elif i == 3:
                            beam_a_end = BeamEnd.START
                    if beam_b_end is None:
                        if j == 1:
                            beam_b_end = BeamEnd.END
                        elif j == 3:
                            beam_b_end = BeamEnd.START

        if not points:
            return None

        # Build dot ranges; append the beam endpoint when that end is at the joint
        a_dots = [_beam_dot(beam_a, p) for p in points]
        if beam_a_end == BeamEnd.START:
            a_dots.append(0.0)
        elif beam_a_end == BeamEnd.END:
            a_dots.append(beam_a.length)
        beam_a_dots = (min(a_dots), max(a_dots))

        b_dots = [_beam_dot(beam_b, p) for p in points]
        if beam_b_end == BeamEnd.START:
            b_dots.append(0.0)
        elif beam_b_end == BeamEnd.END:
            b_dots.append(beam_b.length)
        beam_b_dots = (min(b_dots), max(b_dots))

        loc = _average_point(points)

        if beam_a_end and beam_b_end:
            return Beam2DSolverResult(beam_a, beam_b, 0.0, JointTopology.TOPO_L, loc, beam_a_dots, beam_b_dots)
        if beam_a_end:
            return Beam2DSolverResult(beam_a, beam_b, 0.0, JointTopology.TOPO_T, loc, beam_a_dots, beam_b_dots)
        if beam_b_end:
            return Beam2DSolverResult(beam_b, beam_a, 0.0, JointTopology.TOPO_T, loc, beam_b_dots, beam_a_dots)
        return Beam2DSolverResult(beam_a, beam_b, 0.0, JointTopology.TOPO_X, loc, beam_a_dots, beam_b_dots)

    # ------------------------------------------------------------------
    # Beam–polyline intersection
    # ------------------------------------------------------------------

    @staticmethod
    def intersection_beam2d_polyline(
        beam,
        outline: Polyline,
        limit_to_segments: bool = True,
    ) -> list[Beam2DPolylineIntersectionResult]:
        """Walk every edge of *outline* and detect how it enters and exits *beam*'s blank.

        Parameters
        ----------
        beam : :class:`~timber_design.populators.Beam2D`
        outline : :class:`~compas.geometry.Polyline`
        limit_to_segments : bool
            When ``False``, the long blank edges are treated as infinite lines
            so that intersections outside the beam's current extents are found.
            Used by :meth:`extend_beam_to_polylines` for boundary projection.

        Returns
        -------
        list[:class:`Beam2DPolylineIntersectionResult`]
        """
        blank_lines = beam.blank_outline.lines
        n_outline = len(outline) - 1

        def _beam_dot(pt: Point) -> float:
            return dot_vectors(Vector.from_start_end(beam.frame.point, pt), beam.frame.xaxis)

        def _intersect_with_blank_edge(outline_edge, blank_idx: int) -> Optional[Point]:
            blank_edge = blank_lines[blank_idx]
            if not limit_to_segments and blank_idx in _LONG_FACE_INDICES:
                result = intersection_line_segment(blank_edge, outline_edge)
            else:
                result = intersection_segment_segment(outline_edge, blank_edge)
            pt = result[0] if result else None
            return Point(*pt) if pt else None

        # Collect intersection dots per outline segment.
        # Filter intersections at each edge's START — they were already recorded
        # as the END of the previous edge, preventing double-counting at outline
        # corners that lie exactly on a blank boundary.
        # Deduplicate within each edge to handle blank corners detected by two
        # adjacent blank edges simultaneously.
        _endpoint_tol = 1e-6
        dots_by_outline: dict[int, list[float]] = {}
        for i, outline_edge in enumerate(outline.lines):
            raw_pts: list[Point] = []
            for j in range(4):
                pt = _intersect_with_blank_edge(outline_edge, j)
                if pt is None:
                    continue
                if outline_edge.start.distance_to_point(pt) < _endpoint_tol:
                    continue
                raw_pts.append(pt)
            unique_pts: list[Point] = []
            for pt in raw_pts:
                if not any(p.distance_to_point(pt) < _endpoint_tol for p in unique_pts):
                    unique_pts.append(pt)
            dots_by_outline[i] = [_beam_dot(pt) for pt in unique_pts]

        if not any(dots_by_outline.values()):
            return []

        inside = beam.contains_point(outline.lines[0].start)
        current_entry: Optional[Beam2DPolylineIntersectionResult] = Beam2DPolylineIntersectionResult() if inside else None
        crossings: list[Beam2DPolylineIntersectionResult] = [current_entry] if inside else []

        for i in range(n_outline):
            hit_dots = dots_by_outline.get(i, [])

            if len(hit_dots) == 0:
                if inside:
                    if current_entry is None:
                        current_entry = Beam2DPolylineIntersectionResult()
                        crossings.append(current_entry)
                    current_entry.internal_dots.append(_beam_dot(outline[i + 1]))

            elif len(hit_dots) == 1:
                inside = not inside
                if inside:
                    current_entry = Beam2DPolylineIntersectionResult(
                        start_dot=hit_dots[0],
                        internal_dots=[_beam_dot(outline[i + 1])],
                    )
                    crossings.append(current_entry)
                else:
                    if current_entry is None:
                        current_entry = Beam2DPolylineIntersectionResult()
                        crossings.append(current_entry)
                    current_entry.end_dot = hit_dots[0]
                    current_entry = None

            elif len(hit_dots) == 2:
                crossings.append(
                    Beam2DPolylineIntersectionResult(
                        start_dot=min(hit_dots),
                        end_dot=max(hit_dots),
                    )
                )
                current_entry = None

        if not crossings:
            return []

        # Wrap-around: outline started inside the beam — fix up the first entry's start_dot.
        if crossings[0].start_dot is None:
            if len(crossings) < 2:
                return []
            tail = crossings.pop()
            crossings[0].start_dot = tail.start_dot
            crossings[0].internal_dots = tail.internal_dots + crossings[0].internal_dots

        return [c for c in crossings if c.all_dots]

    # ------------------------------------------------------------------
    # Beam extension
    # ------------------------------------------------------------------

    @staticmethod
    def extend_beam_to_polylines(
        beam,
        outlines: list[Optional[Polyline]],
        only_start: bool = False,
        only_end: bool = False,
    ) -> None:
        """Extend *beam* in-place so its ends reach the nearest outlines.

        Parameters
        ----------
        beam : :class:`~timber_design.populators.Beam2D`
        outlines : list[:class:`~compas.geometry.Polyline` or None]
            Boundary outlines to extend toward.  ``None`` entries are skipped.
        only_start : bool
            Only extend toward the beam start (negative dot direction).
        only_end : bool
            Only extend toward the beam end (positive dot direction).
        """
        if only_end and only_start:
            raise ValueError("Beam is overconstrained; only one of `only_start` and `only_end` can be True: {}".format(beam))

        intersections: list[Beam2DPolylineIntersectionResult] = []
        for outline in outlines:
            if outline is not None:
                intersections.extend(ConnectionSolver2D.intersection_beam2d_polyline(beam, outline, limit_to_segments=False))

        if not intersections:
            return

        def _avg(x: Beam2DPolylineIntersectionResult) -> float:
            return x.average_dot if x.average_dot is not None else 0.0

        intersections.sort(key=_avg)

        def _get_bottom_dot(intersections: list[Beam2DPolylineIntersectionResult]) -> Optional[float]:
            neg = [x for x in intersections if x.all_dots and _avg(x) <= 0]
            if not neg:
                return None
            return min(max(neg, key=_avg).all_dots)

        def _get_top_dot(beam, intersections: list[Beam2DPolylineIntersectionResult]) -> Optional[float]:
            pos = [x for x in intersections if x.all_dots and _avg(x) >= beam.length]
            if not pos:
                return None
            return max(min(pos, key=_avg).all_dots)

        bottom_dot = _get_bottom_dot(intersections) if not only_end else None
        top_dot = _get_top_dot(beam, intersections) if not only_start else None

        if bottom_dot is not None:
            beam.transform(Translation.from_vector(beam.frame.xaxis * bottom_dot))

        start = bottom_dot if bottom_dot is not None else 0
        end = top_dot if top_dot is not None else beam.length
        new_length = end - start
        if new_length <= 0:
            raise ValueError(
                "extend_beam_to_polylines produced degenerate length {} (bottom_dot={}, top_dot={}, original_length={}) on beam '{}'".format(
                    new_length, bottom_dot, top_dot, beam.length, beam.attributes.get("name", "?")
                )
            )
        beam.length = new_length

    # ------------------------------------------------------------------
    # Joint candidates and cluster finding
    # ------------------------------------------------------------------

    def find_joint_candidates(self, beams) -> list[Beam2DSolverResult]:
        """Return pairwise topology results for all overlapping beam pairs.

        Parameters
        ----------
        beams : list[:class:`~timber_design.populators.Beam2D`]

        Returns
        -------
        list[:class:`Beam2DSolverResult`]
        """
        results = []
        for beam_a, beam_b in self.find_intersecting_pairs(beams):
            result = self.find_topology(beam_a, beam_b)
            if result is not None:
                results.append(result)
        return results

    def find_joint_clusters(self, beams) -> list["Cluster2D"]:
        """Find pairwise results and cluster multi-beam corners.

        Convenience wrapper that calls :meth:`find_joint_candidates` then
        :meth:`Cluster2DFinder.find_clusters`.

        Parameters
        ----------
        beams : list[:class:`~timber_design.populators.Beam2D`]

        Returns
        -------
        list[:class:`Cluster2D`]
        """
        results = self.find_joint_candidates(beams)
        return Cluster2DFinder(endpoint_tolerance=self.max_distance).find_clusters(results)


class Cluster2DFinder:
    """Finds multi-beam corner clusters from pairwise :class:`Beam2DSolverResult`s.

    Two results are **adjacent** if they share a beam and their dot-product
    ranges on that shared beam overlap.  Connected components of this adjacency
    graph are returned as :class:`Cluster2D` objects.

    Parameters
    ----------
    endpoint_tolerance : float
        Dot-product distance from a beam endpoint within which an intersection
        is considered "at an endpoint" for Y/K classification.  Defaults to
        ``0.0`` (matches the default ``max_distance`` of
        :class:`ConnectionSolver2D`).

    Attributes
    ----------
    endpoint_tolerance : float
    """

    def __init__(self, endpoint_tolerance: float = 0.0) -> None:
        self.endpoint_tolerance = endpoint_tolerance

    def find_clusters(self, results: list[Beam2DSolverResult]) -> list["Cluster2D"]:
        """Find corner clusters in *results*.

        Parameters
        ----------
        results : list[:class:`Beam2DSolverResult`]

        Returns
        -------
        list[:class:`Cluster2D`]
        """
        n = len(results)
        if n == 0:
            return []

        adjacency: dict[int, set[int]] = {i: set() for i in range(n)}
        for i in range(n):
            for j in range(i + 1, n):
                shared = self._shared_beam(results[i], results[j])
                if shared is None:
                    continue
                ri = self._dot_range_for_beam(results[i], shared)
                rj = self._dot_range_for_beam(results[j], shared)
                if ri is None or rj is None:
                    continue
                if self._ranges_overlap(ri, rj):
                    adjacency[i].add(j)
                    adjacency[j].add(i)

        visited: set[int] = set()
        clusters: list[Cluster2D] = []
        for start in range(n):
            if start in visited:
                continue
            component: list[int] = []
            stack = [start]
            while stack:
                node = stack.pop()
                if node in visited:
                    continue
                visited.add(node)
                component.append(node)
                stack.extend(adjacency[node] - visited)
            clusters.append(
                Cluster2D(
                    [results[i] for i in component],
                    endpoint_tolerance=self.endpoint_tolerance,
                )
            )

        return clusters

    @staticmethod
    def _compute_topology(results: list[Beam2DSolverResult], endpoint_tolerance: float = 0.0) -> int:
        """Determine cluster topology using dot-range endpoint analysis.

        For a single result, returns that result's topology directly.
        For multi-result clusters, returns :attr:`~compas_timber.connections.JointTopology.TOPO_Y`
        if every intersection range touches a beam endpoint (within *endpoint_tolerance*),
        or :attr:`~compas_timber.connections.JointTopology.TOPO_K` otherwise.
        """
        if len(results) == 1:
            return results[0].topology
        tol = endpoint_tolerance
        beam_ranges: dict[int, list[tuple[float, float]]] = {}
        beam_map: dict[int, object] = {}
        for result in results:
            for beam, dot_range in (
                (result.beam_a, result.dot_range_on_a),
                (result.beam_b, result.dot_range_on_b),
            ):
                if dot_range is None:
                    continue
                bid = id(beam)
                beam_map[bid] = beam
                beam_ranges.setdefault(bid, []).append(dot_range)
        for bid, ranges in beam_ranges.items():
            beam = beam_map[bid]
            for d_min, d_max in _merge_intervals(ranges):
                if not (d_min <= tol or d_max >= beam.length - tol):
                    return JointTopology.TOPO_K
        return JointTopology.TOPO_Y

    @staticmethod
    def _shared_beam(r1: Beam2DSolverResult, r2: Beam2DSolverResult):
        """Return the beam shared by both results, or ``None``."""
        for b in (r1.beam_a, r1.beam_b):
            if b is r2.beam_a or b is r2.beam_b:
                return b
        return None

    @staticmethod
    def _dot_range_for_beam(result: Beam2DSolverResult, beam) -> Optional[tuple[float, float]]:
        """Return the dot-range stored in *result* for the given *beam*."""
        if result.beam_a is beam:
            return result.dot_range_on_a
        if result.beam_b is beam:
            return result.dot_range_on_b
        return None

    @staticmethod
    def _ranges_overlap(r1: tuple[float, float], r2: tuple[float, float]) -> bool:
        """Return ``True`` if the two 1-D intervals overlap (inclusive)."""
        return r1[0] <= r2[1] and r2[0] <= r1[1]


class Cluster2D(Cluster):
    """A :class:`~compas_timber.connections.Cluster` whose topology is determined
    by dot-range endpoint analysis on the constituent :class:`Beam2DSolverResult`s.

    Unlike the base :class:`~compas_timber.connections.Cluster`, which derives
    topology purely from pairwise joint types, this subclass uses
    :meth:`Cluster2DFinder._compute_topology` to distinguish Y from K based on
    whether each intersection range touches a beam endpoint.

    Parameters
    ----------
    results : list[:class:`Beam2DSolverResult`]
        Pairwise results forming this cluster.
    endpoint_tolerance : float
        Dot-product distance from a beam endpoint considered "at endpoint".
    """

    def __init__(self, results: list[Beam2DSolverResult], endpoint_tolerance: float = 0.0) -> None:
        super().__init__(results)
        self._topology = Cluster2DFinder._compute_topology(results, endpoint_tolerance)

    def __repr__(self) -> str:
        return "Cluster2D(topology={}, n_joints={}, n_elements={})".format(
            JointTopology.get_name(self._topology),
            len(self.joints),
            len(self.elements),
        )

    @property
    def topology(self) -> int:
        return self._topology

    @property
    def location(self) -> Optional[Point]:
        """Average location of all constituent results."""
        pts = [r.location for r in self.joints if r.location is not None]
        return _average_point(pts) if pts else None
