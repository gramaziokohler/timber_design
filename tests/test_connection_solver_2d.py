"""Tests for ConnectionSolver2D.

Uses real Beam2D objects (no mocks) and is designed to run inside Rhino's
Python environment as well as a standard pytest runner.

Coordinate convention
---------------------
All beams lie flat in the XY plane with ``z_vector=(0,0,1)`` so that:
  * ``frame.yaxis`` points in  **-X** for a beam along Y, and in **-Y** for a
    beam along X.
  * ``edge_a`` is the blank edge offset in the **-yaxis** direction (−width/2).
  * ``edge_b`` is the blank edge offset in the **+yaxis** direction (+width/2).

For a horizontal beam from (x0,0) to (x1,0) with width *w*:
  blank spans x=[x0, x1],  y=[−w/2, +w/2]

For a vertical beam from (0,y0) to (0,y1) with width *w*:
  blank spans x=[−w/2, +w/2],  y=[y0, y1]
"""

from compas.geometry import Line
from compas.geometry import Point
from compas.geometry import Vector
from compas_timber.connections.solver import JointTopology

from timber_design.populators.beam2d import AABB2D
from timber_design.populators.beam2d import Beam2D
from timber_design.populators.connection_solver_2d import ConnectionSolver2D


# =============================================================================
# Helpers
# =============================================================================


def make_beam(x0, y0, x1, y1, width=0.5, height=0.1):
    """Create a Beam2D from flat 2D start/end coordinates."""
    return Beam2D.from_centerline(
        Line(Point(x0, y0, 0.0), Point(x1, y1, 0.0)),
        width=width,
        height=height,
        z_vector=Vector(0.0, 0.0, 1.0),
    )


class SimpleAgent(object):
    """Minimal stand-in for PopulatorAgent with an ``elements`` list and ``aabb``."""

    def __init__(self, beams):
        self.elements = list(beams)

    @property
    def aabb(self):
        pts = []
        for e in self.elements:
            if hasattr(e, "aabb") and e.aabb:
                pts.extend(e.aabb.points)
        if not pts:
            return None
        return AABB2D.from_points(pts)


# =============================================================================
# find_topology
# =============================================================================


