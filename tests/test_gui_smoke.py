"""Headless GUI smoke test (doc acceptance: 'the app launches').

Uses Qt's offscreen platform so it runs without a display. Drives the public
MainWindow action methods through a full import -> nest -> export -> save/load
cycle and asserts nothing crashes and a valid result is produced.
"""

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

import dxfgen  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _pump_until(app, predicate, timeout=30.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_window_full_cycle(app, tmp_path):
    from cad_n.ui.main_window import MainWindow

    win = MainWindow()
    win.add_rectangle("A", 100, 60, 4)
    win.add_rectangle("B", 50, 50, 6)
    assert len(win.parts) == 2

    # Also import a generated DXF file (no dialog) to exercise import_paths.
    f = tmp_path / "combo.dxf"
    dxfgen.multiple_parts().saveas(f)
    win.import_paths([str(f)], ask_layers=False)
    assert len(win.parts) == 5  # 2 manual + 3 from the combined DXF

    win.sp_sheet_w.setValue(500)
    win.sp_sheet_h.setValue(400)
    win.sp_attempts.setValue(2)
    win.sp_timelimit.setValue(10)

    win.run_nest()
    assert _pump_until(app, lambda: win.result is not None), "nest did not finish"
    assert win.result.total_parts_nested > 0

    out = tmp_path / "out.dxf"
    rep = win.export_dxf(str(out))
    assert rep.success and out.exists()

    job = tmp_path / "job.json"
    win.save_job(str(job))
    win.clear_parts()
    assert len(win.parts) == 0
    win.load_job(str(job))
    assert len(win.parts) == 5

    win.close()


def test_window_two_sheet_sizes(app, tmp_path):
    from cad_n.ui.main_window import MainWindow

    win = MainWindow()
    win.add_rectangle("P", 90, 90, 5, False)
    win.sp_sheet_w.setValue(200); win.sp_sheet_h.setValue(100); win.sp_margin.setValue(0)
    win.sp_attempts.setValue(2)
    # Enable a second stock size (B) -> engine searches mixes of A and B.
    win.chk_sheet2.setChecked(True)
    win.sp_sheet2_w.setValue(100); win.sp_sheet2_h.setValue(100)
    # isHidden() reflects the widget's own flag (the window is never shown here).
    assert not win.sheet2_box.isHidden()

    win.run_nest()
    assert _pump_until(app, lambda: win.result is not None), "nest did not finish"
    assert win.result.total_parts_nested == 5
    assert len(win.result.configurations) > 1
    assert not win.cfg_widget.isHidden()
    assert win.cb_config.count() == len(win.result.configurations)

    # Picking another configuration switches the active (exported) result.
    win.cb_config.setCurrentIndex(1)
    assert win._active_result is win.result.configurations[1].result

    out = tmp_path / "mix.dxf"
    rep = win.export_dxf(str(out))
    assert rep.success and out.exists()
    win.close()
