"""Best-nest history (operator-facing log of the highest-utilization nests).

After each successful nest the result is offered to a persistent log that keeps
only the **top results by total utilization** (a "best nests" leaderboard).
Operators can reopen any logged nest to preview and export it. The log is stored
as JSON in the per-user data directory so it survives app restarts.

Each record is self-contained: it embeds the resulting layout *and* a snapshot of
the parts / sheets / settings that produced it, so loading one fully restores
that nest (preview + export + re-run).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import uuid
from dataclasses import dataclass, field

from shapely.geometry import LineString, Polygon

from ..logging_setup import data_dir, get_logger
from .models import NestingResult, Placement, Sheet

log = get_logger("nest_history")

SCHEMA = 1
DEFAULT_CAP = 20            # how many best nests to keep
_FILENAME = "best_nests.json"


# --------------------------------------------------------------------------- #
# Result <-> dict (the layout, with full placed geometry)
# --------------------------------------------------------------------------- #
def _ring(coords) -> list[list[float]]:
    return [[float(x), float(y)] for x, y in coords]


def _placement_to_dict(pl: Placement) -> dict:
    poly = pl.polygon_world
    return {
        "part_id": pl.part_id,
        "part_name": pl.part_name,
        "sheet_index": pl.sheet_index,
        "x_mm": pl.x_mm,
        "y_mm": pl.y_mm,
        "rotation_deg": pl.rotation_deg,
        "mirrored": pl.mirrored,
        "exterior": _ring(poly.exterior.coords),
        "holes": [_ring(r.coords) for r in poly.interiors],
        "internal": [_ring(line.coords) for line in pl.internal_world],
    }


def _placement_from_dict(d: dict) -> Placement:
    poly = Polygon(d["exterior"], d.get("holes", []))
    internal = [LineString(c) for c in d.get("internal", []) if len(c) >= 2]
    return Placement(
        part_id=d.get("part_id", ""),
        part_name=d.get("part_name", ""),
        sheet_index=int(d.get("sheet_index", 0)),
        x_mm=float(d.get("x_mm", 0.0)),
        y_mm=float(d.get("y_mm", 0.0)),
        rotation_deg=float(d.get("rotation_deg", 0.0)),
        mirrored=bool(d.get("mirrored", False)),
        polygon_world=poly,
        internal_world=internal,
    )


def result_to_dict(result: NestingResult) -> dict:
    """Serialise the parts of a NestingResult needed to preview/export it."""
    return {
        "placements": [_placement_to_dict(p) for p in result.placements],
        "sheets": [s.to_dict() for s in result.sheets],
        "sheet": result.sheet.to_dict() if result.sheet else None,
        "sheet_count_used": result.sheet_count_used,
        "utilization_by_sheet": list(result.utilization_by_sheet),
        "total_utilization": result.total_utilization,
        "used_length_by_sheet": list(result.used_length_by_sheet),
        "remnant_length_by_sheet": list(result.remnant_length_by_sheet),
        "runtime_sec": result.runtime_sec,
    }


def result_from_dict(d: dict) -> NestingResult:
    r = NestingResult()
    r.placements = [_placement_from_dict(p) for p in d.get("placements", [])]
    r.sheets = [Sheet.from_dict(s) for s in d.get("sheets", [])]
    sheet = d.get("sheet")
    r.sheet = Sheet.from_dict(sheet) if sheet else (r.sheets[0] if r.sheets else None)
    r.sheet_count_used = int(d.get("sheet_count_used", 0))
    r.utilization_by_sheet = list(d.get("utilization_by_sheet", []))
    r.total_utilization = float(d.get("total_utilization", 0.0))
    r.used_length_by_sheet = list(d.get("used_length_by_sheet", []))
    r.remnant_length_by_sheet = list(d.get("remnant_length_by_sheet", []))
    r.runtime_sec = float(d.get("runtime_sec", 0.0))
    return r


# --------------------------------------------------------------------------- #
# Records + the leaderboard store
# --------------------------------------------------------------------------- #
@dataclass
class NestRecord:
    id: str
    created_at: str                  # ISO timestamp
    label: str                       # one-line human summary
    source_files: list[str]
    parts_placed: int
    parts_requested: int
    sheets_used: int
    total_utilization: float
    payload: dict = field(default_factory=dict)  # {result, parts, sheets, settings}

    @property
    def signature(self) -> tuple:
        """Identifies "the same nest" for de-duplication."""
        srcs = tuple(sorted(os.path.basename(s) for s in self.source_files))
        return (self.parts_requested, self.sheets_used,
                round(self.total_utilization, 4), srcs)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "label": self.label,
            "source_files": list(self.source_files),
            "parts_placed": self.parts_placed,
            "parts_requested": self.parts_requested,
            "sheets_used": self.sheets_used,
            "total_utilization": self.total_utilization,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "NestRecord":
        return cls(
            id=d.get("id", uuid.uuid4().hex[:8]),
            created_at=d.get("created_at", ""),
            label=d.get("label", ""),
            source_files=list(d.get("source_files", [])),
            parts_placed=int(d.get("parts_placed", 0)),
            parts_requested=int(d.get("parts_requested", 0)),
            sheets_used=int(d.get("sheets_used", 0)),
            total_utilization=float(d.get("total_utilization", 0.0)),
            payload=d.get("payload", {}),
        )


def make_record(result: NestingResult, parts, sheets, settings,
                source_files) -> NestRecord:
    """Build a self-contained record from a finished nest and its inputs."""
    requested = sum(int(getattr(p, "quantity", 1)) for p in parts)
    label = (f"{result.total_parts_nested} part(s) -> {result.sheet_count_used} "
             f"sheet(s), {result.total_utilization * 100:.1f}% util")
    return NestRecord(
        id=uuid.uuid4().hex[:8],
        created_at=_dt.datetime.now().isoformat(timespec="seconds"),
        label=label,
        source_files=list(source_files or []),
        parts_placed=result.total_parts_nested,
        parts_requested=requested,
        sheets_used=result.sheet_count_used,
        total_utilization=result.total_utilization,
        payload={
            "result": result_to_dict(result),
            "parts": [p.to_dict() for p in parts],
            "sheets": [s.to_dict() for s in sheets],
            "settings": settings.to_dict(),
        },
    )


class NestHistory:
    """A persistent, capped leaderboard of the best nests by utilization."""

    def __init__(self, path: str, records=None, cap: int = DEFAULT_CAP) -> None:
        self.path = path
        self.records: list[NestRecord] = list(records or [])
        self.cap = cap
        self._reorder()

    @classmethod
    def default_path(cls) -> str:
        # CADN_HISTORY_PATH lets tests (and power users) redirect the log file.
        override = os.environ.get("CADN_HISTORY_PATH")
        return override or os.path.join(str(data_dir()), _FILENAME)

    @classmethod
    def load(cls, path: str | None = None, cap: int = DEFAULT_CAP) -> "NestHistory":
        path = path or cls.default_path()
        records: list[NestRecord] = []
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                records = [NestRecord.from_dict(r) for r in data.get("records", [])]
            except Exception as exc:  # noqa: BLE001 - a bad log must never crash the app
                log.warning("could not read nest history (%s); starting empty", exc)
        return cls(path, records, cap)

    def _reorder(self) -> None:
        # Highest utilization first; newest breaks ties. Keep only the top `cap`.
        self.records.sort(key=lambda r: (-r.total_utilization, r.created_at), reverse=False)
        del self.records[self.cap:]

    def consider(self, record: NestRecord) -> bool:
        """Add a record, keep only the top `cap` by utilization, and persist.

        Returns True if the record made (and remains on) the leaderboard."""
        self.records = [r for r in self.records if r.signature != record.signature]
        self.records.append(record)
        self._reorder()
        self.save()
        return any(r.id == record.id for r in self.records)

    def delete(self, record_id: str) -> None:
        self.records = [r for r in self.records if r.id != record_id]
        self.save()

    def clear(self) -> None:
        self.records = []
        self.save()

    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            data = {"app": "CAD-N", "schema": SCHEMA,
                    "records": [r.to_dict() for r in self.records]}
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            os.replace(tmp, self.path)
        except Exception as exc:  # noqa: BLE001 - persistence is best-effort
            log.warning("could not write nest history: %s", exc)
