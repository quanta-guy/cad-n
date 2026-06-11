# CAD-N — Operator Guide

CAD-N arranges your DXF parts onto sheet stock so you waste less material and
get a clean DXF to cut. This guide walks through a normal job.

---

## 1. Start the program

Double-click **CAD-N** (or `CAD-N.exe`). No Python or extra software is
needed. The window has four areas:

- **Left** — buttons and the Sheet / Nesting settings.
- **Centre** — the layout preview and sheet navigation.
- **Right** — the parts list and warnings.
- **Bottom** — the result summary and export buttons.

## 2. Import parts from DXF

1. Click **Import DXF…** and pick one or more `.dxf` files.
2. For each file a window shows every **layer**, how many entities it has, and
   the file's units. Tick the layers that contain **part outlines**.
   - Layers that look like dimensions/text/borders are unticked for you.
   - Layers with no usable geometry can't be ticked.
3. Click **OK**. Detected parts appear in the parts list on the right.

**Why dimensions and text are left out:** a dimension is drawn with little arrow
shapes and text. If those were treated as cut geometry, your sheet would fill up
with tiny arrow "parts" and junk. CAD-N ignores `TEXT`, `MTEXT`, `DIMENSION`,
`LEADER`, `MLEADER` and `HATCH` unless you deliberately include their layer — and
even then the dimension/text entities themselves are never cut.

> Tip: a part outline must be **closed**. If a contour has a gap, it shows up as
> an "open contour" warning and is **not** nested. Fix the gap in your CAD tool
> and re-import.

## 3. Add a rectangular part by hand

For plain rectangles you don't need a DXF:

1. Click **Add rectangular part…**
2. Enter a name, **Length**, **Width**, **Quantity**, and whether rotation is allowed.
3. Click **OK**.

## 4. Set quantities

In the parts list, **double-click the Qty cell** of any part and type the number
you need. Imported repeats of the same shape are grouped automatically.

## 5. Set up the sheet

On the left, under **Sheet**:

- **Length / Width** — your sheet size in mm.
- **Sheets available** — how many sheets you have (leave high for "as many as needed").
- **Border margin** — keep parts this far from the sheet edge.

## 6. Set nesting options

Under **Nesting**:

- **Part spacing** — gap between parts (mm).
- **Kerf** — extra allowance for the cut width (added to spacing).
- **Rotations** — e.g. `0 / 90 / 180 / 270`, finer steps, or no rotation.
- **Strategy** — usually *Largest area first*.
- **Attempts** — more attempts try more arrangements and keep the best (slower).
- **Time limit** — stops searching after this many seconds.

## 7. Run the nest

Click **RUN NEST**. A progress bar shows attempts; the window stays responsive.
When it finishes, the preview shows the first sheet.

- Use **mouse wheel** to zoom, **drag** to pan, **Fit** to reset.
- Use **Prev / Next sheet** to step through sheets.

## 8. Read the results

The bottom bar shows:

- **Sheets** used, parts **Nested** and **Unnested**.
- **Total utilization** (used area ÷ usable sheet area).
- **Scrap** area and **Remnant length** per sheet (unused length at the end of the sheet).

The **Warnings** panel (right) lists anything you should check, in plain English.

## 9. Export the nested DXF

Click **Export DXF…** and choose a file name. The output has:

- `SHEET_BOUNDARY` — the sheet rectangles,
- `CUT` — the part outlines and holes,
- `LABELS` — part names (optional).

Sheets are placed side by side in the file. **Before writing, CAD-N checks
the layout**: if any part overlaps or sits outside the sheet, it refuses to
export and tells you — it will not quietly produce a wrong cut file.

Open the exported DXF in your usual CAD/CAM program and **check it before
cutting**, especially the first time.

## 10. Save and reload a job

- **File → Save job…** stores parts, quantities, sheet and settings in one JSON
  file. The part shapes are saved inside it, so the job still opens even if the
  original DXFs are moved.
- **File → Load job…** restores everything.

You can also **Export report (CSV)** for a record of the job.

## 11. Understanding warnings

| Message | Meaning | What to do |
|---|---|---|
| Open contour detected | A part outline has a gap | Close the contour in CAD and re-import |
| Duplicate segments removed | The same lines were drawn twice | Usually harmless |
| Annotation entities ignored | Text/dimensions were skipped | Expected; nothing to do |
| Block references exploded | A block was opened into its lines | Expected |
| Units are not specified | The DXF didn't say mm/inch | Check the part sizes look right |
| Fragments below minimum area ignored | Tiny stray shapes were dropped | Usually harmless |
| Part is larger than the sheet | A part can't fit even alone | Use a bigger sheet or smaller part |

## 12. Good habits

- Keep a clean **CUT** layer in your CAD exports.
- Verify the **preview** and the **exported DXF** before sending to the machine.
- Cut one low-risk job first when trying a new part family.
