"""Render import previews and nesting layouts to PNG for visual inspection
(doc 14.4 visual regression). Matplotlib is a dev/tooling dependency only.

Run:  python tools/render.py     # builds a gallery in tests/_visual_out/
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import PathPatch  # noqa: E402
from matplotlib.path import Path as MPath  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import dxfgen  # noqa: E402

from cad_n.core import dxf_importer as imp  # noqa: E402
from cad_n.core.models import NestingSettings, Sheet, make_rectangle_part  # noqa: E402
from cad_n.core.nesting_engine import nest  # noqa: E402

OUT = ROOT / "tests" / "_visual_out"
PART_FILL = "#7fb3d5"
HOLE_EDGE = "#c0392b"
SHEET_EDGE = "#2c3e50"


def _ring_codes(n):
    return [MPath.MOVETO] + [MPath.LINETO] * (n - 2) + [MPath.CLOSEPOLY]


def _poly_patch(poly, **kw):
    verts = list(poly.exterior.coords)
    codes = _ring_codes(len(verts))
    for interior in poly.interiors:
        ic = list(interior.coords)
        verts += ic
        codes += _ring_codes(len(ic))
    return PathPatch(MPath(verts, codes), **kw)


def render_import_preview(parts, path, title):
    n = len(parts)
    if n == 0:
        return
    cols = min(4, n)
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(3 * cols, 3 * rows), squeeze=False)
    for i, part in enumerate(parts):
        ax = axes[i // cols][i % cols]
        ax.add_patch(_poly_patch(part.geom, facecolor=PART_FILL, edgecolor="black", lw=1.2))
        minx, miny, maxx, maxy = part.bounds
        pad = max(maxx - minx, maxy - miny) * 0.1 + 1
        ax.set_xlim(minx - pad, maxx + pad)
        ax.set_ylim(miny - pad, maxy + pad)
        ax.set_aspect("equal")
        ax.set_title(f"{part.name} x{part.quantity}\n{part.area:.0f} mm^2, {len(part.holes)} hole(s)",
                     fontsize=8)
        ax.tick_params(labelsize=6)
    for j in range(n, rows * cols):
        axes[j // cols][j % cols].axis("off")
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    fig.savefig(path, dpi=90)
    plt.close(fig)


def render_nesting(result, sheet, path, title):
    n = max(result.sheet_count_used, 1)
    cols = min(3, n)
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(4 * cols, 4 * rows * sheet.height_mm / sheet.width_mm + 1),
                             squeeze=False)
    colors = plt.cm.tab20.colors
    for s in range(n):
        ax = axes[s // cols][s % cols]
        ax.add_patch(plt.Rectangle((0, 0), sheet.width_mm, sheet.height_mm,
                                   fill=False, edgecolor=SHEET_EDGE, lw=1.5))
        for k, pl in enumerate(result.placements_on(s)):
            ax.add_patch(_poly_patch(pl.polygon_world, facecolor=colors[k % len(colors)],
                                     edgecolor="black", lw=0.6, alpha=0.85))
        util = result.utilization_by_sheet[s] * 100 if s < len(result.utilization_by_sheet) else 0
        ax.set_xlim(-sheet.width_mm * 0.03, sheet.width_mm * 1.03)
        ax.set_ylim(-sheet.height_mm * 0.03, sheet.height_mm * 1.03)
        ax.set_aspect("equal")
        ax.set_title(f"Sheet {s + 1}  util {util:.1f}%", fontsize=9)
        ax.tick_params(labelsize=6)
    for j in range(n, rows * cols):
        axes[j // cols][j % cols].axis("off")
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    fig.savefig(path, dpi=90)
    plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    # --- Import previews (verify the right shapes were detected) ---
    preview_specs = {
        "preview_multiple_parts": dxfgen.multiple_parts,
        "preview_dimensions_and_text": dxfgen.dimensions_and_text,  # MUST show only the rect
        "preview_rectangle_with_hole": dxfgen.rectangle_with_hole,
        "preview_arc_profile": dxfgen.arc_profile,
        "preview_spline_profile": dxfgen.spline_profile,
        "preview_blocks_insert": dxfgen.blocks_insert,
        "preview_tiny_fragments": dxfgen.tiny_fragments,  # MUST show only the big rect
    }
    for name, builder in preview_specs.items():
        doc = builder()
        res = imp.extract(doc, f"{name}.dxf", imp.ImportOptions(),
                          imp.summarize(doc, f"{name}.dxf"))
        render_import_preview(res.parts, OUT / f"{name}.png", name)
        print(f"rendered {name}.png ({len(res.parts)} parts)")

    # A real downloaded file, if present.
    real = ROOT / "tests" / "real_dxf" / "gdsestimating__ellipse.dxf"
    if real.exists():
        res = imp.import_dxf(str(real))
        render_import_preview(res.parts, OUT / "preview_real_ellipse.png", "real: ellipse.dxf")
        print(f"rendered preview_real_ellipse.png ({len(res.parts)} parts)")

    # --- Nesting layouts ---
    sheet = Sheet("S", 600, 400, margin_mm=5)
    settings = NestingSettings(part_spacing_mm=4, attempt_count=4)
    parts = [make_rectangle_part("A", 120, 80, quantity=6),
             make_rectangle_part("B", 60, 60, quantity=8),
             make_rectangle_part("C", 200, 40, quantity=4)]
    res = nest(parts, sheet, settings)
    render_nesting(res, sheet, OUT / "nest_mixed_rectangles.png",
                   f"Mixed rectangles ({res.total_parts_nested} parts)")
    print(f"rendered nest_mixed_rectangles.png util={res.total_utilization*100:.1f}%")

    # Multi-sheet job
    sheet2 = Sheet("S2", 300, 300, margin_mm=5)
    res2 = nest([make_rectangle_part("Q", 110, 110, quantity=9)], sheet2,
                NestingSettings(part_spacing_mm=3, attempt_count=2))
    render_nesting(res2, sheet2, OUT / "nest_multisheet.png",
                   f"Multi-sheet ({res2.sheet_count_used} sheets)")
    print(f"rendered nest_multisheet.png sheets={res2.sheet_count_used}")

    # Combined DXF parts nested
    doc = dxfgen.multiple_parts()
    r = imp.extract(doc, "mp.dxf", imp.ImportOptions(), imp.summarize(doc, "mp.dxf"))
    for p in r.parts:
        p.quantity = 4
    sheet3 = Sheet("S3", 500, 400, margin_mm=5)
    res3 = nest(r.parts, sheet3, NestingSettings(part_spacing_mm=3, attempt_count=4))
    render_nesting(res3, sheet3, OUT / "nest_combined_parts.png",
                   f"Combined DXF parts ({res3.total_parts_nested} parts)")
    print(f"rendered nest_combined_parts.png util={res3.total_utilization*100:.1f}%")

    print(f"\nGallery written to {OUT}")


if __name__ == "__main__":
    main()
