"""Exporter tests: clean output, holes preserved, round-trip reopen, and the
validation gate that blocks bad geometry."""

import dxfgen
import ezdxf
import pytest
from shapely.geometry import box

from cad_n.core import dxf_importer as imp
from cad_n.core.dxf_exporter import ExportOptions, export_nesting
from cad_n.core.models import (
    NestingResult,
    NestingSettings,
    Part,
    Placement,
    Sheet,
    make_rectangle_part,
)
from cad_n.core.nesting_engine import nest


def _count_on_layer(doc, layer, dxftype):
    msp = doc.modelspace()
    return sum(1 for e in msp if e.dxf.layer == layer and e.dxftype() == dxftype)


def test_export_reopens_and_has_expected_entities(tmp_path):
    sheet = Sheet("S", 300, 200)
    settings = NestingSettings(part_spacing_mm=2, attempt_count=1)
    res = nest([make_rectangle_part("A", 50, 40, quantity=3)], sheet, settings)
    out = tmp_path / "nest.dxf"
    rep = export_nesting(res, str(out), sheet, ExportOptions(include_labels=True))
    assert rep.success
    assert out.exists()

    doc = ezdxf.readfile(str(out))  # reopens cleanly
    assert _count_on_layer(doc, "CUT", "LWPOLYLINE") == 3
    assert _count_on_layer(doc, "SHEET_BOUNDARY", "LWPOLYLINE") == res.sheet_count_used
    assert doc.header.get("$INSUNITS") == 4


def test_export_no_annotation_when_disabled(tmp_path):
    sheet = Sheet("S", 300, 200)
    res = nest([make_rectangle_part("A", 50, 40, quantity=2)], sheet,
               NestingSettings(attempt_count=1))
    out = tmp_path / "clean.dxf"
    export_nesting(res, str(out), sheet,
                   ExportOptions(include_labels=False, include_sheet_boundary=False))
    doc = ezdxf.readfile(str(out))
    texts = sum(1 for e in doc.modelspace() if e.dxftype() in ("TEXT", "MTEXT"))
    boundaries = _count_on_layer(doc, "SHEET_BOUNDARY", "LWPOLYLINE")
    assert texts == 0
    assert boundaries == 0


def test_export_preserves_holes_roundtrip(tmp_path):
    sheet = Sheet("S", 200, 200)
    part = Part.from_rings(
        "ring",
        outer=[(0, 0), (100, 0), (100, 100), (0, 100)],
        holes=[[(40, 40), (60, 40), (60, 60), (40, 60)]],
    )
    res = nest([part], sheet, NestingSettings(attempt_count=1, part_spacing_mm=0))
    out = tmp_path / "hole.dxf"
    export_nesting(res, str(out), sheet, ExportOptions(include_labels=False))

    # Re-import only the CUT layer; the single part must come back with 1 hole.
    reimp = imp.import_dxf(str(out), imp.ImportOptions(cut_layers={"CUT"}))
    assert len(reimp.parts) == 1
    assert len(reimp.parts[0].holes) == 1


def test_semantic_roundtrip_part_count(tmp_path):
    sheet = Sheet("S", 400, 300)
    res = nest([make_rectangle_part("A", 60, 40, quantity=5)], sheet,
               NestingSettings(attempt_count=1, part_spacing_mm=3))
    out = tmp_path / "rt.dxf"
    export_nesting(res, str(out), sheet, ExportOptions(include_labels=False))
    reimp = imp.import_dxf(str(out), imp.ImportOptions(cut_layers={"CUT"}, group_identical=False))
    assert len(reimp.parts) == res.total_parts_nested == 5


def test_internal_cut_lines_exported_and_roundtrip(tmp_path):
    """Preserved internal cut lines (micro-joints / chases) are emitted on CUT as
    open polylines, ride through nesting, and survive a re-import."""
    src = tmp_path / "mj.dxf"
    dxfgen.internal_micro_joints().saveas(str(src))
    parts = imp.import_dxf(str(src)).parts
    assert len(parts) == 1 and len(parts[0].internal_paths) == 5

    sheet = Sheet("S", 400, 300)
    res = nest(parts, sheet, NestingSettings(attempt_count=1, part_spacing_mm=2))
    assert res.total_parts_nested == 1
    assert sum(len(pl.internal_world) for pl in res.placements) == 5

    out = tmp_path / "mj_nest.dxf"
    rep = export_nesting(res, str(out), sheet, ExportOptions(include_labels=False))
    assert rep.success

    doc = ezdxf.readfile(str(out))
    cut = [e for e in doc.modelspace()
           if e.dxf.layer == "CUT" and e.dxftype() == "LWPOLYLINE"]
    # 1 closed outline + 5 open internal cut lines.
    assert len(cut) == 6
    assert sum(1 for e in cut if e.closed) == 1
    assert sum(1 for e in cut if not e.closed) == 5

    # Re-import keeps the part and all 5 internal cut lines.
    reimp = imp.import_dxf(str(out), imp.ImportOptions(cut_layers={"CUT"}))
    assert len(reimp.parts) == 1
    assert len(reimp.parts[0].internal_paths) == 5


def test_validation_blocks_overlap(tmp_path):
    sheet = Sheet("S", 200, 200)
    # Two manually-overlapping placements.
    p1 = Placement("a", "A", 0, 0, 0, 0, False, box(0, 0, 50, 50))
    p2 = Placement("b", "B", 0, 10, 10, 0, False, box(10, 10, 60, 60))
    res = NestingResult(placements=[p1, p2], sheet=sheet, sheet_count_used=1,
                        utilization_by_sheet=[0.5])
    out = tmp_path / "bad.dxf"
    rep = export_nesting(res, str(out), sheet)
    assert not rep.success
    assert any(n.code == "EXPORT_OVERLAP" for n in rep.notices)
    assert not out.exists()