class TestFindTopology:
    """Tests for ConnectionSolver2D.find_topology."""

    def test_no_overlap_returns_none(self):
        """Beams with clearly separated blanks produce no candidate."""
        solver = ConnectionSolver2D()
        beam_a = make_beam(0, 0, 2, 0)  # blank x=0..2,  y=±0.25
        beam_b = make_beam(5, 0, 7, 0)  # blank x=5..7,  y=±0.25  — far apart
        assert solver.find_topology(beam_a, beam_b) is None

    def test_parallel_offset_no_overlap_returns_none(self):
        """Parallel beams whose AABBs are beyond max_distance apart → no candidate.

        With solver max_distance=1.0, the AABB gap must exceed 2*1.0 = 2.0 to
        avoid even AABB overlap.  beam_b at y=3 gives a blank-edge gap of 2.5.
        """
        solver = ConnectionSolver2D()
        beam_a = make_beam(0, 0, 4, 0)  # blank y=±0.25
        beam_b = make_beam(0, 3, 4, 3)  # blank y=2.75..3.25 — AABB gap=2.5
        assert solver.find_topology(beam_a, beam_b) is None

    def test_topo_l_corner_joint(self):
        """Two beams meeting end-to-end at a right-angle corner → TOPO_L."""
        solver = ConnectionSolver2D()
        #  beam_a: horizontal,  blank x=0..2  y=±0.25
        #  beam_b: vertical,    blank x=±0.25 y=0..2 (shifted so its start
        #          aligns with beam_a's end)
        beam_a = make_beam(0, 0, 2, 0)
        beam_b = make_beam(2, 0, 2, 2)
        candidate = solver.find_topology(beam_a, beam_b)
        assert candidate is not None
        assert candidate.topology == JointTopology.TOPO_L

    def test_topo_t_end_beam_is_beam_a(self):
        """End beam (the one that butts in) must be ``beam_a`` in the result."""
        solver = ConnectionSolver2D()
        beam_face = make_beam(0, 0, 4, 0)  # long face beam — blank y=±0.25
        beam_end = make_beam(2, -2, 2, 0)  # short end beam terminating at y=0
        candidate = solver.find_topology(beam_face, beam_end)
        assert candidate is not None
        assert candidate.topology == JointTopology.TOPO_T
        assert candidate.beam_a is beam_end
        assert candidate.beam_b is beam_face

    def test_topo_t_argument_order_normalised(self):
        """Swapping argument order must not change which beam is ``beam_a``."""
        solver = ConnectionSolver2D()
        beam_face = make_beam(0, 0, 4, 0)
        beam_end = make_beam(2, -2, 2, 0)
        c1 = solver.find_topology(beam_end, beam_face)
        c2 = solver.find_topology(beam_face, beam_end)
        assert c1 is not None and c2 is not None
        assert c1.beam_a is beam_end
        assert c2.beam_a is beam_end

    def test_topo_x_crossing_beams(self):
        """Two beams whose centrelines cross in the middle, with no endpoint
        inside the other beam's blank → TOPO_X."""
        solver = ConnectionSolver2D()
        beam_a = make_beam(-1, 0, 3, 0)  # horizontal — blank y=±0.25
        beam_b = make_beam(1, -2, 1, 2)  # vertical   — blank x=±0.25
        # neither beam's corners fall inside the other
        candidate = solver.find_topology(beam_a, beam_b)
        assert candidate is not None
        assert candidate.topology == JointTopology.TOPO_X

    def test_candidate_carries_location(self):
        """Every returned candidate has a non-None ``location`` point."""
        solver = ConnectionSolver2D()
        cases = [
            (make_beam(0, 0, 2, 0), make_beam(2, 0, 2, 2)),  # L
            (make_beam(0, 0, 4, 0), make_beam(2, -2, 2, 0)),  # T
            (make_beam(-1, 0, 3, 0), make_beam(1, -2, 1, 2)),  # X
        ]
        for beam_a, beam_b in cases:
            candidate = solver.find_topology(beam_a, beam_b)
            assert candidate is not None, "Expected a candidate for overlapping beams"
            assert candidate.location is not None

    def test_candidate_elements_are_the_input_beams(self):
        """``element_a`` and ``element_b`` together must be the two input beams."""
        solver = ConnectionSolver2D()
        beam_a = make_beam(0, 0, 4, 0)
        beam_b = make_beam(2, -2, 2, 0)
        candidate = solver.find_topology(beam_a, beam_b)
        assert candidate is not None
        assert {id(candidate.beam_a), id(candidate.beam_b)} == {id(beam_a), id(beam_b)}

    def test_topo_t_end_trimmed_flush(self):
        """End beam trimmed so its start sits exactly at the face beam's outer edge
        — no blank overlap, but extended edge lines detect the T-joint."""
        solver = ConnectionSolver2D()
        beam_face = make_beam(0, 0, 4, 0, width=0.5)
        # beam_end trimmed so its tip is at y=0.25 (beam_face's outer blank edge)
        # — there is no blank overlap, only an adjacency
        beam_end = make_beam(2, 0.25, 2, 2, width=0.5)
        candidate = solver.find_topology(beam_face, beam_end)
        assert candidate is not None
        assert candidate.topology == JointTopology.TOPO_T
        assert candidate.beam_a is beam_end

    def test_topo_l_both_trimmed_flush(self):
        """Both beams trimmed to each other's outer face — extended edge lines
        detect the L-joint even though the blanks are adjacent, not overlapping."""
        solver = ConnectionSolver2D()
        # beam_a horizontal, blank y=±0.25.  beam_b vertical, blank x=±0.25.
        # Trim beam_a so it ends at x=1.75 (beam_b's left blank edge)
        # and beam_b so it starts at y=0.25 (beam_a's top blank edge).
        beam_a = make_beam(0, 0, 1.75, 0, width=0.5)  # ends just before beam_b's blank
        beam_b = make_beam(2, 0.25, 2, 3, width=0.5)  # starts just above beam_a's blank
        candidate = solver.find_topology(beam_a, beam_b)
        assert candidate is not None
        assert candidate.topology == JointTopology.TOPO_L

    def test_symmetric_pair_returns_same_topology(self):
        """Calling find_topology(a, b) and find_topology(b, a) must return the
        same topology value (element roles may differ for T, but topology is equal)."""
        solver = ConnectionSolver2D()
        pairs = [
            (make_beam(0, 0, 2, 0), make_beam(2, 0, 2, 2)),  # L
            (make_beam(0, 0, 4, 0), make_beam(2, -2, 2, 0)),  # T
            (make_beam(-1, 0, 3, 0), make_beam(1, -2, 1, 2)),  # X
        ]
        for beam_a, beam_b in pairs:
            c1 = solver.find_topology(beam_a, beam_b)
            c2 = solver.find_topology(beam_b, beam_a)
            assert c1 is not None and c2 is not None
            assert c1.topology == c2.topology


