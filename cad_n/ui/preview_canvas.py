"""Nesting preview canvas (doc 12.1 / preview requirements).

A QGraphicsView that draws one sheet at a time: the sheet boundary, the usable
(margin) rectangle, placed parts (filled, holes shown), and part labels. Mouse
wheel zooms about the cursor; left-drag pans. CAD Y-up is preserved by negating
Y for display.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
)

_PALETTE = [
    "#7fb3d5", "#7dcea0", "#f7dc6f", "#f1948a", "#bb8fce", "#f8c471",
    "#85c1e9", "#82e0aa", "#f5b7b1", "#d7bde2", "#a3e4d7", "#fad7a0",
]


class PreviewCanvas(QGraphicsView):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QBrush(QColor("#f4f6f7")))
        self._result = None
        self._sheet = None
        self._sheet_index = 0
        self.show_placeholder("Import parts and run a nest to see the layout.")

    # -- public API --------------------------------------------------------- #
    def set_result(self, result, sheet=None) -> None:
        self._result = result
        # Fallback stock size when a per-sheet size is unavailable.
        self._sheet = sheet or (result.sheet if result else None)
        self._sheet_index = 0
        self.render_sheet(0)

    def sheet_count(self) -> int:
        return self._result.sheet_count_used if self._result else 0

    def current_sheet(self) -> int:
        return self._sheet_index

    def show_placeholder(self, text: str) -> None:
        self._scene.clear()
        t = self._scene.addText(text, QFont("Segoe UI", 12))
        t.setDefaultTextColor(QColor("#7f8c8d"))
        self.setSceneRect(t.boundingRect())
        self.resetTransform()

    def render_sheet(self, index: int) -> None:
        if not self._result or not self._sheet:
            return
        n = max(self._result.sheet_count_used, 0)
        if n == 0:
            self.show_placeholder("No parts were nested.")
            return
        index = max(0, min(index, n - 1))
        self._sheet_index = index
        self._scene.clear()
        # Each physical sheet may be a different stock size.
        sheet = self._result.sheet_at(index) or self._sheet

        # Sheet boundary.
        self._scene.addRect(
            QRectF(0, -sheet.height_mm, sheet.width_mm, sheet.height_mm),
            QPen(QColor("#2c3e50"), 0), QBrush(QColor("white")),
        )
        # Usable (margin) rectangle, dashed.
        m = sheet.margin_mm
        if m > 0:
            pen = QPen(QColor("#aab7b8"), 0)
            pen.setStyle(Qt.DashLine)
            self._scene.addRect(
                QRectF(m, -(sheet.height_mm - m), sheet.usable_width, sheet.usable_height),
                pen, QBrush(Qt.NoBrush),
            )

        # Parts.
        font = QFont("Segoe UI")
        font.setPointSizeF(max(6.0, sheet.width_mm / 90.0))
        for k, pl in enumerate(self._result.placements_on(index)):
            item = QGraphicsPathItem(self._poly_path(pl.polygon_world))
            color = QColor(_PALETTE[k % len(_PALETTE)])
            item.setBrush(QBrush(color))
            item.setPen(QPen(QColor("#1c2833"), 0))
            item.setToolTip(f"{pl.part_name}  rot {pl.rotation_deg:g} deg")
            self._scene.addItem(item)
            # Preserved internal cut lines (micro-joints / chase outlines), drawn
            # on top of the fill so the operator can see them.
            for line in getattr(pl, "internal_world", ()):
                lpath = self._line_path(line)
                if lpath is None:
                    continue
                litem = QGraphicsPathItem(lpath)
                litem.setPen(QPen(QColor("#922b21"), 0))
                litem.setBrush(QBrush(Qt.NoBrush))
                self._scene.addItem(litem)
            c = pl.polygon_world.representative_point()
            label = self._scene.addText(pl.part_name, font)
            label.setDefaultTextColor(QColor("#1c2833"))
            br = label.boundingRect()
            label.setPos(c.x - br.width() / 2, -c.y - br.height() / 2)

        margin_box = QRectF(-sheet.width_mm * 0.05, -sheet.height_mm * 1.05,
                            sheet.width_mm * 1.1, sheet.height_mm * 1.1)
        self.setSceneRect(margin_box)
        self.fit_view()

    def fit_view(self) -> None:
        if self._scene.sceneRect().isValid():
            self.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)

    # -- helpers ------------------------------------------------------------ #
    @staticmethod
    def _poly_path(poly) -> QPainterPath:
        path = QPainterPath()
        path.setFillRule(Qt.OddEvenFill)

        def add_ring(coords):
            pts = list(coords)
            if not pts:
                return
            path.moveTo(QPointF(pts[0][0], -pts[0][1]))
            for x, y in pts[1:]:
                path.lineTo(QPointF(x, -y))
            path.closeSubpath()

        add_ring(poly.exterior.coords)
        for interior in poly.interiors:
            add_ring(interior.coords)
        return path

    @staticmethod
    def _line_path(line):
        coords = list(getattr(line, "coords", []))
        if len(coords) < 2:
            return None
        path = QPainterPath()
        path.moveTo(QPointF(coords[0][0], -coords[0][1]))
        for x, y in coords[1:]:
            path.lineTo(QPointF(x, -y))
        return path

    # -- interaction -------------------------------------------------------- #
    def wheelEvent(self, event) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.fit_view()