def test_common_line_merges_shared_edge(tmp_path):
    # Two 50x40 parts with zero spacing butt together and share one vertical edge.
    sheet = Sheet("S", 300, 200)
    res = nest(
        [make_rectangle_part("A", 50, 40, quantity=2, allow_rotation=False)],
        sheet,
        NestingSettings(attempt_count=1, part_spacing_mm=0, kerf_mm=0, rotation_step_deg=0),
    )
    assert res.total_parts_nested == 2
    out = tmp_path / "common.dxf"
    rep = export_nesting(res, str(out), sheet,
                         ExportOptions(include_labels=False, common_line=True))
    assert rep.success
    assert rep.common_entities >= 1
    assert any(n.code == "EXPORT_COMMON_CUT" for n in rep.notices)

    doc = ezdxf.readfile(str(out))
    # The shared edge appears once on its own layer...
    assert _count_on_layer(doc, "COMMON_CUT", "LWPOLYLINE") >= 1
    # ...and the two parts dissolve into a single outer perimeter on CUT.
    assert _count_on_layer(doc, "CUT", "LWPOLYLINE") == 1


def test_common_line_off_keeps_independent_profiles(tmp_path):
    # With common-line off, butting parts still export as 2 full closed profiles.
    sheet = Sheet("S", 300, 200)
    res = nest(
        [make_rectangle_part("A", 50, 40, quantity=2, allow_rotation=False)],
        sheet,
        NestingSettings(attempt_count=1, part_spacing_mm=0, kerf_mm=0, rotation_step_deg=0),
    )
    out = tmp_path / "indep.dxf"
    rep = export_nesting(res, str(out), sheet,
                         ExportOptions(include_labels=False, common_line=False))
    assert rep.success
    assert rep.common_entities == 0
    doc = ezdxf.readfile(str(out))
    assert _count_on_layer(doc, "CUT", "LWPOLYLINE") == 2
    assert _count_on_layer(doc, "COMMON_CUT", "LWPOLYLINE") == 0


def test_validation_blocks_out_of_bounds(tmp_path):
    sheet = Sheet("S", 100, 100)
    p1 = Placement("a", "A", 0, 0, 0, 0, False, box(80, 80, 160, 160))  # off the sheet
    res = NestingResult(placements=[p1], sheet=sheet, sheet_count_used=1,
                        utilization_by_sheet=[0.1])
    rep = export_nesting(res, str(tmp_path / "oob.dxf"), sheet)
    assert not rep.success
    assert any(n.code == "EXPORT_OUT_OF_BOUNDS" for n in rep.notices)


def test_export_default_strips_labels_and_uses_white_lines(tmp_path):
    """Default export = clean cutting DXF: no text, white cut lines, yellow sheet."""
    sheet = Sheet("S", 300, 200)
    res = nest([make_rectangle_part("A", 50, 40, quantity=2)], sheet,
               NestingSettings(attempt_count=1))
    out = tmp_path / "default.dxf"
    rep = export_nesting(res, str(out), sheet)  # default ExportOptions
    assert rep.success
    doc = ezdxf.readfile(str(out))
    # No labels or part names anywhere in the exported file.
    assert sum(1 for e in doc.modelspace() if e.dxftype() in ("TEXT", "MTEXT")) == 0
    # All cut lines white (ACI 7); the stock sheet outline yellow (ACI 2).
    assert doc.layers.get("CUT").color == 7
    assert doc.layers.get("SHEET_BOUNDARY").color == 2


def test_export_multi_sheet_sizes(tmp_path):
    """A heterogeneous result exports one boundary per used sheet, each at its
    own size and laid out side by side."""
    A = Sheet("A", 200, 100, margin_mm=0)
    B = Sheet("B", 100, 100, margin_mm=0)
    res = nest([make_rectangle_part("P", 90, 90, quantity=5, allow_rotation=False)],
               [A, B], NestingSettings(part_spacing_mm=0, attempt_count=2, rotation_step_deg=0))
    assert res.total_parts_nested == 5
    out = tmp_path / "multi.dxf"
    rep = export_nesting(res, str(out))   # default options; sizes come from the result
    assert rep.success

    doc = ezdxf.readfile(str(out))
    boundaries = [e for e in doc.modelspace()
                  if e.dxf.layer == "SHEET_BOUNDARY" and e.dxftype() == "LWPOLYLINE"]
    assert len(boundaries) == res.sheet_count_used
    widths = set()
    for e in boundaries:
        xs = [p[0] for p in e.get_points("xy")]
        widths.add(round(max(xs) - min(xs), 1))
    # The chosen mix uses both the 200-wide and 100-wide stock.
    assert 200.0 in widths and 100.0 in widths


def test_common_cut_lines_are_white(tmp_path):
    """Common-line shared edges use the same white colour as ordinary cut lines."""
    sheet = Sheet("S", 300, 200)
    res = nest(
        [make_rectangle_part("A", 50, 40, quantity=2, allow_rotation=False)],
        sheet,
        NestingSettings(attempt_count=1, part_spacing_mm=0, kerf_mm=0, rotation_step_deg=0),
    )
    out = tmp_path / "common_white.dxf"
    rep = export_nesting(res, str(out), sheet, ExportOptions(common_line=True))
    assert rep.success and rep.common_entities >= 1
    doc = ezdxf.readfile(str(out))
    assert doc.layers.get("COMMON_CUT").color == 7  # white, not red
    assert doc.layers.get("CUT").color == 7
