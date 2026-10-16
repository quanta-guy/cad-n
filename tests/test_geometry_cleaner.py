"""Tests for the geometry cleaner: welding, stitching, DCEL faces, containment."""

import math

import pytest
from conftest import ring_segments

from cad_n.config import Tolerances
from cad_n.core import geometry_cleaner as gc

SQ = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


# --------------------------------------------------------------------------- #
# Point welding
# --------------------------------------------------------------------------- #
def test_point_weld_merges_close_points():
    w = gc.PointWeld(0.05)
    a = w.weld(0.0, 0.0)
    b = w.weld(0.02, 0.0)        # within tol -> same index
    c = w.weld(5.0, 5.0)         # far -> new index
    assert a == b
    assert c != a
    assert len(w.points) == 2


def test_point_weld_straddling_grid_boundary():
    # Two points either side of a cell boundary but within tolerance.
    w = gc.PointWeld(0.1)
    a = w.weld(0.099, 0.0)
    b = w.weld(0.101, 0.0)
    assert a == b


# --------------------------------------------------------------------------- #
# Collinear merge
# --------------------------------------------------------------------------- #
def test_merge_collinear_drops_redundant_midpoint():
    coords = [(0, 0), (5, 0), (10, 0), (10, 10), (0, 10)]  # (5,0) is redundant
    out = gc.merge_collinear(coords, 0.5)
    assert (5, 0) not in out
    assert len(out) == 4


def test_merge_collinear_keeps_real_corners():
    out = gc.merge_collinear(list(SQ), 0.5)
    assert len(out) == 4


# --------------------------------------------------------------------------- #
# Stitching loose segments
# --------------------------------------------------------------------------- #
def test_stitch_single_square():
    loops, opens, dup, tiny, leftover = gc.stitch_loops(ring_segments(SQ), Tolerances())
    assert len(loops) == 1
    assert opens == 0
    assert len(loops[0]) == 4


def test_stitch_detects_open_contour():
    # Three sides of a square -> open chain, no loop.
    segs = [((0, 0), (10, 0)), ((10, 0), (10, 10)), ((10, 10), (0, 10))]
    loops, opens, dup, tiny, leftover = gc.stitch_loops(segs, Tolerances())
    assert loops == []
    assert opens == 1


def test_stitch_closed_loop_with_stray_tail():
    # A square plus a dangling tail edge sticking out of one corner.
    segs = ring_segments(SQ) + [((10, 10), (15, 15))]
    loops, opens, dup, tiny, leftover = gc.stitch_loops(segs, Tolerances())
    assert len(loops) == 1          # square recovered
    assert opens == 1               # tail reported as open


def test_stitch_two_separate_squares():
    sq2 = [(100, 0), (110, 0), (110, 10), (100, 10)]
    segs = ring_segments(SQ) + ring_segments(sq2)
    loops, opens, dup, tiny, leftover = gc.stitch_loops(segs, Tolerances())
    assert len(loops) == 2


def test_stitch_counts_duplicates():
    segs = ring_segments(SQ) + ring_segments(SQ)  # every edge twice
    loops, opens, dup, tiny, leftover = gc.stitch_loops(segs, Tolerances())
    assert len(loops) == 1
    assert dup == 4


def test_stitch_returns_open_linework_as_leftover():
    # Three sides of a square -> no loop; the open linework comes back whole.
    segs = [((0, 0), (10, 0)), ((10, 0), (10, 10)), ((10, 10), (0, 10))]
    loops, opens, dup, tiny, leftover = gc.stitch_loops(segs, Tolerances())
    assert loops == []
    assert len(leftover) == 1
    for corner in [(0, 0), (10, 0), (10, 10), (0, 10)]:
        assert corner in leftover[0]


def test_stitch_keeps_only_the_dangling_tail_as_leftover():
    # A closed square plus a dangling tail: the square loops, the tail is leftover.
    segs = ring_segments(SQ) + [((10, 10), (15, 15))]
    loops, opens, dup, tiny, leftover = gc.stitch_loops(segs, Tolerances())
    assert len(loops) == 1
    assert len(leftover) == 1
    assert (15, 15) in leftover[0]


def test_stitch_closes_outline_halves_that_overshoot_by_1mm():
    # TO NEST.dxf (Oct 16): a panel drawn as two open polylines whose ends run
    # 1 mm past each other's corner (T-junctions, gap > snap). Must close into
    # one loop, with the 1 mm overshoot stubs dropped.
    left = [(101, 0), (0, 0), (0, 50), (101, 50)]
    right = [(100, 0), (100, 50)]
    segs = [(p[i], p[i + 1]) for p in (left, right) for i in range(len(p) - 1)]
    loops, opens, dup, tiny, leftover = gc.stitch_loops(segs, Tolerances())
    assert len(loops) == 1
    assert abs(abs(gc._signed_area(loops[0])) - 5000) < 1e-6
    assert leftover == []


# --------------------------------------------------------------------------- #
# DCEL face extraction (shared edges / vertices) -- verifies sign convention
# --------------------------------------------------------------------------- #
def test_dcel_two_adjacent_squares_share_edge():
    a = [(0, 0), (10, 0), (10, 10), (0, 10)]
    b = [(10, 0), (20, 0), (20, 10), (10, 10)]
    segs = ring_segments(a) + ring_segments(b)
    res = gc.build_polygons([], segs, Tolerances())
    assert len(res.polygons) == 2, [p.area for p in res.polygons]
    for p in res.polygons:
        assert math.isclose(p.area, 100.0, rel_tol=1e-6)


