"""Tests for reporting and job save/load."""

import math

import pytest

from cad_n.core.job_io import load_job, save_job
from cad_n.core.models import NestingSettings, Part, Sheet, make_rectangle_part
from cad_n.core.nesting_engine import nest
from cad_n.core.reports import build_report, write_csv_report


def test_build_report_counts():
    sheet = Sheet("S", 200, 200)
    settings = NestingSettings(attempt_count=1, part_spacing_mm=0)
    parts = [make_rectangle_part("A", 50, 50, quantity=2),
             make_rectangle_part("B", 30, 30, quantity=1)]
    res = nest(parts, sheet, settings)
    rep = build_report(res, parts, sheet, settings, job_name="JobX")
    assert rep.job_name == "JobX"
    assert rep.parts_nested == 3
    by_name = {r.name: r for r in rep.parts}
    assert by_name["A"].qty_requested == 2
    assert by_name["A"].qty_nested == 2
    assert by_name["B"].qty_nested == 1
    assert rep.total_utilization > 0


def test_write_csv_report(tmp_path):
    sheet = Sheet("S", 200, 200)
    parts = [make_rectangle_part("A", 50, 50, quantity=2)]
    res = nest(parts, sheet, NestingSettings(attempt_count=1))
    rep = build_report(res, parts, sheet, job_name="CSVJob", export_path="x.dxf")
    out = tmp_path / "r.csv"
    write_csv_report(rep, str(out))
    text = out.read_text(encoding="utf-8")
    assert "CAD-N job report" in text
    assert "Utilization" in text
    assert "A" in text


def test_job_roundtrip(tmp_path):
    sheet = Sheet("Big", 2500, 1250, margin_mm=10, material="MS", thickness=2.0)
    settings = NestingSettings(part_spacing_mm=3, kerf_mm=0.2, attempt_count=6,
                               rotation_step_deg=45)
    parts = [
        make_rectangle_part("A", 100, 60, quantity=4),
        Part.from_rings("ring", outer=[(0, 0), (80, 0), (80, 80), (0, 80)],
                        holes=[[(30, 30), (50, 30), (50, 50), (30, 50)]], quantity=2),
    ]
    path = tmp_path / "job.svnest.json"
    save_job(str(path), "MyJob", parts, sheet, settings,
             source_files=[str(tmp_path / "orig.dxf")])

    job = load_job(str(path))
    assert job.job_name == "MyJob"
    assert len(job.parts) == 2
    assert job.sheet.width_mm == 2500 and job.sheet.margin_mm == 10
    assert math.isclose(job.settings.kerf_mm, 0.2)
    assert job.settings.attempt_count == 6
    # geometry preserved (areas match within tolerance)
    areas_in = sorted(p.area for p in parts)
    areas_out = sorted(p.area for p in job.parts)
    for a, b in zip(areas_in, areas_out):
        assert math.isclose(a, b, rel_tol=1e-6)
    # hole preserved
    assert any(len(p.holes) == 1 for p in job.parts)


def test_job_self_contained_when_source_missing(tmp_path):
    sheet = Sheet("S", 1000, 500)
    parts = [make_rectangle_part("A", 50, 50)]
    path = tmp_path / "j.json"
    save_job(str(path), "J", parts, sheet, NestingSettings(),
             source_files=["Z:/does/not/exist.dxf"])
    job = load_job(str(path))
    # Geometry still loads even though the source file is gone.
    assert len(job.parts) == 1
    assert any(n.code == "JOB_SOURCES_MISSING" for n in job.notices)
