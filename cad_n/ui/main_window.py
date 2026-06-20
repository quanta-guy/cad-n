"""Main application window (doc 12.1 layout).

Left: job + sheet + nesting settings. Centre: preview with sheet navigation.
Right: part table + warnings. Bottom: results summary + export controls.

Action methods (import_paths, add_rectangle, run_nest, export_dxf, ...) are public
so they can be driven by a headless smoke test without real dialogs.
"""

from __future__ import annotations

import os
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..config import APP_NAME, APP_VERSION, Tolerances
from ..core import dxf_exporter as dxe
from ..core import dxf_importer as imp
from ..core import job_io, reports
from ..core.models import (
    NestingSettings,
    Part,
    PlacementStrategy,
    Severity,
    Sheet,
    make_rectangle_part,
)
from ..core.nest_history import NestHistory, make_record, result_from_dict
from ..logging_setup import get_logger
from .best_nests_dialog import BestNestsDialog
from .import_dialog import ImportDialog
from .nest_worker import NestWorker
from .preview_canvas import PreviewCanvas
from .settings_dialog import SettingsDialog

log = get_logger("main_window")

_ROT_OPTIONS = [
    ("0 / 90 / 180 / 270", 90.0),
    ("0 / 180", 180.0),
    ("Every 45 deg", 45.0),
    ("Every 30 deg", 30.0),
    ("Every 15 deg", 15.0),
    ("No rotation", 0.0),
]
_STRATEGY_OPTIONS = [
    ("Largest area first", PlacementStrategy.AREA_DESC),
    ("Longest side first", PlacementStrategy.LONGEST_SIDE),
    ("Tallest first", PlacementStrategy.HEIGHT_DESC),
]


class AddRectangleDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add rectangular part")
        form = QFormLayout(self)
        self.name = QLineEdit("Rect")
        self.length = QDoubleSpinBox(); self.length.setRange(0.1, 100000); self.length.setValue(100)
        self.width = QDoubleSpinBox(); self.width.setRange(0.1, 100000); self.width.setValue(60)
        self.qty = QSpinBox(); self.qty.setRange(1, 100000); self.qty.setValue(1)
        self.rot = QComboBox(); self.rot.addItems(["Rotation allowed", "Fixed orientation"])
        form.addRow("Name", self.name)
        form.addRow("Length (mm)", self.length)
        form.addRow("Width (mm)", self.width)
        form.addRow("Quantity", self.qty)
        form.addRow("Rotation", self.rot)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        form.addRow(bb)

    def values(self):
        return (self.name.text().strip() or "Rect", self.length.value(),
                self.width.value(), self.qty.value(), self.rot.currentIndex() == 0)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(1280, 820)

        self.parts = []
        self.source_files: list[str] = []
        self.tolerances = Tolerances()
        self.result = None
        self._active_result = None          # configuration currently shown / exported
        self._suppress_config = False       # guard while repopulating the chooser
        self._pending_sheet: Sheet | None = None
        self._pending_sheets: list[Sheet] = []
        self.job_path: str | None = None
        self.last_export_path: str | None = None
        self._worker: NestWorker | None = None
        # Persistent log of the highest-utilization nests, and a snapshot of the
        # inputs of the nest currently running (so a finished nest can be logged).
        self.history = NestHistory.load()
        self._pending_parts: list = []
        self._pending_settings: NestingSettings | None = None

        self._build_ui()
        self._build_menu()
        self._refresh_part_table()
        self._update_summary()

    # ------------------------------------------------------------------ UI #
    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Horizontal)

        # ---- Left: setup ----
        left = QWidget(); lv = QVBoxLayout(left)
        btn_import = QPushButton("Import DXF...")
        btn_import.clicked.connect(self.on_import_clicked)
        btn_rect = QPushButton("Add rectangular part...")
        btn_rect.clicked.connect(self.on_add_rectangle_clicked)
        lv.addWidget(btn_import); lv.addWidget(btn_rect)

        sheet_box = QGroupBox("Sheet A (stock)")
        sf = QFormLayout(sheet_box)
        self.sp_sheet_w = self._dspin(2500, 1, 100000)
        self.sp_sheet_h = self._dspin(1250, 1, 100000)
        self.sp_sheet_qty = QSpinBox(); self.sp_sheet_qty.setRange(1, 100000); self.sp_sheet_qty.setValue(100)
        self.sp_margin = self._dspin(10, 0, 10000)
        sf.addRow("Length (mm)", self.sp_sheet_w)
        sf.addRow("Width (mm)", self.sp_sheet_h)
        sf.addRow("Sheets available", self.sp_sheet_qty)
        sf.addRow("Border margin (mm)", self.sp_margin)
        lv.addWidget(sheet_box)

        # Optional second stock size. When enabled the engine searches mixes of
        # A and B and returns the least-stock-area configuration, with the ranked
        # alternatives offered in the chooser above the preview.
        self.chk_sheet2 = QCheckBox("Add a second sheet size (B)")
        self.chk_sheet2.setToolTip(
            "Nest across two stock sizes and pick the mix with the least total "
            "sheet area. The border margin above applies to both sizes.")
        self.chk_sheet2.toggled.connect(self._on_sheet2_toggled)
        lv.addWidget(self.chk_sheet2)
        self.sheet2_box = QGroupBox("Sheet B (stock)")
        s2 = QFormLayout(self.sheet2_box)
        self.sp_sheet2_w = self._dspin(1250, 1, 100000)
        self.sp_sheet2_h = self._dspin(1250, 1, 100000)
        self.sp_sheet2_qty = QSpinBox(); self.sp_sheet2_qty.setRange(1, 100000); self.sp_sheet2_qty.setValue(100)
        s2.addRow("Length (mm)", self.sp_sheet2_w)
        s2.addRow("Width (mm)", self.sp_sheet2_h)
        s2.addRow("Sheets available", self.sp_sheet2_qty)
        self.sheet2_box.setVisible(False)
        lv.addWidget(self.sheet2_box)

        nest_box = QGroupBox("Nesting")
        nf = QFormLayout(nest_box)
        self.sp_spacing = self._dspin(3, 0, 1000)
        self.sp_kerf = self._dspin(0, 0, 1000)
        self.cb_rot = QComboBox()
        for label, _ in _ROT_OPTIONS:
            self.cb_rot.addItem(label)
        self.cb_strategy = QComboBox()
        for label, _ in _STRATEGY_OPTIONS:
            self.cb_strategy.addItem(label)
        self.sp_attempts = QSpinBox(); self.sp_attempts.setRange(1, 200); self.sp_attempts.setValue(6)
        self.sp_timelimit = self._dspin(20, 1, 600)
        nf.addRow("Part spacing (mm)", self.sp_spacing)
        nf.addRow("Kerf (mm)", self.sp_kerf)
        nf.addRow("Rotations", self.cb_rot)
        nf.addRow("Strategy", self.cb_strategy)
        nf.addRow("Attempts", self.sp_attempts)
        nf.addRow("Time limit (s)", self.sp_timelimit)
        lv.addWidget(nest_box)

        btn_adv = QPushButton("Advanced tolerances...")
        btn_adv.clicked.connect(self.on_advanced_clicked)
        lv.addWidget(btn_adv)

        self.btn_run = QPushButton("RUN NEST")
        self.btn_run.setStyleSheet("font-weight:bold; padding:10px;")
        self.btn_run.clicked.connect(self.run_nest)
        lv.addWidget(self.btn_run)
        lv.addStretch(1)

        # ---- Centre: preview ----
        centre = QWidget(); cv = QVBoxLayout(centre)
        cfg_row = QHBoxLayout()
        cfg_row.addWidget(QLabel("Configuration:"))
        self.cb_config = QComboBox()
        self.cb_config.setToolTip(
            "Stock-mix configurations, best (least total sheet area) first.\n"
            "Pick one to preview and export it.")
        self.cb_config.currentIndexChanged.connect(self._on_config_changed)
        cfg_row.addWidget(self.cb_config, 1)
        self.cfg_widget = QWidget(); self.cfg_widget.setLayout(cfg_row)
        self.cfg_widget.setVisible(False)
        self.canvas = PreviewCanvas()
        nav = QHBoxLayout()
        self.btn_prev = QPushButton("< Prev sheet"); self.btn_prev.clicked.connect(self.prev_sheet)
        self.btn_next = QPushButton("Next sheet >"); self.btn_next.clicked.connect(self.next_sheet)
        self.lbl_sheet = QLabel("Sheet -/-"); self.lbl_sheet.setAlignment(Qt.AlignCenter)
        btn_fit = QPushButton("Fit"); btn_fit.clicked.connect(self.canvas.fit_view)
        nav.addWidget(self.btn_prev); nav.addWidget(self.lbl_sheet)
        nav.addWidget(self.btn_next); nav.addWidget(btn_fit)
        self.progress = QProgressBar(); self.progress.setVisible(False)
        cv.addWidget(self.cfg_widget); cv.addWidget(self.canvas, 1)
        cv.addLayout(nav); cv.addWidget(self.progress)

        # ---- Right: parts + warnings ----
        right = QWidget(); rv = QVBoxLayout(right)
        rv.addWidget(QLabel("<b>Parts</b>  (double-click Qty to edit)"))
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Part", "Source", "Qty", "Area mm^2", "Status", "Notes"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.cellChanged.connect(self._on_cell_changed)
        rv.addWidget(self.table, 2)
        row = QHBoxLayout()
        btn_remove = QPushButton("Remove selected"); btn_remove.clicked.connect(self.remove_selected)
        btn_clear = QPushButton("Clear all"); btn_clear.clicked.connect(self.clear_parts)
        row.addWidget(btn_remove); row.addWidget(btn_clear)
        rv.addLayout(row)
        rv.addWidget(QLabel("<b>Warnings</b>"))
        self.warn_list = QListWidget()
        rv.addWidget(self.warn_list, 1)

        # ---- Bottom: summary + export ----
        bottom = QWidget(); bh = QHBoxLayout(bottom)
        self.lbl_summary = QLabel("No nest yet.")
        self.lbl_summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bh.addWidget(self.lbl_summary, 1)
        self.chk_common = QCheckBox("Common-line cut")
        self.chk_common.setToolTip(
            "Merge the coincident edges of butting parts into a single cut.\n"
            "Shared edges are placed on the COMMON_CUT layer. Set part "
            "spacing to 0 so parts share edges. Verify cut order before cutting.")
        self.btn_best = QPushButton("Best nests...")
        self.btn_best.setToolTip("Browse the highest-utilization nests and reload one into the preview.")
        self.btn_best.clicked.connect(self.on_best_nests_clicked)
        self.btn_export = QPushButton("Export DXF..."); self.btn_export.clicked.connect(self.on_export_dxf_clicked)
        self.btn_csv = QPushButton("Export report (CSV)..."); self.btn_csv.clicked.connect(self.on_export_csv_clicked)
        self.btn_export.setEnabled(False); self.btn_csv.setEnabled(False)
        bh.addWidget(self.chk_common); bh.addWidget(self.btn_best)
        bh.addWidget(self.btn_export); bh.addWidget(self.btn_csv)

        centre_and_bottom = QSplitter(Qt.Vertical)
        centre_and_bottom.addWidget(centre)
        centre_and_bottom.addWidget(bottom)
        centre_and_bottom.setStretchFactor(0, 1)

        splitter.addWidget(left)
        splitter.addWidget(centre_and_bottom)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([300, 640, 340])
        self.setCentralWidget(splitter)
        self.statusBar().showMessage("Ready.")

    def _build_menu(self) -> None:
        m = self.menuBar()
        filem = m.addMenu("&File")
        for text, slot in [
            ("Import DXF...", self.on_import_clicked),
            ("Add rectangular part...", self.on_add_rectangle_clicked),
            (None, None),
            ("Save job...", self.on_save_job_clicked),
            ("Load job...", self.on_load_job_clicked),
            (None, None),
            ("Best nests...", self.on_best_nests_clicked),
            (None, None),
            ("Export nested DXF...", self.on_export_dxf_clicked),
            ("Export report (CSV)...", self.on_export_csv_clicked),
            (None, None),
            ("Exit", self.close),
        ]:
            if text is None:
                filem.addSeparator(); continue
            act = QAction(text, self); act.triggered.connect(slot); filem.addAction(act)
        setm = m.addMenu("&Settings")
        a = QAction("Advanced tolerances...", self); a.triggered.connect(self.on_advanced_clicked)
        setm.addAction(a)
        helpm = m.addMenu("&Help")
        a2 = QAction("About", self); a2.triggered.connect(self._about); helpm.addAction(a2)

    @staticmethod
    def _dspin(val, lo, hi) -> QDoubleSpinBox:
        sp = QDoubleSpinBox(); sp.setRange(lo, hi); sp.setDecimals(2); sp.setValue(val)
        return sp

    def _about(self) -> None:
        QMessageBox.information(
            self, "About",
            f"{APP_NAME} {APP_VERSION}\n\nInternal 2D true-shape nesting tool.\n"
            "Clean-room build using ezdxf, Shapely, pyclipper, PySide6.")

    # -------------------------------------------------------------- inputs #
    def build_sheets(self) -> list[Sheet]:
        """Stock sizes to nest into: Sheet A, plus Sheet B when enabled."""
        margin = self.sp_margin.value()
        sheets = [Sheet("A", self.sp_sheet_w.value(), self.sp_sheet_h.value(),
                        quantity_available=self.sp_sheet_qty.value(), margin_mm=margin)]
        if self.chk_sheet2.isChecked():
            sheets.append(Sheet("B", self.sp_sheet2_w.value(), self.sp_sheet2_h.value(),
                                quantity_available=self.sp_sheet2_qty.value(), margin_mm=margin))
        return sheets

    def build_sheet(self) -> Sheet:
        return self.build_sheets()[0]

    def _on_sheet2_toggled(self, on: bool) -> None:
        self.sheet2_box.setVisible(on)

    def build_settings(self) -> NestingSettings:
        rot = _ROT_OPTIONS[self.cb_rot.currentIndex()][1]
        strat = _STRATEGY_OPTIONS[self.cb_strategy.currentIndex()][1]
        return NestingSettings(
            part_spacing_mm=self.sp_spacing.value(), kerf_mm=self.sp_kerf.value(),
            rotation_step_deg=rot, placement_strategy=strat,
            attempt_count=self.sp_attempts.value(), time_limit_sec=self.sp_timelimit.value(),
        )

    # ----------------------------------------------------------- importing #
    def on_import_clicked(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Import DXF", "", "DXF files (*.dxf)")
        if paths:
            self.import_paths(paths, ask_layers=True)

    def import_paths(self, paths, ask_layers=True) -> None:
        added = 0
        for path in paths:
            doc, notices = imp.open_dxf(path)
            if doc is None:
                self._show_notices(notices)
                continue
            summary = imp.summarize(doc, path)
            cut_layers = None
            if ask_layers:
                dlg = ImportDialog(summary, self.tolerances.snap_tolerance_mm, self)
                if dlg.exec() != QDialog.Accepted:
                    continue
                cut_layers = dlg.selected_layers()
                # Remember the operator's snap choice so it carries to the next
                # import and stays in sync with the Advanced tolerances dialog.
                snap = dlg.snap_tolerance()
                if snap != self.tolerances.snap_tolerance_mm:
                    self.tolerances = replace(self.tolerances, snap_tolerance_mm=snap)
            options = imp.ImportOptions(cut_layers=cut_layers, tolerances=self.tolerances)
            res = imp.extract(doc, path, options, summary)
            self.parts.extend(res.parts)
            if path not in self.source_files:
                self.source_files.append(path)
            added += len(res.parts)
            self._append_warnings(res.notices)
        self._refresh_part_table()
        self.statusBar().showMessage(f"Imported {added} part(s).")

    def on_add_rectangle_clicked(self) -> None:
        dlg = AddRectangleDialog(self)
        if dlg.exec() == QDialog.Accepted:
            name, length, width, qty, rot = dlg.values()
            self.add_rectangle(name, length, width, qty, rot)

    def add_rectangle(self, name, length, width, qty, allow_rotation=True) -> None:
        self.parts.append(make_rectangle_part(name, length, width, qty, allow_rotation))
        self._refresh_part_table()

    # -------------------------------------------------------------- nesting #
    def run_nest(self) -> None:
        if not self.parts:
            QMessageBox.information(self, "Nothing to nest", "Add or import some parts first.")
            return
        if self._worker and self._worker.isRunning():
            return
        sheets = self.build_sheets()
        settings = self.build_settings()
        self.btn_run.setEnabled(False)
        self.progress.setVisible(True); self.progress.setRange(0, 0)
        self.statusBar().showMessage("Nesting...")
        self._worker = NestWorker(list(self.parts), sheets, settings)
        self._pending_sheets = sheets
        self._pending_sheet = sheets[0]
        self._pending_parts = list(self.parts)
        self._pending_settings = settings
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_nest_done)
        self._worker.failed.connect(self._on_nest_failed)
        self._worker.start()

    def _on_progress(self, done, total, msg) -> None:
        if total:
            self.progress.setRange(0, total); self.progress.setValue(done)
        self.statusBar().showMessage(msg)

    def _on_nest_done(self, result) -> None:
        self.result = result
        self._active_result = result
        self.progress.setVisible(False)
        self.btn_run.setEnabled(True)
        self._populate_configs(result)
        self.canvas.set_result(result)
        self._update_sheet_nav()
        self._update_summary()
        self._append_warnings(result.notices, clear=True)
        self.btn_export.setEnabled(result.sheet_count_used > 0)
        self.btn_csv.setEnabled(result.sheet_count_used > 0)
        self._refresh_part_table()
        self.statusBar().showMessage(
            f"Done: {result.total_parts_nested} placed on {result.sheet_count_used} sheet(s) "
            f"in {result.runtime_sec:.1f}s.")
        self._log_best_nest(result)

    def _log_best_nest(self, result) -> None:
        """Offer a finished nest to the best-nests log (kept only if it ranks)."""
        if not result or result.sheet_count_used <= 0:
            return
        try:
            rec = make_record(
                result,
                self._pending_parts or self.parts,
                self._pending_sheets or self.build_sheets(),
                self._pending_settings or self.build_settings(),
                self.source_files,
            )
            self.history.consider(rec)
        except Exception:  # noqa: BLE001 - logging a nest must never break nesting
            log.exception("could not log nest to best-nests history")

    def _populate_configs(self, result) -> None:
        """Fill the configuration chooser when several stock mixes were tried."""
        cfgs = result.configurations
        self._suppress_config = True
        self.cb_config.clear()
        if len(cfgs) > 1:
            for c in cfgs:
                tag = "" if c.all_placed else "  [INCOMPLETE]"
                self.cb_config.addItem(
                    f"{c.label}  -  {c.sheets_used} sheet(s), {c.utilization * 100:.1f}% util, "
                    f"waste {c.waste_area / 1e6:.3f} m^2{tag}")
            self.cb_config.setCurrentIndex(0)
            self.cfg_widget.setVisible(True)
        else:
            self.cfg_widget.setVisible(False)
        self._suppress_config = False

    def _on_config_changed(self, idx: int) -> None:
        if self._suppress_config or not self.result or idx < 0:
            return
        cfgs = self.result.configurations
        if idx >= len(cfgs):
            return
        opt = cfgs[idx]
        self._active_result = opt.result
        self.canvas.set_result(opt.result)
        self._update_sheet_nav()
        self._update_summary()
        self._append_warnings(opt.result.notices, clear=True)
        self.btn_export.setEnabled(opt.result.sheet_count_used > 0)
        self.btn_csv.setEnabled(opt.result.sheet_count_used > 0)
        self.statusBar().showMessage(f"Showing configuration: {opt.label}")

    def _on_nest_failed(self, msg) -> None:
        self.progress.setVisible(False)
        self.btn_run.setEnabled(True)
        QMessageBox.critical(self, "Nesting failed", msg)

    # ------------------------------------------------------------- navigation #
    def prev_sheet(self) -> None:
        if self.result:
            self.canvas.render_sheet(self.canvas.current_sheet() - 1)
            self._update_sheet_nav()

    def next_sheet(self) -> None:
        if self.result:
            self.canvas.render_sheet(self.canvas.current_sheet() + 1)
            self._update_sheet_nav()

    def _update_sheet_nav(self) -> None:
        n = self.canvas.sheet_count()
        idx = self.canvas.current_sheet()
        cur = idx + 1 if n else 0
        text = f"Sheet {cur}/{n}"
        r = self._active_result or self.result
        if r and n:
            sh = r.sheet_at(idx)
            if sh is not None:
                text += f"  -  {sh.name} {sh.width_mm:g}x{sh.height_mm:g}"
        self.lbl_sheet.setText(text)

    # --------------------------------------------------------------- exports #
    def on_export_dxf_clicked(self) -> None:
        if not self.result:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export nested DXF", "nested.dxf",
                                              "DXF files (*.dxf)")
        if path:
            self.export_dxf(path)

    def export_dxf(self, path) -> dxe.ExportReport:
        opts = dxe.ExportOptions(common_line=self.chk_common.isChecked())
        res = self._active_result or self.result
        rep = dxe.export_nesting(res, path, None, opts)
        self._append_warnings(rep.notices)
        if rep.success:
            self.last_export_path = path
            msg = f"Exported {rep.cut_entities} cut profiles to {path}"
            if opts.common_line and rep.common_entities:
                msg += f" ({rep.common_entities} shared edges on COMMON_CUT)"
            self.statusBar().showMessage(msg)
        else:
            QMessageBox.warning(self, "Export blocked",
                                "The layout failed validation and was not written. "
                                "See warnings.")
        return rep

    def on_export_csv_clicked(self) -> None:
        if not self.result:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV report", "report.csv",
                                              "CSV files (*.csv)")
        if path:
            res = self._active_result or self.result
            rep = reports.build_report(res, self.parts, res.sheet or self._pending_sheet,
                                       export_path=self.last_export_path or "")
            reports.write_csv_report(rep, path)
            self.statusBar().showMessage(f"Report written to {path}")

    # ----------------------------------------------------------- job save/load #
    def on_save_job_clicked(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save job", "job.svnest.json",
                                              "CAD-N job (*.json)")
        if path:
            self.save_job(path)

    def save_job(self, path) -> None:
        last = None
        if self.result:
            last = {"sheets_used": self.result.sheet_count_used,
                    "total_utilization": self.result.total_utilization,
                    "export_path": self.last_export_path}
        job_io.save_job(path, os.path.basename(path), self.parts, self.build_sheets(),
                        self.build_settings(), self.source_files, last)
        self.job_path = path
        self.statusBar().showMessage(f"Job saved to {path}")

    def on_load_job_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load job", "", "CAD-N job (*.json)")
        if path:
            self.load_job(path)

    def load_job(self, path) -> None:
        job = job_io.load_job(path)
        self.parts = job.parts
        self.source_files = list(job.source_files)
        sheets = job.sheets or [job.sheet]
        a = sheets[0]
        self.sp_sheet_w.setValue(a.width_mm)
        self.sp_sheet_h.setValue(a.height_mm)
        self.sp_margin.setValue(a.margin_mm)
        self.sp_sheet_qty.setValue(min(int(a.quantity_available), 100000))
        if len(sheets) > 1:
            b = sheets[1]
            self.sp_sheet2_w.setValue(b.width_mm)
            self.sp_sheet2_h.setValue(b.height_mm)
            self.sp_sheet2_qty.setValue(min(int(b.quantity_available), 100000))
            self.chk_sheet2.setChecked(True)
        else:
            self.chk_sheet2.setChecked(False)
        self.sp_spacing.setValue(job.settings.part_spacing_mm)
        self.sp_kerf.setValue(job.settings.kerf_mm)
        self.sp_attempts.setValue(job.settings.attempt_count)
        self.sp_timelimit.setValue(job.settings.time_limit_sec)
        self.job_path = path
        self._refresh_part_table()
        self._append_warnings(job.notices, clear=True)
        self.statusBar().showMessage(f"Loaded job: {job.job_name} ({len(self.parts)} parts)")

    # -------------------------------------------------------------- best nests #
    def on_best_nests_clicked(self) -> None:
        if not self.history.records:
            QMessageBox.information(
                self, "Best nests",
                "No nests logged yet. Run a nest and the highest-utilization "
                "results are saved here automatically.")
            return
        dlg = BestNestsDialog(self.history, self)
        if dlg.exec() == QDialog.Accepted and dlg.selected_record is not None:
            self._load_nest_record(dlg.selected_record)

    def _load_nest_record(self, rec) -> None:
        """Restore a logged nest: its parts/sheets/settings snapshot plus the saved
        layout, so it can be previewed, exported, or re-run."""
        payload = rec.payload or {}
        self.parts = [Part.from_dict(d) for d in payload.get("parts", [])]
        self.source_files = list(rec.source_files)

        sheets = [Sheet.from_dict(d) for d in payload.get("sheets", [])]
        if sheets:
            a = sheets[0]
            self.sp_sheet_w.setValue(a.width_mm); self.sp_sheet_h.setValue(a.height_mm)
            self.sp_margin.setValue(a.margin_mm)
            self.sp_sheet_qty.setValue(min(int(a.quantity_available), 100000))
            if len(sheets) > 1:
                b = sheets[1]
                self.sp_sheet2_w.setValue(b.width_mm); self.sp_sheet2_h.setValue(b.height_mm)
                self.sp_sheet2_qty.setValue(min(int(b.quantity_available), 100000))
                self.chk_sheet2.setChecked(True)
            else:
                self.chk_sheet2.setChecked(False)

        s = NestingSettings.from_dict(payload.get("settings"))
        self.sp_spacing.setValue(s.part_spacing_mm); self.sp_kerf.setValue(s.kerf_mm)
        self.sp_attempts.setValue(s.attempt_count); self.sp_timelimit.setValue(s.time_limit_sec)
        for i, (_, val) in enumerate(_ROT_OPTIONS):
            if val == s.rotation_step_deg:
                self.cb_rot.setCurrentIndex(i); break
        for i, (_, val) in enumerate(_STRATEGY_OPTIONS):
            if val == s.placement_strategy:
                self.cb_strategy.setCurrentIndex(i); break

        result = result_from_dict(payload.get("result", {}))
        self.result = result
        self._active_result = result
        self._pending_sheets = sheets
        self._pending_sheet = sheets[0] if sheets else None
        self._pending_parts = list(self.parts)
        self._pending_settings = s
        self._populate_configs(result)
        self.canvas.set_result(result)
        self._update_sheet_nav()
        self._update_summary()
        self.btn_export.setEnabled(result.sheet_count_used > 0)
        self.btn_csv.setEnabled(result.sheet_count_used > 0)
        self._refresh_part_table()
        self.statusBar().showMessage(f"Loaded best nest: {rec.label}")

    # --------------------------------------------------------------- tables #
    def on_advanced_clicked(self) -> None:
        dlg = SettingsDialog(self.tolerances, self)
        if dlg.exec() == QDialog.Accepted:
            self.tolerances = dlg.tolerances()
            self.statusBar().showMessage("Tolerances updated (apply on next import).")

    def remove_selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            if 0 <= r < len(self.parts):
                del self.parts[r]
        self._refresh_part_table()

    def clear_parts(self) -> None:
        self.parts = []
        self.result = None
        self._active_result = None
        self.cfg_widget.setVisible(False)
        self.btn_export.setEnabled(False); self.btn_csv.setEnabled(False)
        self.canvas.show_placeholder("Import parts and run a nest to see the layout.")
        self._refresh_part_table(); self._update_summary()

    def _refresh_part_table(self) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.parts))
        nested_by_id = {}
        if self.result:
            for pl in self.result.placements:
                nested_by_id[pl.part_id] = nested_by_id.get(pl.part_id, 0) + 1
        for r, p in enumerate(self.parts):
            self._set_ro(r, 0, p.name)
            self._set_ro(r, 1, os.path.basename(p.source_file) if p.source_file else "(manual)")
            qty = QTableWidgetItem(str(p.quantity))
            qty.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)
            self.table.setItem(r, 2, qty)
            self._set_ro(r, 3, f"{p.area:.1f}")
            if p.has_error:
                status = "ERROR"
            elif self.result is not None:
                status = f"nested {nested_by_id.get(p.id, 0)}/{p.quantity}"
            elif p.notices:
                status = "check"
            else:
                status = "ready"
            self._set_ro(r, 4, status)
            self._set_ro(r, 5, str(len(p.notices)) if p.notices else "")
        self.table.blockSignals(False)
        self.table.resizeColumnsToContents()

    def _set_ro(self, r, c, text) -> None:
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self.table.setItem(r, c, item)

    def _on_cell_changed(self, row, col) -> None:
        if col != 2 or row >= len(self.parts):
            return
        try:
            q = max(0, int(self.table.item(row, 2).text()))
        except ValueError:
            q = self.parts[row].quantity
        self.parts[row].quantity = q
        self.table.blockSignals(True)
        self.table.item(row, 2).setText(str(q))
        self.table.blockSignals(False)

    # -------------------------------------------------------------- summary #
    def _update_summary(self) -> None:
        r = self._active_result or self.result
        if not r:
            self.lbl_summary.setText("No nest yet. Set up parts and sheet, then Run Nest.")
            return
        utils = " | ".join(f"S{i+1}:{u*100:.0f}%" for i, u in enumerate(r.utilization_by_sheet))
        remnants = ", ".join(f"{x:.0f}" for x in r.remnant_length_by_sheet)
        if r.sheets:
            sheet_area = sum(s.usable_area for s in r.sheets)
        elif self._pending_sheet:
            sheet_area = self._pending_sheet.usable_area * r.sheet_count_used
        else:
            sheet_area = 0.0
        scrap = sheet_area - sum(p.area for p in r.placements)
        mix = ""
        if r.configurations and r.sheets:
            counts: dict[str, int] = {}
            for s in r.sheets:
                counts[s.name] = counts.get(s.name, 0) + 1
            mix = ("<b>Mix:</b> " + " + ".join(f"{n}x {nm}" for nm, n in sorted(counts.items()))
                   + " &nbsp; ")
        self.lbl_summary.setText(
            f"{mix}"
            f"<b>Sheets:</b> {r.sheet_count_used} &nbsp; "
            f"<b>Nested:</b> {r.total_parts_nested} &nbsp; "
            f"<b>Unnested:</b> {r.total_parts_failed} &nbsp; "
            f"<b>Total util:</b> {r.total_utilization*100:.1f}% &nbsp; "
            f"<b>Scrap:</b> {max(0.0, scrap):.0f} mm^2<br>"
            f"<b>Per sheet:</b> {utils} &nbsp; <b>Remnant len (mm):</b> {remnants} &nbsp; "
            f"<b>Runtime:</b> {r.runtime_sec:.1f}s")

    # ------------------------------------------------------------- warnings #
    def _append_warnings(self, notices, clear=False) -> None:
        if clear:
            self.warn_list.clear()
        for n in notices:
            icon = {"info": "i", "warning": "!", "error": "X"}.get(n.severity.value, "-")
            item = QListWidgetItem(f"[{icon}] {n.message}")
            if n.severity is Severity.ERROR:
                item.setForeground(Qt.red)
            elif n.severity is Severity.WARNING:
                item.setForeground(Qt.darkYellow)
            if n.detail:
                item.setToolTip(n.detail)
            self.warn_list.addItem(item)
        self.warn_list.scrollToBottom()

    def _show_notices(self, notices) -> None:
        self._append_warnings(notices)
        errs = [n for n in notices if n.severity is Severity.ERROR]
        if errs:
            QMessageBox.warning(self, "Import problem", errs[0].message)