def test_dcel_figure_eight_shared_vertex():
    a = [(0, 0), (10, 0), (10, 10), (0, 10)]
    b = [(10, 10), (20, 10), (20, 20), (10, 20)]
    segs = ring_segments(a) + ring_segments(b)
    res = gc.build_polygons([], segs, Tolerances())
    assert len(res.polygons) == 2
    for p in res.polygons:
        assert math.isclose(p.area, 100.0, rel_tol=1e-6)


# --------------------------------------------------------------------------- #
# Containment / holes
# --------------------------------------------------------------------------- #
def test_containment_square_with_hole():
    outer = [(0, 0), (100, 0), (100, 100), (0, 100)]
    hole = [(40, 40), (60, 40), (60, 60), (40, 60)]
    res = gc.build_polygons([outer, hole], [], Tolerances())
    assert len(res.polygons) == 1
    poly = res.polygons[0]
    assert len(poly.interiors) == 1
    # Net area = 100*100 - 20*20 = 10000 - 400.
    assert math.isclose(poly.area, 9600.0, rel_tol=1e-6)


def test_part_inside_hole_becomes_separate_part():
    outer = [(0, 0), (100, 0), (100, 100), (0, 100)]
    hole = [(20, 20), (80, 20), (80, 80), (20, 80)]
    island = [(40, 40), (60, 40), (60, 60), (40, 60)]  # solid inside the hole
    res = gc.build_polygons([outer, hole, island], [], Tolerances())
    # Outer (with hole) + island = 2 solid parts.
    assert len(res.polygons) == 2
    areas = sorted(p.area for p in res.polygons)
    assert math.isclose(areas[0], 400.0, rel_tol=1e-6)       # island 20x20
    assert math.isclose(areas[1], 10000 - 3600, rel_tol=1e-6)  # outer minus 60x60 hole


# --------------------------------------------------------------------------- #
# Validation / repair
# --------------------------------------------------------------------------- #
def test_bowtie_is_repaired_or_dropped():
    bowtie = [(0, 0), (10, 10), (10, 0), (0, 10)]  # self-intersecting
    res = gc.build_polygons([bowtie], [], Tolerances())
    # Either repaired into valid pieces or dropped, but never invalid output.
    for p in res.polygons:
        assert p.is_valid


def test_tiny_fragment_filtered():
    tiny = [(0, 0), (0.2, 0), (0.2, 0.2), (0, 0.2)]  # 0.04 mm^2 < 1.0 default
    res = gc.build_polygons([tiny], [], Tolerances())
    assert res.polygons == []


def test_repair_handles_geometry_collection_from_figure_eight_hole():
    # A figure-8 hole retracing its shared middle edge (real DXF: two stacked
    # slots drawn as one polyline) makes make_valid return a GeometryCollection
    # (polygon + collapsed line). The part must be kept, not dropped.
    from shapely.geometry import Polygon

    hole = [(10, 10), (30, 10), (30, 20), (10, 20), (10, 30), (30, 30), (30, 20), (10, 20)]
    poly = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)], [hole])
    assert not poly.is_valid
    fixed, notices = gc.validate_and_repair(poly, Tolerances())
    assert fixed is not None and fixed.is_valid
    assert fixed.area == pytest.approx(100 * 100 - 20 * 20)
    assert "UNREPAIRABLE" not in {n.code for n in notices}


def test_touching_holes_merge_into_one_opening_with_common_line():
    # Two 20x10 cutouts sharing the y=20 edge (zero-width web, as in the real
    # figure-8 slot pairs) become one 20x20 opening; the shared edge is kept
    # as an internal common cut line.
    outer = [(0, 0), (100, 0), (100, 100), (0, 100)]
    top = [(10, 20), (30, 20), (30, 30), (10, 30)]
    bottom = [(10, 10), (30, 10), (30, 20), (10, 20)]
    segs = ring_segments(outer) + ring_segments(top) + ring_segments(bottom)
    res = gc.build_polygons([], segs, Tolerances())
    assert len(res.polygons) == 1
    part = res.polygons[0]
    assert part.is_valid and len(part.interiors) == 1
    assert part.area == pytest.approx(100 * 100 - 20 * 20)
    assert "TOUCHING_HOLES_MERGED" in {n.code for n in res.notices}
    shared = [p for p in res.internal_paths if all(abs(y - 20) < 1e-9 for _, y in p)]
    assert shared and sum(abs(p[-1][0] - p[0][0]) for p in shared) == pytest.approx(20)


def test_overlapping_collinear_line_is_split_and_deduplicated():
    # A stray LINE drawn corner-to-corner over a hole side that has a small
    # notch (real case: LINEs over rounded slot corners) overlaps the side but
    # shares no nodes with it. Without splitting, the hole is lost entirely.
    outer = [(0, 0), (100, 0), (100, 100), (0, 100)]
    hole = [(10, 20), (30, 20), (30, 40), (10, 40), (10, 32), (12, 30), (10, 28)]
    stray = ((10, 20), (10, 40))
    res = gc.build_polygons([], ring_segments(outer) + ring_segments(hole) + [stray], Tolerances())
    assert len(res.polygons) == 1
    assert len(res.polygons[0].interiors) == 1
    assert res.polygons[0].area == pytest.approx(100 * 100 - 20 * 20)


def test_t_junction_edge_cut_is_not_split_off_as_a_part():
    # An open U-cut whose ends touch a part edge (edge micro-joint) stays
    # internal linework; it must not carve a separate slug part.
    outer = [(0, 0), (100, 0), (100, 100), (0, 100)]
    u = [((40, 0), (40, 15)), ((40, 15), (55, 15)), ((55, 15), (55, 0))]
    res = gc.build_polygons([], ring_segments(outer) + u, Tolerances())
    assert len(res.polygons) == 1
    assert res.polygons[0].area == pytest.approx(100 * 100)
