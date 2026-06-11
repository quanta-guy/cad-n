"""Tests for the nesting engine: the correctness invariants matter most
(no overlap, inside sheet, clearance), then metrics and behaviour."""

import math

import pytest

from cad_n.core.models import (
    NestingSettings,
    Part,
    PlacementStrategy,
    Sheet,
    make_rectangle_part,
)
from cad_n.core.nesting_engine import nest


def _assert_valid(result, sheet, settings):
    """Core invariants that must hold for ANY result."""
    minx, miny, maxx, maxy = sheet.usable_rect()
    polys = [pl.polygon_world for pl in result.placements]
    sheets = [pl.sheet_index for pl in result.placements]

    # 1) every placement inside the usable rectangle
    for pl in result.placements:
        bx0, by0, bx1, by1 = pl.polygon_world.bounds
        assert bx0 >= minx - 1e-3 and by0 >= miny - 1e-3
        assert bx1 <= maxx + 1e-3 and by1 <= maxy + 1e-3

    # 2) no overlap, and 3) clearance between parts on the same sheet
    for i in range(len(polys)):
        for j in range(i + 1, len(polys)):
            if sheets[i] != sheets[j]:
                continue
            inter = polys[i].intersection(polys[j])
            assert inter.is_empty or inter.area < 1e-4
            dist = polys[i].distance(polys[j])
            assert dist >= settings.clearance_mm - 1e-2


def test_two_rectangles_one_sheet():
    sheet = Sheet("S", 200, 200)
    settings = NestingSettings(part_spacing_mm=0, kerf_mm=0, attempt_count=1)
    parts = [make_rectangle_part("A", 50, 50), make_rectangle_part("B", 60, 40)]
    res = nest(parts, sheet, settings)
    assert res.total_parts_nested == 2
    assert res.sheet_count_used == 1
    _assert_valid(res, sheet, settings)


def test_no_overlap_many_parts():
    sheet = Sheet("S", 300, 300)
    settings = NestingSettings(part_spacing_mm=3, kerf_mm=1, attempt_count=3)
    a = make_rectangle_part("A", 40, 25, quantity=12)
    b = make_rectangle_part("B", 20, 20, quantity=12)
    res = nest([a, b], sheet, settings)
    assert res.total_parts_nested == 24
    _assert_valid(res, sheet, settings)


def test_clearance_exact():
    sheet = Sheet("S", 200, 50)
    settings = NestingSettings(part_spacing_mm=4, kerf_mm=0, attempt_count=1,
                               rotation_step_deg=0)
    res = nest([make_rectangle_part("A", 20, 20, quantity=2, allow_rotation=False)],
               sheet, settings)
    assert res.total_parts_nested == 2
    d = res.placements[0].polygon_world.distance(res.placements[1].polygon_world)
    assert math.isclose(d, 4.0, abs_tol=0.05)


def test_part_too_large_is_unnested():
    sheet = Sheet("S", 1000, 500)
    settings = NestingSettings(attempt_count=1)
    big = make_rectangle_part("BIG", 5000, 20, allow_rotation=True)
    res = nest([big], sheet, settings)
    assert res.total_parts_nested == 0
    assert len(res.unnested_parts) == 1
    assert "larger" in res.unnested_parts[0].reason.lower()


def test_multi_sheet():
    # 60x60 parts on a 100x100 sheet: only one fits per sheet (2*60 > 100).
    sheet = Sheet("S", 100, 100)
    settings = NestingSettings(part_spacing_mm=0, attempt_count=1)
    res = nest([make_rectangle_part("Q", 60, 60, quantity=4)], sheet, settings)
    assert res.total_parts_nested == 4
    assert res.sheet_count_used == 4
    _assert_valid(res, sheet, settings)


def test_utilization_value():
    sheet = Sheet("S", 100, 100)  # usable area 10000
    settings = NestingSettings(part_spacing_mm=0, attempt_count=1)
    res = nest([make_rectangle_part("A", 50, 50, allow_rotation=False)], sheet, settings)
    assert math.isclose(res.utilization_by_sheet[0], 0.25, rel_tol=1e-6)
    assert math.isclose(res.total_utilization, 0.25, rel_tol=1e-6)


def test_remnant_length():
    sheet = Sheet("S", 200, 50, margin_mm=0)
    settings = NestingSettings(part_spacing_mm=0, attempt_count=1, rotation_step_deg=0)
    res = nest([make_rectangle_part("A", 30, 30, allow_rotation=False)], sheet, settings)
    # one 30-long part placed at x=0..30 -> remnant = 200 - 30 - 0
    assert math.isclose(res.used_length_by_sheet[0], 30.0, abs_tol=1e-6)
    assert math.isclose(res.remnant_length_by_sheet[0], 170.0, abs_tol=1e-6)


