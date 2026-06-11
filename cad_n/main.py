"""Application entry point.  Run with:  python -m cad_n   (or the cad_n script)."""

from __future__ import annotations

import os
import sys

from .config import APP_NAME, APP_VERSION
from .logging_setup import configure, get_logger


def _icon_path() -> str | None:
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(here, "resources", "icon.ico")
    return p if os.path.exists(p) else None


def _selfcheck() -> int:
    """Headless exercise of the full geometry stack -- proves a frozen build can
    actually compute (Shapely/GEOS + ezdxf), not just import. Returns 0 on OK."""
    import os
    import tempfile

    from .core import dxf_exporter, dxf_importer
    from .core.models import NestingSettings, Sheet, make_rectangle_part
    from .core.nesting_engine import nest

    log = get_logger("selfcheck")
    try:
        parts = [make_rectangle_part("A", 100, 60, 4), make_rectangle_part("B", 50, 50, 6)]
        sheet = Sheet("S", 400, 300, margin_mm=5)
        res = nest(parts, sheet, NestingSettings(attempt_count=2, time_limit_sec=10))
        assert res.total_parts_nested == 10, res.total_parts_nested
        fd, path = tempfile.mkstemp(suffix=".dxf")
        os.close(fd)
        rep = dxf_exporter.export_nesting(res, path, sheet)
        assert rep.success
        reimp = dxf_importer.import_dxf(path)
        assert len(reimp.parts) >= 1
        os.remove(path)
        log.info("SELFCHECK PASS: nested 10, exported %d profiles, reopened OK",
                 rep.cut_entities)
        return 0
    except Exception as exc:  # noqa: BLE001
        log.exception("SELFCHECK FAIL: %s", exc)
        return 2


def main() -> int:
    configure()
    log = get_logger("main")
    log.info("Starting %s %s", APP_NAME, APP_VERSION)

    if os.environ.get("CADN_SELFCHECK"):
        return _selfcheck()

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(f"{APP_NAME} {APP_VERSION}")
    ico = _icon_path()
    if ico:
        app.setWindowIcon(QIcon(ico))

    from .ui.main_window import MainWindow

    win = MainWindow()
    if ico:
        win.setWindowIcon(QIcon(ico))
    win.show()

    # Unattended launch self-test (used by packaging verification): show the
    # window then quit cleanly so a CI/build step can confirm the app starts.
    if os.environ.get("CADN_SELFTEST"):
        from PySide6.QtCore import QTimer

        QTimer.singleShot(400, app.quit)
        log.info("Self-test mode: window shown, quitting shortly.")

    return app.exec()


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()  # safe no-op; protects packaged builds
    sys.exit(main())
