"""Reporting and summary calculations (doc 13)."""

from __future__ import annotations

import csv
import datetime as _dt
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from .models import NestingResult, NestingSettings, Part, Sheet


@dataclass
class PartReportRow:
    name: str
    source: str
    qty_requested: int
    qty_nested: int
    qty_failed: int
    area_each: float
    rotations_used: str


@dataclass
class JobReport:
    job_name: str
    timestamp: str
    material: str
    thickness: str
    sheet_size: str
    sheets_used: int
    parts_nested: int
    parts_failed: int
    total_part_area: float
    total_sheet_area: float
    total_utilization: float
    scrap_area: float
    remnant_lengths: list[float]
    export_path: str
    parts: list[PartReportRow] = field(default_factory=list)

    def as_summary_lines(self) -> list[tuple[str, str]]:
        return [
            ("Job", self.job_name),
            ("Date/time", self.timestamp),
            ("Material", self.material or "-"),
            ("Thickness", self.thickness or "-"),
            ("Sheet size", self.sheet_size),
            ("Sheets used", str(self.sheets_used)),
            ("Parts nested", str(self.parts_nested)),
            ("Parts not nested", str(self.parts_failed)),
            ("Total part area (mm^2)", f"{self.total_part_area:.1f}"),
            ("Sheet area used (mm^2)", f"{self.total_sheet_area:.1f}"),
            ("Utilization", f"{self.total_utilization * 100:.1f}%"),
            ("Scrap area (mm^2)", f"{self.scrap_area:.1f}"),
            ("Remnant length / sheet (mm)",
             ", ".join(f"{r:.1f}" for r in self.remnant_lengths) or "-"),
            ("Export file", self.export_path or "-"),
        ]


def _sheet_size_label(result: NestingResult, sheet: Sheet) -> str:
    """Human-readable stock description: a single size, or the realised mix."""
    sheets = result.sheets or ([sheet] if sheet else [])
    if not sheets:
        return "-"
    counts: dict[tuple, int] = {}
    order: list[Sheet] = []
    for s in sheets:
        k = (s.width_mm, s.height_mm, s.margin_mm)
        if k not in counts:
            counts[k] = 0
            order.append(s)
        counts[k] += 1
    multi = len(order) > 1
    segs = []
    for s in order:
        seg = f"{s.width_mm:g} x {s.height_mm:g} mm (margin {s.margin_mm:g})"
        segs.append(f"{counts[(s.width_mm, s.height_mm, s.margin_mm)]} x [{seg}]"
                    if multi else seg)
    return "; ".join(segs)


def build_report(
    result: NestingResult,
    parts: list[Part],
    sheet: Sheet,
    settings: Optional[NestingSettings] = None,
    job_name: str = "Untitled",
    export_path: str = "",
) -> JobReport:
    nested_by_part: dict[str, int] = defaultdict(int)
    rot_by_part: dict[str, set] = defaultdict(set)
    for pl in result.placements:
        nested_by_part[pl.part_id] += 1
        rot_by_part[pl.part_id].add(round(pl.rotation_deg, 1))

    rows: list[PartReportRow] = []
    total_part_area = 0.0
    for p in parts:
        nested = nested_by_part.get(p.id, 0)
        total_part_area += p.area * nested
        rows.append(
            PartReportRow(
                name=p.name,
                source=p.source_file or "(manual)",
                qty_requested=p.quantity,
                qty_nested=nested,
                qty_failed=max(0, p.quantity - nested),
                area_each=p.area,
                rotations_used=", ".join(f"{r:g}" for r in sorted(rot_by_part.get(p.id, {0.0}))),
            )
        )

    sheets_used = result.sheet_count_used
    total_sheet_area = (sum(s.usable_area for s in result.sheets)
                        if result.sheets else sheet.usable_area * sheets_used)
    scrap = max(0.0, total_sheet_area - total_part_area)
    material = next((p.material for p in parts if p.material), "") or (sheet.material or "")
    thickness = next((str(p.thickness) for p in parts if p.thickness), "") or (
        str(sheet.thickness) if sheet.thickness else "")

    return JobReport(
        job_name=job_name,
        timestamp=_dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        material=material,
        thickness=thickness,
        sheet_size=_sheet_size_label(result, sheet),
        sheets_used=sheets_used,
        parts_nested=result.total_parts_nested,
        parts_failed=result.total_parts_failed,
        total_part_area=total_part_area,
        total_sheet_area=total_sheet_area,
        total_utilization=result.total_utilization,
        scrap_area=scrap,
        remnant_lengths=list(result.remnant_length_by_sheet),
        export_path=export_path,
        parts=rows,
    )


def write_csv_report(report: JobReport, path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["CAD-N job report"])
        for key, val in report.as_summary_lines():
            w.writerow([key, val])
        w.writerow([])
        w.writerow(["Part", "Source", "Qty requested", "Qty nested", "Qty failed",
                    "Area each (mm^2)", "Rotations used (deg)"])
        for r in report.parts:
            w.writerow([r.name, r.source, r.qty_requested, r.qty_nested, r.qty_failed,
                        f"{r.area_each:.2f}", r.rotations_used])