def test_rotation_enables_fit():
    # Sheet is short in Y; the part only fits if rotated 90 degrees.
    sheet = Sheet("S", 100, 20, margin_mm=0)
    settings = NestingSettings(part_spacing_mm=0, attempt_count=1, rotation_step_deg=90)
    part = make_rectangle_part("L", 18, 80)  # 18 wide x 80 tall -> rotate to 80x18
    res = nest([part], sheet, settings)
    assert res.total_parts_nested == 1
    assert res.placements[0].rotation_deg in (90.0, 270.0)


def test_deterministic_with_seed():
    sheet = Sheet("S", 250, 250)
    settings = NestingSettings(part_spacing_mm=2, attempt_count=4, random_seed=7)
    parts = [make_rectangle_part("A", 40, 30, quantity=10),
             make_rectangle_part("B", 25, 25, quantity=10)]
    r1 = nest(parts, sheet, settings)
    r2 = nest(parts, sheet, settings)
    assert r1.total_parts_nested == r2.total_parts_nested
    assert r1.sheet_count_used == r2.sheet_count_used
    assert math.isclose(r1.total_utilization, r2.total_utilization, rel_tol=1e-9)


def _assert_valid_multi(result, settings):
    """Invariants for a (possibly heterogeneous) multi-sheet result."""
    for pl in result.placements:
        sh = result.sheet_at(pl.sheet_index)
        minx, miny, maxx, maxy = sh.usable_rect()
        bx0, by0, bx1, by1 = pl.polygon_world.bounds
        assert bx0 >= minx - 1e-3 and by0 >= miny - 1e-3
        assert bx1 <= maxx + 1e-3 and by1 <= maxy + 1e-3
    polys = [pl.polygon_world for pl in result.placements]
    sidx = [pl.sheet_index for pl in result.placements]
    for i in range(len(polys)):
        for j in range(i + 1, len(polys)):
            if sidx[i] != sidx[j]:
                continue
            inter = polys[i].intersection(polys[j])
            assert inter.is_empty or inter.area < 1e-4
            assert polys[i].distance(polys[j]) >= settings.clearance_mm - 1e-2


def test_multi_sheet_mix_beats_single_stock():
    # 5x 90x90: A(200x100) holds 2 per sheet, B(100x100) holds 1. Single A needs
    # 3 sheets (stock 60000); 2xA + 1xB places all in 50000 -> the mix wins.
    A = Sheet("A", 200, 100, margin_mm=0)
    B = Sheet("B", 100, 100, margin_mm=0)
    parts = [make_rectangle_part("P", 90, 90, quantity=5, allow_rotation=False)]
    settings = NestingSettings(part_spacing_mm=0, attempt_count=2, rotation_step_deg=0)

    single = nest(parts, A, settings)
    single_stock = sum(s.width_mm * s.height_mm for s in single.sheets)

    multi = nest(parts, [A, B], settings)
    assert multi.total_parts_nested == 5
    multi_stock = sum(s.width_mm * s.height_mm for s in multi.sheets)
    assert multi_stock < single_stock            # the mix wastes less stock
    assert len(multi.configurations) > 1          # alternatives to choose from
    _assert_valid_multi(multi, settings)


def test_multi_sheet_configurations_ranked_best_first():
    A = Sheet("A", 200, 100, margin_mm=0)
    B = Sheet("B", 100, 100, margin_mm=0)
    parts = [make_rectangle_part("P", 90, 90, quantity=5, allow_rotation=False)]
    res = nest(parts, [A, B],
               NestingSettings(part_spacing_mm=0, attempt_count=2, rotation_step_deg=0))
    cfgs = res.configurations
    assert cfgs[0].all_placed
    assert cfgs[0].sheets_used == res.sheet_count_used
    # Every fully-placed config is at least as costly (stock area) as the best.
    placed = [c for c in cfgs if c.all_placed]
    assert cfgs[0].stock_area == min(c.stock_area for c in placed)


def test_single_element_list_matches_single_sheet():
    sheet = Sheet("S", 300, 200)
    settings = NestingSettings(attempt_count=1, part_spacing_mm=2)
    parts = [make_rectangle_part("A", 50, 40, quantity=4)]
    r_single = nest(parts, sheet, settings)
    r_list = nest(parts, [sheet], settings)
    assert r_single.total_parts_nested == r_list.total_parts_nested
    assert r_single.sheet_count_used == r_list.sheet_count_used
    assert math.isclose(r_single.total_utilization, r_list.total_utilization, rel_tol=1e-9)


def test_part_with_hole_area_counts_net():
    sheet = Sheet("S", 200, 200)
    settings = NestingSettings(part_spacing_mm=0, attempt_count=1)
    part = Part.from_rings(
        "ring",
        outer=[(0, 0), (100, 0), (100, 100), (0, 100)],
        holes=[[(40, 40), (60, 40), (60, 60), (40, 60)]],
    )
    res = nest([part], sheet, settings)
    assert res.total_parts_nested == 1
    # net area 10000-400 = 9600; utilization = 9600/40000 = 0.24
    assert math.isclose(res.utilization_by_sheet[0], 9600 / 40000, rel_tol=1e-6)