# =============================================================================
# find_intersecting_pairs
# =============================================================================


class TestFindIntersectingPairs:
    """Tests for ConnectionSolver2D.find_intersecting_pairs."""

    def test_single_overlapping_pair(self):
        """Three beams where only one pair's AABBs overlap → one result."""
        solver = ConnectionSolver2D()
        beam_a = make_beam(0, 0, 2, 0)
        beam_b = make_beam(2, 0, 2, 2)  # meets beam_a at the corner
        beam_c = make_beam(10, 0, 12, 0)  # completely separate
        pairs = list(solver.find_intersecting_pairs([beam_a, beam_b, beam_c]))
        assert len(pairs) == 1
        pair_ids = {id(pairs[0][0]), id(pairs[0][1])}
        assert pair_ids == {id(beam_a), id(beam_b)}

    def test_multiple_overlapping_pairs(self):
        """One long horizontal + two short verticals → two overlapping pairs.

        beam_v1 (x=2) and beam_v2 (x=5) are spaced 3 units apart.  Their AABB
        x-gap (3.0 - 2*0.25 = 2.5) exceeds 2*max_distance (2.0), so they are
        not detected as an overlapping pair.  Each vertical only pairs with
        the horizontal.
        """
        solver = ConnectionSolver2D()
        beam_h = make_beam(0, 0, 6, 0)
        beam_v1 = make_beam(2, -2, 2, 0)  # T into beam_h at x=2
        beam_v2 = make_beam(5, -2, 5, 0)  # T into beam_h at x=5  (gap > 2·max_distance)
        pairs = list(solver.find_intersecting_pairs([beam_h, beam_v1, beam_v2]))
        # beam_h ↔ beam_v1, beam_h ↔ beam_v2  (v1 and v2 are too far apart to pair)
        assert len(pairs) == 2

    def test_no_overlapping_beams(self):
        """Beams all separated → empty result."""
        solver = ConnectionSolver2D()
        pairs = list(
            solver.find_intersecting_pairs(
                [
                    make_beam(0, 0, 1, 0),
                    make_beam(5, 0, 6, 0),
                    make_beam(10, 0, 11, 0),
                ]
            )
        )
        assert pairs == []

    def test_each_pair_yielded_once(self):
        """No (a,b) / (b,a) duplicates — each unordered pair appears once."""
        solver = ConnectionSolver2D()
        beam_a = make_beam(0, 0, 4, 0)
        beam_b = make_beam(2, -2, 2, 2)
        pairs = list(solver.find_intersecting_pairs([beam_a, beam_b]))
        assert len(pairs) == 1

    def test_single_beam_returns_empty(self):
        solver = ConnectionSolver2D()
        assert list(solver.find_intersecting_pairs([make_beam(0, 0, 2, 0)])) == []

    def test_empty_list_returns_empty(self):
        solver = ConnectionSolver2D()
        assert list(solver.find_intersecting_pairs([])) == []

    def test_yielded_pairs_are_tuples_of_two_beams(self):
        """Each yielded item must be a 2-tuple of Beam2D instances."""
        solver = ConnectionSolver2D()
        beam_a = make_beam(0, 0, 4, 0)
        beam_b = make_beam(2, -2, 2, 0)
        pairs = list(solver.find_intersecting_pairs([beam_a, beam_b]))
        assert len(pairs) == 1
        pair = pairs[0]
        assert len(pair) == 2
        assert isinstance(pair[0], Beam2D)
        assert isinstance(pair[1], Beam2D)


