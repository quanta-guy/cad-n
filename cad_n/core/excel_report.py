"""Portable Excel part report using the standard Open XML ZIP format.

No Office installation or additional runtime dependency is required.
Areas are each part's full enclosing rectangle (minimum rotated rectangle):
corner relief cuts, notches and holes are ignored, matching how panels are
costed. Rectangle sides are rounded up to the next 0.25 mm before the area is
computed. The DXF export and on-screen statistics still use true geometry.
"""

from pathlib import Path
from tempfile import NamedTemporaryFile
from xml.etree.ElementTree import Element, SubElement, tostring
from zipfile import ZIP_DEFLATED, ZipFile
import math
import os

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _xml(root):
    return tostring(root, encoding="utf-8", xml_declaration=True)


def _worksheet(rows):
    root = Element("worksheet", xmlns=NS)
    views = SubElement(root, "sheetViews")
    view = SubElement(views, "sheetView", workbookViewId="0")
    SubElement(view, "pane", ySplit="1", topLeftCell="A2", activePane="bottomLeft", state="frozen")
    cols = SubElement(root, "cols")
    for i in range(len(rows[0])):
        width = min(45, max(16, max(len(str(r[i])) if i < len(r) else 0 for r in rows) + 2))
        SubElement(cols, "col", min=str(i+1), max=str(i+1), width=str(width), customWidth="1")
    data = SubElement(root, "sheetData")
    for row_index, values in enumerate(rows, 1):
        row = SubElement(data, "row", r=str(row_index))
        for col_index, value in enumerate(values):
            # Report tables contain fewer than 26 columns.
            cell = SubElement(row, "c", r=f"{chr(65+col_index)}{row_index}")
            if isinstance(value, (int, float)):
                cell.set("s", "0" if isinstance(value, int) else "2")
                SubElement(cell, "v").text = str(value)
            else:
                cell.set("t", "inlineStr")
                cell.set("s", "1" if row_index == 1 else "0")
                SubElement(SubElement(cell, "is"), "t").text = str(value)
    SubElement(root, "autoFilter", ref=f"A1:{chr(64+len(rows[0]))}{len(rows)}")
    return _xml(root)


def _ceil_quarter(mm):
    """Round up to the next 0.25 mm; the epsilon keeps exact steps (1.25) put."""
    return math.ceil(round(mm / 0.25, 6)) * 0.25


def _rect_dims(placement):
    """(length, width) of the complete enclosing rectangle, ignoring corner
    cuts and holes, each side rounded up to 0.25 mm."""
    pts = list(placement.polygon_world.minimum_rotated_rectangle.exterior.coords)
    sides = [math.dist(pts[0], pts[1]), math.dist(pts[1], pts[2])]
    return tuple(_ceil_quarter(v) for v in sorted(sides, reverse=True))


def _rect_area(placement):
    length, width = _rect_dims(placement)
    return length * width


def write_excel_report(result, path):
    """Write sheet totals and individual placements for the selected layout."""
    summary = [["Sheet", "Stock", "Width (mm)", "Height (mm)", "Parts",
                "Part area (mm²)", "Part area (in²)", "Stock utilization (%)"]]
    parts = [["Sheet", "Part on sheet", "Part name", "Part ID", "X (mm)",
              "Y (mm)", "Rotation (deg)", "Mirrored", "Length (mm)", "Width (mm)",
              "Area (mm²)", "Area (in²)"]]
    for i in range(result.sheet_count_used):
        sheet = result.sheet_at(i)
        placed = result.placements_on(i)
        area = sum(_rect_area(p) for p in placed)
        stock_area = sheet.width_mm * sheet.height_mm
        summary.append([i+1, sheet.name, sheet.width_mm, sheet.height_mm, len(placed),
                        area, area / 645.16, 100 * area / stock_area if stock_area else 0])
        for j, p in enumerate(placed, 1):
            parts.append([i+1, j, p.part_name, p.part_id, p.x_mm, p.y_mm,
                          p.rotation_deg, "Yes" if p.mirrored else "No",
                          *_rect_dims(p), _rect_area(p), _rect_area(p) / 645.16])
    tables = [("Sheets", summary), ("Placed parts", parts)]
    if result.unnested_parts:
        tables.append(("Unplaced parts", [["Part name", "Part ID", "Quantity", "Reason"]] + [
            [p.part_name, p.part_id, p.quantity_failed, p.reason] for p in result.unnested_parts]))
    content = Element("Types", xmlns="http://schemas.openxmlformats.org/package/2006/content-types")
    SubElement(content, "Default", Extension="rels", ContentType="application/vnd.openxmlformats-package.relationships+xml")
    SubElement(content, "Default", Extension="xml", ContentType="application/xml")
    workbook = Element("workbook", xmlns=NS, attrib={"xmlns:r": REL})
    sheets = SubElement(workbook, "sheets")
    rels = Element("Relationships", xmlns="http://schemas.openxmlformats.org/package/2006/relationships")
    for i, (name, _) in enumerate(tables, 1):
        SubElement(sheets, "sheet", name=name, sheetId=str(i), attrib={"r:id": f"rId{i}"})
        SubElement(rels, "Relationship", Id=f"rId{i}", Type=f"{REL}/worksheet", Target=f"worksheets/sheet{i}.xml")
        SubElement(content, "Override", PartName=f"/xl/worksheets/sheet{i}.xml", ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml")
    SubElement(rels, "Relationship", Id="styles", Type=f"{REL}/styles", Target="styles.xml")
    for name, kind in [("workbook", "sheet.main"), ("styles", "styles")]:
        SubElement(content, "Override", PartName=f"/xl/{name}.xml", ContentType=f"application/vnd.openxmlformats-officedocument.spreadsheetml.{kind}+xml")
    root_rels = Element("Relationships", xmlns="http://schemas.openxmlformats.org/package/2006/relationships")
    SubElement(root_rels, "Relationship", Id="rId1", Type=f"{REL}/officeDocument", Target="xl/workbook.xml")
    styles = f'''<styleSheet xmlns="{NS}"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF244766"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/><xf numFmtId="4" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'''
    target = Path(path)
    with NamedTemporaryFile(dir=target.parent, suffix=".xlsx", delete=False) as tmp:
        temp_path = Path(tmp.name)
    try:
        with ZipFile(temp_path, "w", ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", _xml(content))
            archive.writestr("_rels/.rels", _xml(root_rels))
            archive.writestr("xl/workbook.xml", _xml(workbook))
            archive.writestr("xl/_rels/workbook.xml.rels", _xml(rels))
            archive.writestr("xl/styles.xml", styles)
            for i, (_, rows) in enumerate(tables, 1):
                archive.writestr(f"xl/worksheets/sheet{i}.xml", _worksheet(rows))
        os.replace(temp_path, target)
    finally:
        temp_path.unlink(missing_ok=True)
