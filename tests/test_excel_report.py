from zipfile import ZipFile
from xml.etree import ElementTree as ET

import pytest
from shapely.geometry import Polygon

from cad_n.core.excel_report import write_excel_report
from cad_n.core.models import NestingResult, Placement, Sheet, UnnestedPart


def _rows(archive, index):
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    root = ET.fromstring(archive.read(f"xl/worksheets/sheet{index}.xml"))
    return [[c.find("s:is/s:t", ns).text if c.get("t") == "inlineStr"
             else float(c.find("s:v", ns).text) for c in row]
            for row in root.findall("s:sheetData/s:row", ns)]


def test_excel_reports_each_placement_and_net_area_on_mixed_sheets(tmp_path):
    # One square inch minus a quarter-square-inch hole.
    poly = Polygon([(0, 0), (25.4, 0), (25.4, 25.4), (0, 25.4)],
                   [[(0.1, 0.1), (12.8, 0.1), (12.8, 12.8), (0.1, 12.8)]])
    placements = [Placement("p", "=A&B", i, 0, 0, 90, False, poly) for i in range(2)]
    result = NestingResult(placements=placements, sheet_count_used=2,
                          sheets=[Sheet("A", 100, 100), Sheet("B", 200, 100)],
                          unnested_parts=[UnnestedPart("q", "Large", 2, "Too large")])
    path = tmp_path / "parts.xlsx"
    write_excel_report(result, path)
    with ZipFile(path) as archive:
        assert archive.testzip() is None
        # All package XML is well formed, including special characters in names.
        for name in archive.namelist():
            ET.fromstring(archive.read(name))
        summary, parts, failed = [_rows(archive, i) for i in (1, 2, 3)]
    assert len(parts) == 3
    assert [r[0] for r in parts[1:]] == [1, 2]
    assert parts[1][2] == "=A&B"  # Text, never interpreted as an Excel formula.
    assert parts[1][8] == pytest.approx(483.87)
    assert parts[1][9] == pytest.approx(0.75)
    assert summary[1][5] == pytest.approx(parts[1][8])
    assert summary[2][2] == 200
    assert failed[1] == ["Large", "q", 2, "Too large"]
