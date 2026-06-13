"""Best-nests chooser dialog.

Lists the highest-utilization nests from the persistent log and lets the operator
load one back into the preview (and so export/report it). Read-only table; the
selected record is exposed as ``selected_record`` after the dialog is accepted.
"""

from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class BestNestsDialog(QDialog):
    def __init__(self, history, parent=None) -> None:
        super().__init__(parent)
        self.history = history
        self.selected_record = None
        self.setWindowTitle("Best nests (highest utilization)")
        self.resize(760, 440)

        v = QVBoxLayout(self)
        v.addWidget(QLabel(
            "Highest-utilization nests, best first. Select one and load it to "
            "preview and export that layout."))

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Utilization", "Sheets", "Parts placed", "When", "Source", "Summary"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.doubleClicked.connect(self._load)
        v.addWidget(self.table, 1)

        row = QHBoxLayout()
        self.btn_load = QPushButton("Load into preview")
        self.btn_load.clicked.connect(self._load)
        self.btn_delete = QPushButton("Delete")
        self.btn_delete.clicked.connect(self._delete)
        self.btn_clear = QPushButton("Clear all")
        self.btn_clear.clicked.connect(self._clear)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.reject)
        row.addWidget(self.btn_load)
        row.addWidget(self.btn_delete)
        row.addStretch(1)
        row.addWidget(self.btn_clear)
        row.addWidget(btn_close)
        v.addLayout(row)

        self._refresh()

    # ------------------------------------------------------------------ #
    def _refresh(self) -> None:
        recs = self.history.records
        self.table.setRowCount(len(recs))
        for i, r in enumerate(recs):
            sources = ", ".join(os.path.basename(s) for s in r.source_files) or "(manual)"
            cells = [
                f"{r.total_utilization * 100:.1f}%",
                str(r.sheets_used),
                f"{r.parts_placed}/{r.parts_requested}",
                r.created_at.replace("T", " "),
                sources,
                r.label,
            ]
            for c, text in enumerate(cells):
                self.table.setItem(i, c, QTableWidgetItem(text))
        self.table.resizeColumnsToContents()
        has = bool(recs)
        self.btn_load.setEnabled(has)
        self.btn_delete.setEnabled(has)
        self.btn_clear.setEnabled(has)
        if has and self.table.currentRow() < 0:
            self.table.selectRow(0)

    def _current(self):
        idx = self.table.currentRow()
        if 0 <= idx < len(self.history.records):
            return self.history.records[idx]
        return None

    def _load(self) -> None:
        rec = self._current()
        if rec is None:
            return
        self.selected_record = rec
        self.accept()

    def _delete(self) -> None:
        rec = self._current()
        if rec is None:
            return
        self.history.delete(rec.id)
        self._refresh()

    def _clear(self) -> None:
        self.history.clear()
        self._refresh()
