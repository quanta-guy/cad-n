# Changelog

All notable changes to CAD-N are recorded here.

## [Unreleased]

### Added
- **Internal cut preservation (micro-joints / chases)**: open cut linework that
  lies inside a part's outer boundary — micro-joint tabs and "chase" outlines
  drawn as gapped or open segments — is now kept verbatim instead of being
  dropped as an open contour. Each piece is attached to the part that contains it
  (`Part.internal_paths`), transformed with that part through nesting
  (rotation / mirror / placement), drawn in the preview, and re-emitted on the
  `CUT` layer at export (and re-imported faithfully). Micro-joint gaps are
  preserved, never bridged, so the tabs that hold a part or its cut-out drop in
  the skeleton survive. Closed internal contours are still treated as holes;
  preserved internal lines raise an `INTERNAL_CUTS_KEPT` notice, and open
  geometry not inside any part is still reported via `OPEN_CONTOUR`.

## [0.4.0] — 2026-06-11 — First public release

CAD-N goes open source under the **MIT License** (formerly an internal tool).

### Added
- **Common-line cutting (opt-in DXF export mode, default OFF)**: when parts butt
  against each other (part spacing 0), the export can dissolve them so the outer
  perimeter is cut once on `CUT` and each internal shared edge once on
  `COMMON_CUT` — no doubled coincident lines on common edges. Enable with the
  "Common-line cut" checkbox next to Export (or `ExportOptions.common_line`).
- **Two stock sizes (mixed-sheet nesting)**: optionally define a second sheet
  size (B). The engine searches mixes of A and B and returns the configuration
  that places every part with the **least total stock area**, offering the ranked
  alternatives in a chooser above the preview so the operator can compare and
  pick. Single-stock behaviour is unchanged; per-sheet sizes flow through the
  preview, DXF export, CSV report, and saved jobs. `nest()` now accepts a
  `Sheet` or a list of `Sheet`.
- **Open-source release files**: MIT `LICENSE`, `NOTICE` (LGPL statement for
  Qt and GEOS), `THIRD_PARTY_LICENSES.md`, and the `LICENSES/` folder with
  full third-party license texts.

### Changed
- **Project renamed to CAD-N** (package `cad_n`, CLI `cad-n`); neutral project
  logo and icon.
- **Export colours**: nested-DXF cut lines are now all white — ordinary cuts and
  common-line shared edges (`CUT` / `COMMON_CUT`) share one colour; only the stock
  sheet outline (`SHEET_BOUNDARY`) is yellow.
- **Export labels off by default**: exported DXFs no longer carry sheet/part text,
  for a clean cut-ready file. Part numbers still appear in the on-screen preview.

## [0.3.0] — 2026-06-03 — Production MVP

First internally usable release (roadmap milestone v0.3).

### Added
- **DXF import** via ezdxf with a layer/entity summary and cut-layer selection.
  Supports `LINE / LWPOLYLINE / POLYLINE / ARC / CIRCLE`, flattens `SPLINE` /
  `ELLIPSE`, and explodes `INSERT` blocks (recursively). Annotation entities
  (`TEXT / MTEXT / DIMENSION / LEADER / MLEADER / HATCH …`) are ignored by default.
- **Geometry cleaner**: endpoint welding, duplicate/tiny-segment removal,
  collinear merge, closed-loop reconstruction (simple-cycle + DCEL planar faces
  for shared edges), even-odd hole/containment classification, validity repair.
- **Unit handling**: DXF `$INSUNITS` converted to millimetres with a warning when
  units are ambiguous.
- **Manual rectangular parts**; automatic grouping of identical imported parts by
  quantity.
- **Nesting engine**: bottom-left-fill placement with spacing + kerf clearance,
  rotation steps, multiple sheets (first-fit), and multi-seed search scored by
  (most placed, fewest sheets, tightest used length).
- **Reporting**: per-sheet and total utilization, scrap area, remnant length.
- **Clean DXF export** on `SHEET_BOUNDARY` / `CUT` / `LABELS` layers, with a
  pre-export validation gate that blocks overlapping or out-of-bounds layouts.
- **Self-contained JSON jobs** (save/load; survives moved source files) and a
  **CSV report**.
- **PySide6 desktop UI**: parts table with editable quantities, sheet/nesting
  settings, advanced tolerance dialog, zoom/pan preview with sheet navigation,
  warnings panel, threaded nesting (responsive UI).
- **Windows packaging**: PyInstaller spec (one-folder and one-file), Windows
  version resource, app icon, and an Inno Setup installer script.
- **Tests & tooling**: 56 automated tests (geometry, importer across 15 fixture
  categories, nesting invariants, export round-trip, reports, job I/O, regression
  guards, headless GUI smoke); fixture generator; real-world DXF fetcher;
  full-pipeline benchmark; visual gallery renderer.

### Robustness
- Malformed/corrupt DXFs (including real broken files) produce a clean error and
  never crash; one bad entity is skipped, not fatal.
- Benchmarked against 31 DXFs (15 synthetic + 16 downloaded real-world) with
  zero crashes; every nestable file re-opened cleanly after export.

### Known limitations / not yet implemented
- Greedy heuristic, not a commercial-grade optimizer.
- No common-cut, common-line removal, edge merging, part-in-part,
  non-rectangular sheets, or no-fit-polygon optimization (roadmap v0.4+).

### Notes
- Built and tested on Python 3.14; supported on 3.11–3.14.
- `pyclipper` was dropped from dependencies — clearance offsetting uses Shapely's
  buffer, so the integer-Clipper backend was unnecessary for this release.
