"""Tests for the best-nests log: result serialisation, leaderboard ranking
(keep only the highest-utilization nests), de-duplication, and disk round-trip."""

import math

from cad_n.core import nest_history as nh
from cad_n.core.models import NestingSettings, Sheet, make_rectangle_part
from cad_n.core.nesting_engine import nest


def _make_result():
    sheet = Sheet("S", 300, 200)
    return nest([make_rectangle_part("A", 50, 40, quantity=3)], sheet,
                NestingSettings(attempt_count=1, part_spacing_mm=2)), sheet


def test_result_dict_roundtrip_preserves_layout():
    result, _ = _make_result()
    restored = nh.result_from_dict(nh.result_to_dict(result))
    assert len(restored.placements) == len(result.placements)
    assert restored.sheet_count_used == result.sheet_count_used
    assert math.isclose(restored.total_utilization, result.total_utilization, rel_tol=1e-9)
    # Geometry survives (areas match placement-for-placement).
    a = sorted(round(p.polygon_world.area, 3) for p in result.placements)
    b = sorted(round(p.polygon_world.area, 3) for p in restored.placements)
    assert a == b


def test_internal_lines_survive_result_roundtrip():
    import dxfgen
    import tempfile, os
    from cad_n.core.dxf_importer import import_dxf
    src = os.path.join(tempfile.mkdtemp(), "mj.dxf")
    dxfgen.internal_micro_joints().saveas(src)
    parts = import_dxf(src).parts
    result = nest(parts, Sheet("S", 400, 300), NestingSettings(attempt_count=1))
    restored = nh.result_from_dict(nh.result_to_dict(result))
    before = sum(len(p.internal_world) for p in result.placements)
    after = sum(len(p.internal_world) for p in restored.placements)
    assert before == after == 5


def test_history_keeps_only_top_utilization(tmp_path):
    path = str(tmp_path / "hist.json")
    hist = nh.NestHistory(path, cap=3)
    result, sheets = _make_result()

    # Insert several records with descending utilization values.
    for i, util in enumerate([0.40, 0.90, 0.55, 0.95, 0.20]):
        rec = nh.make_record(result, [], [sheets], NestingSettings(), [f"job{i}.dxf"])
        rec.total_utilization = util
        rec.label = f"u{util}"
        hist.consider(rec)

    # Only the top 3 by utilization are kept, best first.
    utils = [round(r.total_utilization, 2) for r in hist.records]
    assert utils == [0.95, 0.90, 0.55]


def test_history_dedups_same_signature(tmp_path):
    path = str(tmp_path / "hist.json")
    hist = nh.NestHistory(path, cap=10)
    result, sheets = _make_result()
    for _ in range(3):
        rec = nh.make_record(result, [], [sheets], NestingSettings(), ["same.dxf"])
        rec.total_utilization = 0.80
        hist.consider(rec)
    assert len(hist.records) == 1


def test_history_persists_to_disk(tmp_path):
    path = str(tmp_path / "hist.json")
    result, sheets = _make_result()
    h1 = nh.NestHistory(path, cap=5)
    rec = nh.make_record(result, [], [sheets], NestingSettings(), ["p.dxf"])
    rec.total_utilization = 0.77
    h1.consider(rec)

    # Reload from disk -> the record (and its layout) come back.
    h2 = nh.NestHistory.load(path)
    assert len(h2.records) == 1
    restored = nh.result_from_dict(h2.records[0].payload["result"])
    assert restored.sheet_count_used == result.sheet_count_used
    assert len(restored.placements) == len(result.placements)
