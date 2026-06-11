"""DXF importer (doc 7.1, 11.1-11.4).

Reads a DXF, summarises layers/entities, filters to cut layers, flattens every
supported entity to polyline geometry via ``ezdxf.path.make_path`` (one uniform
chord-tolerance knob for LINE/ARC/CIRCLE/LWPOLYLINE/POLYLINE/ELLIPSE/SPLINE),
explodes block INSERTs, ignores annotation entities, then hands the geometry to
the cleaner to reconstruct parts. The golden rule (doc 11.1): *dimensions, text
and leaders never become cut geometry unless the user explicitly includes them.*
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Optional

import ezdxf
from ezdxf import path as ezpath
from ezdxf import recover

from ..config import DEFAULT_TOLERANCES, Tolerances
from ..logging_setup import get_logger
from . import geometry_cleaner as gc
from .models import Notice, Part, Severity
from .units import insunits_to_mm

log = get_logger("dxf_importer")

# Entities we turn into cut geometry.
SUPPORTED = {"LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE"}
# Curves we flatten (also via make_path) but flag so the operator knows.
FLATTEN_WITH_WARNING = {"SPLINE", "ELLIPSE"}
# Pure annotation -- never cut geometry.
ANNOTATION = {
    "TEXT", "MTEXT", "DIMENSION", "LEADER", "MLEADER", "MULTILEADER",
    "ACAD_TABLE", "TABLE", "VIEWPORT", "IMAGE", "WIPEOUT", "ATTDEF",
    "ATTRIB", "POINT", "RAY", "XLINE", "HELIX", "MESH", "SHAPE",
}

CUT_LAYER_HINTS = ("cut", "profile", "outer", "inner", "part", "contour", "geom")
IGNORE_LAYER_HINTS = (
    "dim", "text", "annot", "note", "center", "centre", "construction",
    "constr", "hidden", "title", "border", "frame", "hatch", "label",
)


@dataclass
class LayerInfo:
    name: str
    entity_counts: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.entity_counts.values())

    @property
    def types(self) -> list[str]:
        return sorted(self.entity_counts)

    @property
    def has_cut_candidates(self) -> bool:
        return any(t in SUPPORTED or t in FLATTEN_WITH_WARNING or t == "INSERT"
                   for t in self.entity_counts)


@dataclass
class DxfSummary:
    path: str
    layers: list[LayerInfo] = field(default_factory=list)
    insunits_code: Optional[int] = None
    unit_name: str = "unspecified"
    unit_scale: float = 1.0
    unit_ambiguous: bool = True
    notices: list[Notice] = field(default_factory=list)

    @property
    def total_entities(self) -> int:
        return sum(l.total for l in self.layers)

    def suggested_cut_layers(self) -> set[str]:
        out = set()
        for l in self.layers:
            if not l.has_cut_candidates:
                continue
            name = l.name.lower()
            if any(h in name for h in IGNORE_LAYER_HINTS):
                continue
            out.add(l.name)
        # If nothing matched (e.g. everything on layer "0"), include all layers
        # that actually contain cut candidates.
        if not out:
            out = {l.name for l in self.layers if l.has_cut_candidates}
        return out


@dataclass
class ImportOptions:
    cut_layers: Optional[set[str]] = None   # None -> use summary suggestion
    explode_blocks: bool = True
    group_identical: bool = True
    tolerances: Tolerances = field(default_factory=lambda: DEFAULT_TOLERANCES)


@dataclass
class ImportResult:
    parts: list[Part] = field(default_factory=list)
    notices: list[Notice] = field(default_factory=list)
    summary: Optional[DxfSummary] = None


# --------------------------------------------------------------------------- #
# Opening
# --------------------------------------------------------------------------- #
def open_dxf(path: str) -> tuple[Optional["ezdxf.document.Drawing"], list[Notice]]:
    notices: list[Notice] = []
    try:
        doc = ezdxf.readfile(path)
        return doc, notices
    except Exception as exc:  # noqa: BLE001 - a malformed DXF must never crash the app
        log.warning("readfile failed (%s); trying recover", exc)
        notices.append(
            Notice(
                "The DXF needed recovery; it may be slightly damaged. Verify the result.",
                Severity.WARNING,
                code="DXF_RECOVERED",
                detail=str(exc),
            )
        )
        try:
            doc, auditor = recover.readfile(path)
            if auditor.has_errors:
                notices.append(
                    Notice(
                        f"DXF recovery reported {len(auditor.errors)} structural error(s).",
                        Severity.WARNING,
                        code="DXF_AUDIT_ERRORS",
                        detail="; ".join(str(e) for e in auditor.errors[:5]),
                    )
                )
            return doc, notices
        except Exception as exc2:  # noqa: BLE001 - importer must never crash the app
            notices.append(
                Notice(
                    "The file could not be read as a DXF.",
                    Severity.ERROR,
                    code="DXF_UNREADABLE",
                    detail=str(exc2),
                )
            )
            return None, notices


def summarize(doc, path: str) -> DxfSummary:
    msp = doc.modelspace()
    layers: dict[str, LayerInfo] = {}
    for e in msp:
        li = layers.setdefault(e.dxf.layer, LayerInfo(e.dxf.layer))
        t = e.dxftype()
        li.entity_counts[t] = li.entity_counts.get(t, 0) + 1

    code = doc.header.get("$INSUNITS", None)
    scale, name, ambiguous = insunits_to_mm(code)
    summary = DxfSummary(
        path=path,
        layers=sorted(layers.values(), key=lambda l: l.name),
        insunits_code=code,
        unit_name=name,
        unit_scale=scale,
        unit_ambiguous=ambiguous,
    )
    if ambiguous:
        summary.notices.append(
            Notice(
                "Drawing units are not specified; assuming millimetres. "
                "Check the imported sizes are sensible.",
                Severity.WARNING,
                code="UNITS_AMBIGUOUS",
            )
        )
    elif scale != 1.0:
        summary.notices.append(
            Notice(
                f"Drawing units are {name}; scaling to millimetres (x{scale:g}).",
                Severity.INFO,
                code="UNITS_SCALED",
            )
        )
    return summary


# --------------------------------------------------------------------------- #
# Geometry extraction
# --------------------------------------------------------------------------- #
def _iter_cut_entities(msp_entities, cut_layers, explode_blocks, insert_layer=None,
                       depth=0):
    """Yield (entity, effective_layer) for cut-candidate entities, recursing
    into INSERTs (block references) up to a sane depth."""
    for e in msp_entities:
        layer = e.dxf.layer
        # Entities on layer "0" inside a block inherit the INSERT's layer.
        eff_layer = insert_layer if (layer == "0" and insert_layer) else layer
        t = e.dxftype()
        if t == "INSERT":
            if not explode_blocks or depth > 6:
                yield ("__INSERT_SKIPPED__", eff_layer)
                continue
            try:
                yield from _iter_cut_entities(
                    e.virtual_entities(), cut_layers, explode_blocks,
                    insert_layer=eff_layer, depth=depth + 1,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("INSERT explode failed: %s", exc)
                yield ("__INSERT_FAILED__", eff_layer)
            continue
        if cut_layers is not None and eff_layer not in cut_layers:
            continue
        yield (e, eff_layer)


def _entity_is_closed(e) -> bool:
    """Honour an entity's own 'closed' flag even when make_path flattens it open
    (e.g. a SPLINE marked closed, which ezdxf may model as an open fit curve)."""
    t = e.dxftype()
    try:
        if t == "CIRCLE":
            return True
        if t == "ELLIPSE":
            return abs(abs(e.dxf.end_param - e.dxf.start_param) - 2 * math.pi) < 1e-6
        if t == "LWPOLYLINE":
            return bool(e.closed)
        if t == "POLYLINE":
            return bool(e.is_closed)
        if t == "SPLINE":
            return bool(getattr(e, "closed", False))
    except Exception:  # noqa: BLE001
        return False
    return False


def _flatten_entity(e, sagitta_drawing_units, unit_scale):
    """Return (closed_ring_or_None, open_segments_list)."""
    p = ezpath.make_path(e)
    pts = [(v.x * unit_scale, v.y * unit_scale) for v in p.flattening(sagitta_drawing_units)]
    if len(pts) < 2:
        return None, []
    closed = (
        p.start.isclose(p.end)
        or math.dist(pts[0], pts[-1]) <= 1e-6
        or _entity_is_closed(e)
    )
    if closed:
        if pts[0] == pts[-1]:
            pts = pts[:-1]
        if len(pts) >= 3:
            return pts, []
        return None, []
    segs = [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    return None, segs


def extract(doc, path: str, options: ImportOptions, summary: Optional[DxfSummary] = None
            ) -> ImportResult:
    summary = summary or summarize(doc, path)
    tol = options.tolerances
    result = ImportResult(summary=summary)
    result.notices.extend(summary.notices)

    cut_layers = options.cut_layers
    if cut_layers is None:
        cut_layers = summary.suggested_cut_layers()
        result.notices.append(
            Notice(
                f"Auto-selected cut layer(s): {', '.join(sorted(cut_layers)) or '(none)'}.",
                Severity.INFO,
                code="AUTO_CUT_LAYERS",
            )
        )

    sagitta = max(tol.curve_chord_tolerance_mm / max(summary.unit_scale, 1e-9), 1e-6)

    closed_rings: list[list[tuple[float, float]]] = []
    open_segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    ignored_by_layer: dict[str, int] = {}
    flattened_curves = 0
    blocks_exploded = False
    blocks_skipped = 0
    hatch_skipped = 0
    unsupported: dict[str, int] = {}

    for e, layer in _iter_cut_entities(
        doc.modelspace(), cut_layers, options.explode_blocks
    ):
        if e == "__INSERT_SKIPPED__":
            blocks_skipped += 1
            continue
        if e == "__INSERT_FAILED__":
            unsupported["INSERT"] = unsupported.get("INSERT", 0) + 1
            continue
        t = e.dxftype()
        if t in ANNOTATION:
            ignored_by_layer[layer] = ignored_by_layer.get(layer, 0) + 1
            continue
        if t == "HATCH":
            hatch_skipped += 1
            continue
        if t in SUPPORTED or t in FLATTEN_WITH_WARNING:
            try:
                ring, segs = _flatten_entity(e, sagitta, summary.unit_scale)
            except Exception as exc:  # noqa: BLE001
                log.warning("flatten failed for %s: %s", t, exc)
                unsupported[t] = unsupported.get(t, 0) + 1
                continue
            if ring is not None:
                closed_rings.append(ring)
            open_segments.extend(segs)
            if t in FLATTEN_WITH_WARNING:
                flattened_curves += 1
            continue
        unsupported[t] = unsupported.get(t, 0) + 1

    # Track whether any INSERT was actually exploded.
    if options.explode_blocks:
        for li in summary.layers:
            if "INSERT" in li.entity_counts:
                blocks_exploded = True
                break

    # Notices about what was ignored / handled.
    total_ignored = sum(ignored_by_layer.values())
    if total_ignored:
        top = sorted(ignored_by_layer.items(), key=lambda kv: -kv[1])[:3]
        detail = ", ".join(f"{n} on '{lyr}'" for lyr, n in top)
        result.notices.append(
            Notice(
                f"{total_ignored} annotation entity(ies) (text/dimension/leader) ignored ({detail}).",
                Severity.INFO,
                code="ANNOTATION_IGNORED",
            )
        )
    if flattened_curves:
        result.notices.append(
            Notice(
                f"{flattened_curves} spline/ellipse curve(s) flattened to polylines "
                f"(chord tolerance {tol.curve_chord_tolerance_mm:g} mm).",
                Severity.INFO,
                code="CURVES_FLATTENED",
            )
        )
    if blocks_exploded:
        result.notices.append(
            Notice(
                "Block references (INSERT) were exploded into their geometry.",
                Severity.INFO,
                code="BLOCKS_EXPLODED",
            )
        )
    if blocks_skipped:
        result.notices.append(
            Notice(
                f"{blocks_skipped} block reference(s) skipped (block explode disabled).",
                Severity.WARNING,
                code="BLOCKS_SKIPPED",
            )
        )
    if hatch_skipped:
        result.notices.append(
            Notice(
                f"{hatch_skipped} HATCH entity(ies) ignored (fills are not cut geometry).",
                Severity.INFO,
                code="HATCH_IGNORED",
            )
        )
    for t, n in unsupported.items():
        result.notices.append(
            Notice(
                f"{n} unsupported '{t}' entity(ies) skipped.",
                Severity.WARNING,
                code="UNSUPPORTED_ENTITY",
            )
        )

    # Reconstruct parts from geometry.
    clean = gc.build_polygons(closed_rings, open_segments, tol)
    result.notices.extend(clean.notices)

    if not clean.polygons:
        result.notices.append(
            Notice(
                "No closed cut contours were found. Check that the right layers are "
                "selected and that part outlines are closed.",
                Severity.WARNING,
                code="NO_PARTS",
            )
        )

    stem = os.path.splitext(os.path.basename(path))[0]
    parts = _polygons_to_parts(clean.polygons, stem, path, options.group_identical)
    result.parts = parts
    if parts:
        result.notices.append(
            Notice(
                f"Detected {len(parts)} distinct part(s), "
                f"{sum(p.quantity for p in parts)} instance(s) total.",
                Severity.INFO,
                code="PARTS_DETECTED",
            )
        )
    return result


# --------------------------------------------------------------------------- #
# Parts assembly + identical-part grouping
# --------------------------------------------------------------------------- #
def _shape_signature(poly, q: float = 0.1) -> tuple:
    def r(v: float) -> float:
        return round(v / q) * q

    ext = list(poly.exterior.coords)[:-1]
    edges = tuple(
        sorted(r(math.dist(ext[i], ext[(i + 1) % len(ext)])) for i in range(len(ext)))
    )
    return (len(ext), len(poly.interiors), r(poly.area), r(poly.length), edges)


def _polygons_to_parts(polygons, stem, path, group_identical) -> list[Part]:
    if not polygons:
        return []
    if not group_identical:
        return [
            Part(name=f"{stem}-P{idx + 1:02d}", geom=poly, source_file=path,
                 allowed_rotations=None)
            for idx, poly in enumerate(polygons)
        ]

    groups: dict[tuple, list] = {}
    order: list[tuple] = []
    for poly in polygons:
        sig = _shape_signature(poly)
        if sig not in groups:
            groups[sig] = []
            order.append(sig)
        groups[sig].append(poly)

    parts: list[Part] = []
    for idx, sig in enumerate(order):
        polys = groups[sig]
        parts.append(
            Part(
                name=f"{stem}-P{idx + 1:02d}",
                geom=polys[0],
                quantity=len(polys),
                source_file=path,
                allowed_rotations=None,
            )
        )
    return parts


def import_dxf(path: str, options: Optional[ImportOptions] = None) -> ImportResult:
    """High-level convenience: open + summarise + extract in one call."""
    options = options or ImportOptions()
    doc, notices = open_dxf(path)
    if doc is None:
        return ImportResult(notices=notices)
    try:
        summary = summarize(doc, path)
        res = extract(doc, path, options, summary)
    except Exception as exc:  # noqa: BLE001 - final safety net; report, never crash
        log.exception("import failed for %s", path)
        return ImportResult(
            notices=notices
            + [Notice("The DXF could not be processed.", Severity.ERROR,
                      code="IMPORT_FAILED", detail=f"{type(exc).__name__}: {exc}")]
        )
    res.notices = notices + res.notices
    return res
