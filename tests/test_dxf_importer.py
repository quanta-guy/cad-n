"""Tests for the DXF importer across all fixture categories."""

import math

import dxfgen
import pytest

from cad_n.core import dxf_importer as imp
from cad_n.core.models import Severity


def _import(doc, **opt_kw):
    options = imp.ImportOptions(**opt_kw)
    summary = imp.summarize(doc, "mem.dxf")
    return imp.extract(doc, "mem.dxf", options, summary)


def _codes(res):
    return {n.code for n in res.notices}


def test_simple_rectangle():
    res = _import(dxfgen.simple_rectangle(100, 60))
    assert len(res.parts) == 1
    assert math.isclose(res.parts[0].area, 6000.0, rel_tol=1e-6)


def test_rectangle_with_hole():
    res = _import(dxfgen.rectangle_with_hole())
    assert len(res.parts) == 1
    p = res.parts[0]
    assert len(p.holes) == 1
    # 100*100 - pi*15^2
    assert math.isclose(p.area, 10000 - math.pi * 225, rel_tol=1e-3)


def test_circle():
    res = _import(dxfgen.circle(25))
    assert len(res.parts) == 1
    # Flattened circle area is legitimately slightly under pi*r^2 (inscribed
    # polygon at 0.1 mm chord tolerance), so allow ~1%.
    assert math.isclose(res.parts[0].area, math.pi * 625, rel_tol=1e-2)
    assert res.parts[0].area <= math.pi * 625  # inscribed -> never larger


def test_arc_profile_closes_into_obround():
    res = _import(dxfgen.arc_profile(80, 20))
    assert len(res.parts) == 1
    # obround area = rectangle (40 x 40) + circle (r=20) = 1600 + pi*400
    assert math.isclose(res.parts[0].area, 1600 + math.pi * 400, rel_tol=1e-2)


def test_spline_profile_detected():
    res = _import(dxfgen.spline_profile())
    assert len(res.parts) == 1
    assert "CURVES_FLATTENED" in _codes(res)


def test_multiple_parts_combined():
    res = _import(dxfgen.multiple_parts())
    assert len(res.parts) == 3


def test_open_contour_reported_and_skipped():
    res = _import(dxfgen.open_contour())
    # Only the closed 50x50 part survives; the open one is skipped + reported.
    assert len(res.parts) == 1
    assert math.isclose(res.parts[0].area, 2500.0, rel_tol=1e-6)
    assert "OPEN_CONTOUR" in _codes(res)


def test_internal_open_cuts_preserved():
    res = _import(dxfgen.internal_micro_joints())
    assert len(res.parts) == 1
    p = res.parts[0]
    # Open inner linework must NOT become a hole -> full solid area is kept.
    assert math.isclose(p.area, 200 * 120, rel_tol=1e-6)
    assert len(p.holes) == 0
    # All 5 open segments (4 tabbed chase edges + 1 edge micro-joint) are kept.
    assert len(p.internal_paths) == 5
    assert "INTERNAL_CUTS_KEPT" in _codes(res)
    assert "OPEN_CONTOUR" not in _codes(res)


def test_duplicate_geometry_deduped():
    res = _import(dxfgen.duplicate_geometry())
    assert len(res.parts) == 1
    assert math.isclose(res.parts[0].area, 2400.0, rel_tol=1e-6)
    assert "DUPLICATE_SEGMENTS" in _codes(res)


def test_dimensions_and_text_never_become_parts():
    """The headline correctness guarantee (doc section 18)."""
    res = _import(dxfgen.dimensions_and_text())
    assert len(res.parts) == 1
    assert math.isclose(res.parts[0].area, 6000.0, rel_tol=1e-6)
    # The DIM layer is auto-excluded; if included, annotation is still ignored.
    res2 = _import(dxfgen.dimensions_and_text(), cut_layers={"CUT", "DIM"})
    assert len(res2.parts) == 1
    assert "ANNOTATION_IGNORED" in _codes(res2)


def test_blocks_insert_exploded():
    res = _import(dxfgen.blocks_insert())
    assert len(res.parts) == 1
    assert len(res.parts[0].holes) == 1
    assert "BLOCKS_EXPLODED" in _codes(res)


def test_blocks_skipped_when_disabled():
    res = _import(dxfgen.blocks_insert(), explode_blocks=False)
    assert len(res.parts) == 0
    assert "BLOCKS_SKIPPED" in _codes(res)


def test_tiny_fragments_filtered():
    res = _import(dxfgen.tiny_fragments())
    assert len(res.parts) == 1
    assert math.isclose(res.parts[0].area, 10000.0, rel_tol=1e-6)


def test_non_mm_units_scaled_to_mm():
    res = _import(dxfgen.non_mm_units())
    assert len(res.parts) == 1
    # 2in x 1in -> 50.8 x 25.4 mm
    assert math.isclose(res.parts[0].area, 50.8 * 25.4, rel_tol=1e-4)
    assert "UNITS_SCALED" in _codes(res)


def test_common_cut_rectangles_two_parts():
    res = _import(dxfgen.common_cut_rectangles(), group_identical=False)
    assert len(res.parts) == 2
    for p in res.parts:
        assert math.isclose(p.area, 1500.0, rel_tol=1e-6)


def test_identical_parts_grouped_by_quantity():
    # large_file is a 20x20 grid of identical rects -> 1 grouped part qty 400.
    res = _import(dxfgen.large_file(rows=5, cols=4))
    assert len(res.parts) == 1
    assert res.parts[0].quantity == 20


def test_garbage_file_is_handled_not_crashed(tmp_path):
    """A non-DXF / corrupt file must produce a clean error, never an exception."""
    p = tmp_path / "bad.dxf"
    p.write_text("this is not a dxf at all\n42\nXYZZY\n", encoding="utf-8")
    res = imp.import_dxf(str(p))   # must not raise
    assert res.parts == []
    assert any(n.severity is Severity.ERROR for n in res.notices)


def test_full_file_roundtrip(tmp_path):
    """Exercise the file-based open path, not just in-memory extract."""
    doc = dxfgen.rectangle_with_hole()
    p = tmp_path / "rh.dxf"
    doc.saveas(p)
    res = imp.import_dxf(str(p))
    assert len(res.parts) == 1
    assert len(res.parts[0].holes) == 1
