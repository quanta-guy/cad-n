"""Background nesting worker so the UI never freezes during a nest."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from ..core.nesting_engine import nest


class NestWorker(QThread):
    progress = Signal(int, int, str)
    done = Signal(object)     # emits NestingResult
    failed = Signal(str)

    def __init__(self, parts, sheets, settings, parent=None) -> None:
        super().__init__(parent)
        self._parts = parts
        self._sheets = sheets   # Sheet or list[Sheet]
        self._settings = settings

    def run(self) -> None:
        try:
            res = nest(self._parts, self._sheets, self._settings,
                       progress=lambda d, t, m: self.progress.emit(d, t, m))
            self.done.emit(res)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")
