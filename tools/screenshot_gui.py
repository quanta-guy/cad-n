"""Render the real MainWindow to a PNG for visual inspection (offscreen).

Run:  python tools/screenshot_gui.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from PySide6.QtWidgets import QApplication  # noqa: E402

import dxfgen  # noqa: E402

from cad_n.core import dxf_importer as imp  # noqa: E402
from cad_n.core.models import make_rectangle_part  # noqa: E402
from cad_n.core.nesting_engine import nest  # noqa: E402
from cad_n.ui.main_window import MainWindow  # noqa: E402

OUT = ROOT / "tests" / "_visual_out"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.resize(1320, 840)

    # Populate with a realistic mix: a combined DXF + manual rectangles.
    doc = dxfgen.multiple_parts()
    res = imp.extract(doc, "combined.dxf", imp.ImportOptions(),
                      imp.summarize(doc, "combined.dxf"))
    for p in res.parts:
        p.quantity = 8
    win.parts.extend(res.parts)
    win.add_rectangle("Bracket", 140, 90, 8)
    win.add_rectangle("Spacer", 60, 60, 14)

    win.sp_sheet_w.setValue(640)
    win.sp_sheet_h.setValue(460)
    win.sp_spacing.setValue(4)
    win.sp_attempts.setValue(5)
    win._refresh_part_table()

    sheet = win.build_sheet()
    settings = win.build_settings()
    result = nest(win.parts, sheet, settings)
    win._pending_sheet = sheet
    win._on_nest_done(result)

    win.show()
    for _ in range(8):
        app.processEvents()
    win.canvas.fit_view()
    for _ in range(4):
        app.processEvents()

    path = OUT / "gui_main_window.png"
    shot = win.grab()
    shot.save(str(path))
    # Also refresh the README screenshot (tracked in the repo).
    shot.save(str(ROOT / "assets" / "screenshot.png"))
    print(f"wrote {path} + assets/screenshot.png  (nested {result.total_parts_nested} "
          f"parts on {result.sheet_count_used} sheet(s), util {result.total_utilization*100:.1f}%)")


if __name__ == "__main__":
    main()
