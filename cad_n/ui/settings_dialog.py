"""Advanced tolerance settings dialog (doc 7.2: tolerances live in an advanced
panel, not the main screen)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
)

from ..config import Tolerances

_FIELDS = [
    ("snap_tolerance_mm", "Endpoint snap tolerance (mm)", 0.0, 5.0, 0.001),
    ("curve_chord_tolerance_mm", "Curve chord tolerance (mm)", 0.001, 5.0, 0.001),
    ("min_segment_length_mm", "Minimum segment length (mm)", 0.0, 5.0, 0.001),
    ("overlap_tolerance_mm", "Overlap tolerance (mm)", 0.0, 5.0, 0.001),
    ("collinear_angle_tolerance_deg", "Collinear merge angle (deg)", 0.0, 10.0, 0.1),
    ("min_part_area_mm2", "Minimum part area (mm^2)", 0.0, 1000.0, 0.1),
]


class SettingsDialog(QDialog):
    def __init__(self, tol: Tolerances, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Advanced geometry tolerances")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("These affect how DXF geometry is cleaned and "
                                "stitched. Defaults suit millimetre sheet-metal work."))
        form = QFormLayout()
        self._spins: dict[str, QDoubleSpinBox] = {}
        for name, label, lo, hi, step in _FIELDS:
            sp = QDoubleSpinBox()
            sp.setRange(lo, hi)
            sp.setSingleStep(step)
            sp.setDecimals(3)
            sp.setValue(getattr(tol, name))
            self._spins[name] = sp
            form.addRow(label, sp)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel
                                   | QDialogButtonBox.RestoreDefaults)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self._restore)
        layout.addWidget(buttons)

    def _restore(self) -> None:
        d = Tolerances()
        for name, sp in self._spins.items():
            sp.setValue(getattr(d, name))

    def tolerances(self) -> Tolerances:
        return Tolerances(**{name: sp.value() for name, sp in self._spins.items()})
