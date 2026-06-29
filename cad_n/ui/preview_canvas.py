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
from shapely.geometry import LineString, Polygon

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
        self._fit_rect = QRectF()
        self._sheet_rect = QRectF()
        self.show_placeholder("Import parts to preview profiles, then run a nest.")

    # -- public API --------------------------------------------------------- #
    def set_result(self, result, sheet=None) -> None:
        self._result = result
        # Fallback stock size when a per-sheet size is unavailable.
        self._sheet = sheet or (result.sheet if result else None)
        self._sheet_index = 0
        self.render_sheet(0)

    def set_import_preview(self, parts) -> None:
        """Tile imported part profiles for visual verification before nesting."""
        self._result = None
        self._sheet = None
        self._sheet_index = 0
        profiles = list(self._iter_import_profiles(parts))
        if not profiles:
            self.show_placeholder("No importable part profiles were found.")
            return

        self._scene.clear()
        bounds = [poly.bounds for _part, poly, _internal in profiles]
        minx = min(b[0] for b in bounds)
        miny = min(b[1] for b in bounds)
        maxx = max(b[2] for b in bounds)
        maxy = max(b[3] for b in bounds)
        width = max(maxx - minx, 1.0)
        height = max(maxy - miny, 1.0)
        max_dim = max(width, height)
        margin = max(10.0, min(max_dim * 0.04, 120.0))

        font = QFont("Segoe UI")
        font.setPointSizeF(max(4.0, min(14.0, max_dim / 160.0)))

        for k, (part, poly, internal) in enumerate(profiles):
            bx0, by0, bx1, by1 = poly.bounds
            self._draw_profile(
                poly, internal, part.name, font, k,
                tooltip=(
                    f"{part.name}\n"
                    f"Qty {part.quantity:g}\n"
                    f"{bx1 - bx0:.1f} x {by1 - by0:.1f} mm\n"
                    f"Area {part.area:.1f} mm^2"
                ),
            )

        rect = QRectF(
            minx - margin,
            -(maxy + margin),
            width + 2 * margin,
            height + 2 * margin,
        )
        self.setSceneRect(rect)
        self._fit_rect = rect
        self._sheet_rect = rect
        self.fit_view()

    def sheet_count(self) -> int:
        return self._result.sheet_count_used if self._result else 0

    def current_sheet(self) -> int:
        return self._sheet_index

    def show_placeholder(self, text: str) -> None:
        self._scene.clear()
        t = self._scene.addText(text, QFont("Segoe UI", 12))
        t.setDefaultTextColor(QColor("#7f8c8d"))
        self.setSceneRect(t.boundingRect())
        self._fit_rect = self._scene.sceneRect()
        self._sheet_rect = self._scene.sceneRect()
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
        placements = self._result.placements_on(index)
        for k, pl in enumerate(placements):
            self._draw_profile(
                pl.polygon_world,
                getattr(pl, "internal_world", ()),
                pl.part_name,
                font,
                k,
                tooltip=f"{pl.part_name}  rot {pl.rotation_deg:g} deg",
            )

        margin_box = QRectF(-sheet.width_mm * 0.05, -sheet.height_mm * 1.05,
                            sheet.width_mm * 1.1, sheet.height_mm * 1.1)
        self.setSceneRect(margin_box)
        self._sheet_rect = margin_box
        self._fit_rect = self._parts_fit_rect(placements, sheet) or margin_box
        self.fit_view()

    def fit_view(self) -> None:
        rect = self._fit_rect if self._fit_rect.isValid() else self._scene.sceneRect()
        if rect.isValid():
            self.fitInView(rect, Qt.KeepAspectRatio)

    def fit_sheet_view(self) -> None:
        rect = self._sheet_rect if self._sheet_rect.isValid() else self._scene.sceneRect()
        if rect.isValid():
            self.fitInView(rect, Qt.KeepAspectRatio)

    # -- helpers ------------------------------------------------------------ #
    @staticmethod
    def _iter_import_profiles(parts):
        for part in parts:
            if part.geom is None or part.geom.is_empty:
                continue
            instances = []
            if isinstance(getattr(part, "metadata", None), dict):
                instances = part.metadata.get("preview_instances") or []
            if instances:
                for inst in instances:
                    try:
                        poly = Polygon(inst["outer"], inst.get("holes", []))
                    except Exception:  # noqa: BLE001
                        continue
                    if not poly.is_empty:
                        yield part, poly, []
                continue
            internal = [
                LineString(path)
                for path in getattr(part, "internal_paths", ())
                if len(path) >= 2
            ]
            yield part, part.geom, internal

    def _draw_profile(self, poly, internal, label_text: str, font: QFont,
                      palette_index: int, tooltip: str = "") -> None:
        item = QGraphicsPathItem(self._poly_path(poly))
        color = QColor(_PALETTE[palette_index % len(_PALETTE)])
        item.setBrush(QBrush(color))
        item.setPen(QPen(QColor("#1c2833"), 0))
        if tooltip:
            item.setToolTip(tooltip)
        self._scene.addItem(item)
        # Preserved internal cut lines (micro-joints / chase outlines), drawn
        # on top of the fill so the operator can see them.
        for line in internal:
            lpath = self._line_path(line)
            if lpath is None:
                continue
            litem = QGraphicsPathItem(lpath)
            litem.setPen(QPen(QColor("#922b21"), 0))
            litem.setBrush(QBrush(Qt.NoBrush))
            self._scene.addItem(litem)
        c = poly.representative_point()
        label = self._scene.addText(label_text, font)
        label.setDefaultTextColor(QColor("#1c2833"))
        br = label.boundingRect()
        label.setPos(c.x - br.width() / 2, -c.y - br.height() / 2)

    @staticmethod
    def _parts_fit_rect(placements, sheet) -> QRectF | None:
        if not placements:
            return None
        minx = min(pl.polygon_world.bounds[0] for pl in placements)
        miny = min(pl.polygon_world.bounds[1] for pl in placements)
        maxx = max(pl.polygon_world.bounds[2] for pl in placements)
        maxy = max(pl.polygon_world.bounds[3] for pl in placements)
        width = max(maxx - minx, 1.0)
        height = max(maxy - miny, 1.0)
        pad = max(20.0, max(width, height) * 0.18,
                  max(sheet.width_mm, sheet.height_mm) * 0.025)
        return QRectF(minx - pad, -(maxy + pad),
                      width + 2 * pad, height + 2 * pad)

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