# =============================================================================
# find_intersecting_agent_pairs
# =============================================================================


class TestFindIntersectingAgentPairs:
    """Tests for ConnectionSolver2D.find_intersecting_agent_pairs."""

    def test_overlapping_pair_returned(self):
        """Two agents whose element AABBs overlap → one pair returned."""
        solver = ConnectionSolver2D()
        agent_a = SimpleAgent([make_beam(0, 0, 4, 0)])
        agent_b = SimpleAgent([make_beam(2, -2, 2, 0)])  # T-intersects agent_a
        agent_c = SimpleAgent([make_beam(20, 0, 24, 0)])  # far away
        pairs = list(solver.find_intersecting_agent_pairs([agent_a, agent_b, agent_c]))
        assert len(pairs) == 1
        pair_ids = {id(pairs[0][0]), id(pairs[0][1])}
        assert pair_ids == {id(agent_a), id(agent_b)}

    def test_empty_agent_skipped(self):
        """An agent with an empty ``elements`` list is never matched."""
        solver = ConnectionSolver2D()
        agent_a = SimpleAgent([make_beam(0, 0, 4, 0)])
        agent_empty = SimpleAgent([])
        pairs = list(solver.find_intersecting_agent_pairs([agent_a, agent_empty]))
        assert pairs == []

    def test_no_overlapping_agents(self):
        """Agents in completely different regions produce no pairs."""
        solver = ConnectionSolver2D()
        agent_a = SimpleAgent([make_beam(0, 0, 1, 0)])
        agent_b = SimpleAgent([make_beam(10, 10, 11, 10)])
        assert list(solver.find_intersecting_agent_pairs([agent_a, agent_b])) == []

    def test_all_agents_overlap(self):
        """Three agents that all overlap each other → three pairs."""
        solver = ConnectionSolver2D()
        # agent_b's beam crosses both agent_a and agent_c; agent_a and agent_c overlap too
        agent_a = SimpleAgent([make_beam(0, 0, 4, 0)])  # y=±0.25
        agent_b = SimpleAgent([make_beam(2, -2, 2, 2)])  # x=±0.25
        agent_c = SimpleAgent([make_beam(0, 0.1, 4, 0.1)])  # y=−0.15..0.35 (overlaps agent_a)
        pairs = list(solver.find_intersecting_agent_pairs([agent_a, agent_b, agent_c]))
        assert len(pairs) == 3

    def test_single_agent_returns_empty(self):
        solver = ConnectionSolver2D()
        agent = SimpleAgent([make_beam(0, 0, 2, 0)])
        assert list(solver.find_intersecting_agent_pairs([agent])) == []

    def test_each_agent_pair_yielded_once(self):
        """No duplicate (a,b) / (b,a) entries."""
        solver = ConnectionSolver2D()
        agent_a = SimpleAgent([make_beam(0, 0, 4, 0)])
        agent_b = SimpleAgent([make_beam(2, -2, 2, 0)])
        pairs = list(solver.find_intersecting_agent_pairs([agent_a, agent_b]))
        assert len(pairs) == 1

    def test_multi_element_agent_aabb(self):
        """Overlap is detected even when an agent holds several beams whose
        *combined* AABB reaches the other agent."""
        solver = ConnectionSolver2D()
        # agent_a: two short parallel beams, neither individually near agent_b,
        #        but together their combined AABB does span x=0..6
        agent_a = SimpleAgent(
            [
                make_beam(0, 0, 2, 0),
                make_beam(4, 0, 6, 0),
            ]
        )
        # agent_b: a beam at x=3 which sits between the two agent_a beams
        # The combined AABB of agent_a (x=0..6) overlaps agent_b (x=2.75..3.25)
        agent_b = SimpleAgent([make_beam(3, -1, 3, 1)])
        pairs = list(solver.find_intersecting_agent_pairs([agent_a, agent_b]))
        assert len(pairs) == 1
