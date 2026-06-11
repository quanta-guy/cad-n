"""Clean nested DXF export (doc 11.5).

Layers: ``SHEET_BOUNDARY`` (sheet rectangles), ``CUT`` (part outlines + holes),
``LABELS`` (optional text), ``COMMON_CUT`` (shared edges, common-line mode).
Sheets are laid out in a row in modelspace with a gap. A validation gate runs
first: if placements overlap or leave the sheet, the exporter refuses to write
rather than emit wrong cut geometry (doc rule: *never silently output wrong DXF
geometry*).

Common-line cutting (opt-in via :attr:`ExportOptions.common_line`) merges the
coincident edges of butting parts into a single cut: adjacent parts are dissolved
so each shared edge is emitted once on the ``COMMON_CUT`` layer, and the outer
perimeter is emitted once on ``CUT``. This changes the actual cut topology, so it
is off by default and the shared edges are kept on their own layer for the
operator to verify cut order / lead-ins before cutting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import ezdxf
from shapely import set_precision
from shapely.affinity import translate
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import linemerge, unary_union

from ..logging_setup import get_logger
from .models import NestingResult, Notice, Severity, Sheet

log = get_logger("dxf_exporter")

LAYER_SHEET = "SHEET_BOUNDARY"
LAYER_CUT = "CUT"
LAYER_LABELS = "LABELS"
LAYER_COMMON = "COMMON_CUT"


@dataclass
class ExportOptions:
    include_sheet_boundary: bool = True
    # Text labels (sheet id + part names) are off for export: a clean cutting DXF
    # carries cut geometry only. The on-screen preview still shows part numbers.
    include_labels: bool = False
    sheet_gap_mm: float = 50.0
    label_height_mm: float = 8.0
    # Common-line cutting: dissolve butting parts so shared edges are cut once.
    common_line: bool = False
    # Grid (mm) coincident edges are snapped to before merging. Coarse enough to
    # absorb float noise, fine enough not to distort sheet-metal geometry.
    common_snap_mm: float = 0.01


@dataclass
class ExportReport:
    success: bool = False
    path: str = ""
    sheets_written: int = 0
    cut_entities: int = 0
    common_entities: int = 0
    notices: list[Notice] = field(default_factory=list)


def validate_result(result: NestingResult, sheet: Sheet) -> list[Notice]:
    """Safety net before export. Returns notices; ERROR severity blocks export."""
    notices: list[Notice] = []
    tol = 1e-2

    by_sheet: dict[int, list] = {}
    for pl in result.placements:
        if pl.polygon_world.is_empty:
            notices.append(Notice("A placement has empty geometry.", Severity.ERROR,
                                  code="EXPORT_EMPTY"))
            continue
        by_sheet.setdefault(pl.sheet_index, []).append(pl)

    for s_i, pls in by_sheet.items():
        # Each physical sheet is validated against its own stock size.
        minx, miny, maxx, maxy = (result.sheet_at(s_i) or sheet).usable_rect()
        for pl in pls:
            bx0, by0, bx1, by1 = pl.polygon_world.bounds
            if bx0 < minx - tol or by0 < miny - tol or bx1 > maxx + tol or by1 > maxy + tol:
                notices.append(
                    Notice(f"Part '{pl.part_name}' lies outside the sheet; export blocked.",
                           Severity.ERROR, code="EXPORT_OUT_OF_BOUNDS", part_name=pl.part_name)
                )
        for i in range(len(pls)):
            for j in range(i + 1, len(pls)):
                inter = pls[i].polygon_world.intersection(pls[j].polygon_world)
                if not inter.is_empty and inter.area > 1e-3:
                    notices.append(
                        Notice(
                            f"Parts '{pls[i].part_name}' and '{pls[j].part_name}' overlap "
                            f"on sheet {s_i + 1}; export blocked.",
                            Severity.ERROR, code="EXPORT_OVERLAP",
                        )
                    )
    return notices


def _add_layers(doc) -> None:
    specs = [
        (LAYER_SHEET, 2),   # yellow (stock sheet outline)
        (LAYER_CUT, 7),     # white (all part cut lines)
        (LAYER_LABELS, 2),  # yellow (only emitted when include_labels is enabled)
        (LAYER_COMMON, 7),  # white (common-line shared edges; same colour as CUT)
    ]
    for name, color in specs:
        if name not in doc.layers:
            doc.layers.add(name, color=color)


def _ring_points(ring) -> list[tuple[float, float]]:
    pts = [(float(x), float(y)) for x, y in ring.coords]
    return pts


def _iter_polygons(geom):
    """Yield Polygon parts from a Polygon / MultiPolygon / collection."""
    if geom is None or geom.is_empty:
        return
    if isinstance(geom, Polygon):
        yield geom
    elif isinstance(geom, MultiPolygon):
        yield from geom.geoms
    elif hasattr(geom, "geoms"):
        for g in geom.geoms:
            yield from _iter_polygons(g)


def _iter_lines(geom):
    """Yield LineString parts from a (Multi)LineString / collection."""
    if geom is None or geom.is_empty:
        return
    if geom.geom_type == "LineString":
        yield geom
    elif hasattr(geom, "geoms"):
        for g in geom.geoms:
            yield from _iter_lines(g)


def _emit_common_line(msp, placements, ox: float, snap: float) -> tuple[int, int]:
    """Emit one sheet's cut linework with butting parts' shared edges merged.

    The outer perimeter (each external edge + every hole) goes on ``CUT``; the
    internal edges shared by adjacent parts go once on ``COMMON_CUT``. Returns
    ``(cut_entities, common_entities)``.
    """
    polys: list[Polygon] = []
    for pl in placements:
        g = pl.polygon_world
        if g.is_empty:
            continue
        if ox:
            g = translate(g, xoff=ox)
        g = set_precision(g, snap)
        if not g.is_empty:
            polys.append(g)
    if not polys:
        return 0, 0

    # Dissolve touching parts: union.boundary is the perimeter cut once each.
    union = unary_union(polys)
    perimeter = union.boundary

    cut_n = 0
    for poly in _iter_polygons(union):
        msp.add_lwpolyline(_ring_points(poly.exterior), close=True,
                           dxfattribs={"layer": LAYER_CUT})
        cut_n += 1
        for interior in poly.interiors:
            msp.add_lwpolyline(_ring_points(interior), close=True,
                               dxfattribs={"layer": LAYER_CUT})
            cut_n += 1

    # Shared edges = all part boundaries, noded, minus the outer perimeter.
    all_boundary = unary_union([p.boundary for p in polys])
    common = all_boundary.difference(perimeter)
    # linemerge stitches collinear fragments into long polylines (fewer entities);
    # it only accepts multi-part input, so skip it for a lone LineString.
    if not common.is_empty and common.geom_type != "LineString":
        common = linemerge(common)

    common_n = 0
    for ls in _iter_lines(common):
        pts = [(float(x), float(y)) for x, y in ls.coords]
        if len(pts) >= 2:
            msp.add_lwpolyline(pts, close=bool(ls.is_ring),
                               dxfattribs={"layer": LAYER_COMMON})
            common_n += 1
    return cut_n, common_n


def export_nesting(
    result: NestingResult,
    path: str,
    sheet: Optional[Sheet] = None,
    options: Optional[ExportOptions] = None,
) -> ExportReport:
    options = options or ExportOptions()
    sheet = sheet or result.sheet
    report = ExportReport(path=path)
    if sheet is None:
        report.notices.append(Notice("No sheet to export.", Severity.ERROR, code="EXPORT_NO_SHEET"))
        return report

    # Validation gate.
    val = validate_result(result, sheet)
    report.notices.extend(val)
    if any(n.severity is Severity.ERROR for n in val):
        report.notices.append(
            Notice("Export aborted: geometry failed validation.", Severity.ERROR,
                   code="EXPORT_ABORTED")
        )
        return report

    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4  # mm
    _add_layers(doc)
    msp = doc.modelspace()

    gap = options.sheet_gap_mm
    n_sheets = max(result.sheet_count_used, 0)
    cut_entities = 0
    common_entities = 0

    ox = 0.0  # cumulative X offset; sheets may differ in width.
    for s_i in range(n_sheets):
        sh = result.sheet_at(s_i) or sheet
        sheet_pls = result.placements_on(s_i)
        if options.include_sheet_boundary:
            msp.add_lwpolyline(
                [(ox, 0), (ox + sh.width_mm, 0),
                 (ox + sh.width_mm, sh.height_mm), (ox, sh.height_mm)],
                close=True,
                dxfattribs={"layer": LAYER_SHEET},
            )
        if options.include_labels:
            util = (result.utilization_by_sheet[s_i] * 100
                    if s_i < len(result.utilization_by_sheet) else 0.0)
            txt = msp.add_text(
                f"Sheet {s_i + 1}  util {util:.1f}%",
                dxfattribs={"layer": LAYER_LABELS, "height": options.label_height_mm},
            )
            txt.set_placement((ox, sh.height_mm + options.label_height_mm))

        if options.common_line:
            c_n, cm_n = _emit_common_line(msp, sheet_pls, ox, options.common_snap_mm)
            cut_entities += c_n
            common_entities += cm_n
        else:
            for pl in sheet_pls:
                poly = pl.polygon_world
                ext = [(x + ox, y) for x, y in _ring_points(poly.exterior)]
                msp.add_lwpolyline(ext, close=True, dxfattribs={"layer": LAYER_CUT})
                cut_entities += 1
                for interior in poly.interiors:
                    hole = [(x + ox, y) for x, y in _ring_points(interior)]
                    msp.add_lwpolyline(hole, close=True, dxfattribs={"layer": LAYER_CUT})
                    cut_entities += 1

        if options.include_labels:
            for pl in sheet_pls:
                c = pl.polygon_world.representative_point()
                t = msp.add_text(
                    pl.part_name,
                    dxfattribs={"layer": LAYER_LABELS,
                                "height": options.label_height_mm * 0.6},
                )
                t.set_placement((c.x + ox, c.y))

        ox += sh.width_mm + gap

    try:
        doc.saveas(path)
    except OSError as exc:
        report.notices.append(
            Notice(f"Could not write the DXF file: {exc}", Severity.ERROR, code="EXPORT_IO")
        )
        return report

    report.success = True
    report.sheets_written = n_sheets
    report.cut_entities = cut_entities
    report.common_entities = common_entities
    report.notices.append(
        Notice(f"Exported {cut_entities} cut profile(s) across {n_sheets} sheet(s).",
               Severity.INFO, code="EXPORT_OK")
    )
    if options.common_line:
        if common_entities:
            report.notices.append(
                Notice(
                    f"Common-line cutting merged {common_entities} shared edge(s) onto "
                    f"the COMMON_CUT layer. Verify cut order and lead-ins before "
                    f"cutting — each shared edge is cut only once.",
                    Severity.WARNING, code="EXPORT_COMMON_CUT",
                )
            )
        else:
            report.notices.append(
                Notice(
                    "Common-line cutting was on but no parts share an edge "
                    "(increase packing / set part spacing to 0 so parts butt together).",
                    Severity.INFO, code="EXPORT_COMMON_NONE",
                )
            )
    return report
