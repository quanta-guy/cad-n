"""Automated regression guards (doc 14.4).

Not pixel comparison -- these lock in the behavioural invariants the doc lists
for stable releases so a future change that silently regresses packing quality,
inflates sheet counts, or leaks annotation entities into the export is caught.
"""

import ezdxf
import pytest

from cad_n.core.dxf_exporter import ExportOptions, export_nesting
from cad_n.core.models import NestingSettings, Sheet, make_rectangle_part
from cad_n.core.nesting_engine import nest


def test_mixed_rectangles_baseline():
    sheet = Sheet("S", 600, 400, margin_mm=5)
    settings = NestingSettings(part_spacing_mm=4, attempt_count=4, random_seed=12345)
    parts = [make_rectangle_part("A", 120, 80, quantity=6),
             make_rectangle_part("B", 60, 60, quantity=8),
             make_rectangle_part("C", 200, 40, quantity=4)]
    res = nest(parts, sheet, settings)
    assert res.total_parts_nested == 18          # all parts placed
    assert res.sheet_count_used == 1             # must stay on one sheet
    assert res.total_utilization >= 0.45         # baseline ~0.515; guard against regress


def test_multisheet_count_stable():
    sheet = Sheet("S", 300, 300, margin_mm=5)
    res = nest([make_rectangle_part("Q", 110, 110, quantity=9)], sheet,
               NestingSettings(part_spacing_mm=3, attempt_count=2))
    assert res.total_parts_nested == 9
    assert res.sheet_count_used == 3             # 4 + 4 + 1


def test_export_has_no_annotation_leak():
    sheet = Sheet("S", 600, 400, margin_mm=5)
    res = nest([make_rectangle_part("A", 120, 80, quantity=6)], sheet,
               NestingSettings(attempt_count=2))
    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".dxf")
    os.close(fd)
    try:
        export_nesting(res, path, sheet, ExportOptions(include_labels=False,
                                                       include_sheet_boundary=False))
        doc = ezdxf.readfile(path)
        anno = sum(1 for e in doc.modelspace()
                   if e.dxftype() in ("TEXT", "MTEXT", "DIMENSION", "LEADER", "MLEADER"))
        cut = sum(1 for e in doc.modelspace()
                  if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == "CUT")
        assert anno == 0
        assert cut == res.total_parts_nested
    finally:
        os.remove(path)
