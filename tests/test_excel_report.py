from zipfile import ZipFile
from xml.etree import ElementTree as ET

import pytest
from shapely.geometry import Polygon

from cad_n.core.excel_report import _ceil_quarter, write_excel_report
from cad_n.core.models import NestingResult, Placement, Sheet, UnnestedPart


def _rows(archive, index):
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    root = ET.fromstring(archive.read(f"xl/worksheets/sheet{index}.xml"))
    return [[c.find("s:is/s:t", ns).text if c.get("t") == "inlineStr"
             else float(c.find("s:v", ns).text) for c in row]
            for row in root.findall("s:sheetData/s:row", ns)]


def test_excel_reports_each_placement_and_net_area_on_mixed_sheets(tmp_path):
    # One square inch with 2 mm corner relief cuts and a hole: the report
    # counts it as the complete square, sides rounded up 25.4 -> 25.5 mm.
    poly = Polygon([(2, 0), (23.4, 0), (23.4, 2), (25.4, 2), (25.4, 23.4),
                    (23.4, 23.4), (23.4, 25.4), (2, 25.4), (2, 23.4), (0, 23.4),
                    (0, 2), (2, 2)],
                   [[(5, 5), (12.8, 5), (12.8, 12.8), (5, 12.8)]])
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
    assert parts[1][8:10] == [25.5, 25.5]
    assert parts[1][10] == pytest.approx(650.25)
    assert parts[1][11] == pytest.approx(650.25 / 645.16)
    assert summary[1][5] == pytest.approx(parts[1][10])
    assert summary[2][2] == 200
    assert failed[1] == ["Large", "q", 2, "Too large"]


@pytest.mark.parametrize("mm, expected", [
    (1.1, 1.25), (1.4, 1.5), (1.6, 1.75), (1.25, 1.25), (2.0, 2.0), (2.0000001, 2.0)])
def test_dimensions_round_up_to_quarter_mm(mm, expected):
    assert _ceil_quarter(mm) == expected
