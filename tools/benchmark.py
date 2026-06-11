"""Benchmark harness (doc 14: testing strategy / 17.3 optimization risk).

Runs the full pipeline (import -> nest -> export -> reopen) over every DXF in
tests/fixtures and tests/real_dxf, adapting the sheet size per file, and reports
parts detected, warnings, utilization, sheet count and runtimes. Every file is
wrapped so one bad input can never abort the run -- surviving a corpus of real
internet DXFs without crashing is part of what we are measuring.

Run:  python tools/benchmark.py
"""

from __future__ import annotations

import csv
import math
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cad_n.core import dxf_exporter as dxe  # noqa: E402
from cad_n.core import dxf_importer as imp  # noqa: E402
from cad_n.core.models import NestingSettings, Sheet  # noqa: E402
from cad_n.core.nesting_engine import nest  # noqa: E402

OUT = ROOT / "benchmarks_out"
DIRS = [ROOT / "tests" / "fixtures", ROOT / "tests" / "real_dxf"]


def adaptive_sheet(parts) -> Sheet:
    maxw = max((p.width for p in parts), default=10.0)
    maxh = max((p.height for p in parts), default=10.0)
    total = sum(p.area * p.quantity for p in parts) or 1.0
    side = max(maxw * 1.2, maxh * 1.2, math.sqrt(total * 2.0))
    side = min(side, 50_000.0)
    return Sheet("Bench", round(side, 1), round(side, 1), margin_mm=2.0)


def run_one(path: Path) -> dict:
    row = {"file": path.name, "parts": 0, "instances": 0, "warns": 0,
           "import_ms": 0.0, "nest_ms": 0.0, "placed": 0, "failed": 0,
           "sheets": 0, "util_%": 0.0, "reopen": "-", "status": "ok", "note": ""}
    try:
        t0 = time.perf_counter()
        res = imp.import_dxf(str(path))
        row["import_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        row["parts"] = len(res.parts)
        row["instances"] = sum(p.quantity for p in res.parts)
        row["warns"] = sum(1 for n in res.notices if n.severity.value != "info")
        codes = sorted({n.code for n in res.notices if n.severity.value == "warning"})
        row["note"] = ",".join(codes)[:60]
        if not res.parts:
            row["status"] = "no-parts"
            return row

        sheet = adaptive_sheet(res.parts)
        settings = NestingSettings(part_spacing_mm=2.0, attempt_count=3, time_limit_sec=8.0)
        t1 = time.perf_counter()
        nres = nest(res.parts, sheet, settings)
        row["nest_ms"] = round((time.perf_counter() - t1) * 1000, 1)
        row["placed"] = nres.total_parts_nested
        row["failed"] = nres.total_parts_failed
        row["sheets"] = nres.sheet_count_used
        row["util_%"] = round(nres.total_utilization * 100, 1)

        OUT.mkdir(parents=True, exist_ok=True)
        outdxf = OUT / f"{path.stem}__nested.dxf"
        rep = dxe.export_nesting(nres, str(outdxf), sheet,
                                 dxe.ExportOptions(include_labels=False))
        if rep.success:
            import ezdxf
            ezdxf.readfile(str(outdxf))  # prove it reopens
            row["reopen"] = "ok"
        else:
            row["reopen"] = "blocked"
    except Exception as exc:  # noqa: BLE001
        row["status"] = "ERROR"
        row["note"] = f"{type(exc).__name__}: {exc}"[:80]
        traceback.print_exc()
    return row


def main() -> int:
    files = []
    for d in DIRS:
        if d.exists():
            files.extend(sorted(d.glob("*.dxf")))
    if not files:
        print("No DXF files found. Run tools/make_fixtures.py / fetch_real_dxf.py first.")
        return 1

    rows = [run_one(f) for f in files]

    cols = ["file", "parts", "instances", "placed", "failed", "sheets", "util_%",
            "warns", "import_ms", "nest_ms", "reopen", "status", "note"]
    widths = {c: max(len(c), max(len(str(r[c])) for r in rows)) for c in cols}
    line = "  ".join(c.ljust(widths[c]) for c in cols)
    print("\n" + line)
    print("-" * len(line))
    for r in rows:
        print("  ".join(str(r[c]).ljust(widths[c]) for c in cols))

    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "benchmark.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    errors = [r for r in rows if r["status"] == "ERROR"]
    print(f"\n{len(rows)} files | errors: {len(errors)} | "
          f"reopened ok: {sum(1 for r in rows if r['reopen'] == 'ok')}")
    print(f"CSV: {OUT / 'benchmark.csv'}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
