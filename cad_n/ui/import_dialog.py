"""Import dialog: shows the layer/entity summary so the operator confirms which
layers are cut geometry before anything is nested (doc 11.3, 12.2)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class ImportDialog(QDialog):
    def __init__(self, summary, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import DXF - choose cut layers")
        self.resize(560, 420)
        self._summary = summary
        suggested = summary.suggested_cut_layers()

        layout = QVBoxLayout(self)
        import os
        head = (f"<b>{os.path.basename(summary.path)}</b><br>"
                f"Units: {summary.unit_name} (x{summary.unit_scale:g} to mm) &nbsp; | &nbsp; "
                f"{summary.total_entities} entities on {len(summary.layers)} layer(s)")
        layout.addWidget(QLabel(head))
        layout.addWidget(QLabel("Tick the layers that contain part outlines. "
                                "Dimension/text layers are unticked by default."))

        self.table = QTableWidget(len(summary.layers), 4, self)
        self.table.setHorizontalHeaderLabels(["Cut?", "Layer", "Entities", "Types"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        for r, li in enumerate(summary.layers):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            checkable = li.has_cut_candidates
            chk.setCheckState(
                Qt.Checked if (li.name in suggested and checkable) else Qt.Unchecked
            )
            if not checkable:
                chk.setFlags(Qt.ItemIsEnabled)  # no cut candidates -> not selectable
                chk.setToolTip("No cut-candidate entities on this layer.")
            self.table.setItem(r, 0, chk)
            self.table.setItem(r, 1, QTableWidgetItem(li.name))
            self.table.setItem(r, 2, QTableWidgetItem(str(li.total)))
            self.table.setItem(r, 3, QTableWidgetItem(", ".join(li.types)))
        self.table.resizeColumnsToContents()
        layout.addWidget(self.table)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_layers(self) -> set[str]:
        out = set()
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item.checkState() == Qt.Checked:
                out.add(self.table.item(r, 1).text())
        return out
