"""Job save/load (doc 7.7).

Jobs are stored as JSON and are *self-contained*: each part's geometry is
embedded, so a job still loads after the original DXFs are moved or deleted.
Source paths are kept for reference and relinking, stored both absolute and
relative to the job file ("Operators move folders. Software should not sulk.")."""

from __future__ import annotations

import datetime as _dt
import json
import os
from dataclasses import dataclass, field
from typing import Optional

from .. import __version__
from .models import NestingSettings, Notice, Part, Severity, Sheet

SCHEMA = 1


@dataclass
class JobData:
    job_name: str = "Untitled"
    parts: list[Part] = field(default_factory=list)
    sheet: Sheet = field(default_factory=lambda: Sheet("Sheet", 2500, 1250))
    sheets: list[Sheet] = field(default_factory=list)
    settings: NestingSettings = field(default_factory=NestingSettings)
    source_files: list[str] = field(default_factory=list)
    last_result: Optional[dict] = None
    notices: list[Notice] = field(default_factory=list)


def save_job(
    path: str,
    job_name: str,
    parts: list[Part],
    sheet,                       # Sheet or list[Sheet] (stock sizes)
    settings: NestingSettings,
    source_files: Optional[list[str]] = None,
    last_result: Optional[dict] = None,
) -> None:
    job_dir = os.path.dirname(os.path.abspath(path))
    sources = []
    for sf in source_files or []:
        ap = os.path.abspath(sf)
        try:
            rel = os.path.relpath(ap, job_dir)
        except ValueError:
            rel = ""
        sources.append({"abs": ap, "rel": rel})

    sheets = [sheet] if isinstance(sheet, Sheet) else list(sheet)
    data = {
        "app": "CAD-N",
        "version": __version__,
        "schema": SCHEMA,
        "saved_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "job_name": job_name,
        "parts": [p.to_dict() for p in parts],
        "source_files": sources,
        "sheet": sheets[0].to_dict() if sheets else None,  # first, for older readers
        "sheets": [s.to_dict() for s in sheets],
        "settings": settings.to_dict(),
        "last_result": last_result,
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)  # atomic-ish write


def load_job(path: str) -> JobData:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    job = JobData(job_name=data.get("job_name", "Untitled"))
    schema = data.get("schema", 1)
    if schema > SCHEMA:
        job.notices.append(
            Notice(
                f"This job was saved by a newer version (schema {schema}); "
                "some settings may be ignored.",
                Severity.WARNING, code="JOB_NEWER_SCHEMA",
            )
        )

    try:
        job.parts = [Part.from_dict(d) for d in data.get("parts", [])]
    except (KeyError, TypeError, ValueError) as exc:
        job.notices.append(
            Notice("Some parts in the job file were unreadable and were skipped.",
                   Severity.WARNING, code="JOB_PART_ERROR", detail=str(exc))
        )

    raw_sheets = data.get("sheets")
    if raw_sheets:
        job.sheets = [Sheet.from_dict(d) for d in raw_sheets]
    else:
        job.sheets = [Sheet.from_dict(data.get("sheet", {"width_mm": 2500, "height_mm": 1250}))]
    job.sheet = job.sheets[0]
    job.settings = NestingSettings.from_dict(data.get("settings"))
    job.last_result = data.get("last_result")

    # Relink check: prefer absolute, fall back to path relative to the job file.
    job_dir = os.path.dirname(os.path.abspath(path))
    missing = []
    for src in data.get("source_files", []):
        ap = src.get("abs", "")
        rel = src.get("rel", "")
        if ap and os.path.exists(ap):
            job.source_files.append(ap)
        elif rel and os.path.exists(os.path.join(job_dir, rel)):
            job.source_files.append(os.path.normpath(os.path.join(job_dir, rel)))
        elif ap or rel:
            missing.append(ap or rel)
    if missing:
        job.notices.append(
            Notice(
                f"{len(missing)} source DXF file(s) could not be found. Part geometry "
                "is preserved in the job; relink only if you need to re-import.",
                Severity.INFO, code="JOB_SOURCES_MISSING",
                detail="; ".join(missing[:5]),
            )
        )
    return job
