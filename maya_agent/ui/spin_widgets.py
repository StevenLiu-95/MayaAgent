"""Toolbar spin boxes with programmatic up/down arrows (Maya Qt safe)."""

from __future__ import annotations

from maya_agent.utils.maya_compat import import_qt

_BTN_WIDTH = 22


def create_toolbar_spin(parent=None, *, decimal: bool = False):
    """
    Return QSpinBox / QDoubleSpinBox that paints flat up/down arrows.

    Matches ToolbarComboBox look: no native button chrome (broken in Maya Qt).
    Explicitly sizes the internal line edit so digits are not clipped.
    """
    QtCore, QtGui, QtWidgets, _ = import_qt()
    Base = QtWidgets.QDoubleSpinBox if decimal else QtWidgets.QSpinBox

    class ToolbarSpinBox(Base):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setObjectName("toolbarSpin")
            self.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
            self.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            self._hover = False
            self._hover_up = False
            self._hover_down = False
            self.setAttribute(QtCore.Qt.WA_Hover, True)
            self.setMouseTracking(True)
            editor = self.lineEdit()
            if editor is not None:
                editor.setObjectName("toolbarSpinEdit")
                editor.setFrame(False)
                editor.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
                editor.installEventFilter(self)
            QtCore.QTimer.singleShot(0, self._sync_line_edit_geometry)

        def eventFilter(self, obj, event):
            if obj is self.lineEdit() and event.type() == QtCore.QEvent.Resize:
                QtCore.QTimer.singleShot(0, self._sync_line_edit_geometry)
            return super().eventFilter(obj, event)

        def _sync_line_edit_geometry(self) -> None:
            """Keep digit area wide; reserve only the right strip for arrows."""
            editor = self.lineEdit()
            if editor is None:
                return
            margin_x = 8
            margin_y = 2
            text_w = max(28, self.width() - _BTN_WIDTH - margin_x - 4)
            text_h = max(16, self.height() - margin_y * 2)
            editor.setGeometry(margin_x, margin_y, text_w, text_h)
            # Clear margins — geometry already reserves arrow space
            editor.setTextMargins(0, 0, 0, 0)

        def _btn_rect(self) -> "QtCore.QRect":
            return QtCore.QRect(
                self.width() - _BTN_WIDTH, 0, _BTN_WIDTH, self.height()
            )

        def _hit_zone(self, pos) -> str:
            """Return 'up', 'down', or ''."""
            rect = self._btn_rect()
            if not rect.contains(pos):
                return ""
            mid = rect.center().y()
            return "up" if pos.y() <= mid else "down"

        def enterEvent(self, event):
            self._hover = True
            self.update()
            super().enterEvent(event)

        def leaveEvent(self, event):
            self._hover = False
            self._hover_up = False
            self._hover_down = False
            self.update()
            super().leaveEvent(event)

        def mouseMoveEvent(self, event):
            pos = event.pos() if hasattr(event, "pos") else event.position().toPoint()
            zone = self._hit_zone(pos)
            up = zone == "up"
            down = zone == "down"
            if up != self._hover_up or down != self._hover_down:
                self._hover_up = up
                self._hover_down = down
                self.update()
            super().mouseMoveEvent(event)

        def mousePressEvent(self, event):
            if event.button() == QtCore.Qt.LeftButton:
                pos = (
                    event.pos()
                    if hasattr(event, "pos")
                    else event.position().toPoint()
                )
                zone = self._hit_zone(pos)
                if zone == "up":
                    self.stepUp()
                    event.accept()
                    return
                if zone == "down":
                    self.stepDown()
                    event.accept()
                    return
            super().mousePressEvent(event)

        def resizeEvent(self, event):
            super().resizeEvent(event)
            self._sync_line_edit_geometry()
            self.update()

        def showEvent(self, event):
            super().showEvent(event)
            QtCore.QTimer.singleShot(0, self._sync_line_edit_geometry)

        def paintEvent(self, event):
            super().paintEvent(event)
            painter = QtGui.QPainter(self)
            try:
                self._paint_buttons(painter)
            finally:
                painter.end()

        def _paint_buttons(self, painter: QtGui.QPainter) -> None:
            w, h = self.width(), self.height()
            if w < _BTN_WIDTH + 8 or h < 12:
                return

            left = w - _BTN_WIDTH
            painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

            drop_rect = QtCore.QRectF(left + 0.5, 1.5, _BTN_WIDTH - 2, h - 3)
            path = QtGui.QPainterPath()
            path.addRoundedRect(drop_rect, 5, 5)
            bg = QtGui.QColor("#3a3b44" if self._hover else "#32333c")
            painter.fillPath(path, bg)

            pen = QtGui.QPen(QtGui.QColor("#40414c"))
            pen.setWidthF(1.0)
            painter.setPen(pen)
            painter.drawLine(left, 5, left, h - 5)

            cx = left + _BTN_WIDTH * 0.5
            mid_y = h * 0.5

            painter.setPen(QtGui.QPen(QtGui.QColor("#40414c")))
            painter.drawLine(int(left + 4), int(mid_y), int(w - 4), int(mid_y))

            def _tri(cy: float, point_up: bool, active: bool) -> None:
                half_w, half_h = 4.5, 3.0
                if point_up:
                    pts = [
                        QtCore.QPointF(cx, cy - half_h),
                        QtCore.QPointF(cx - half_w, cy + half_h * 0.6),
                        QtCore.QPointF(cx + half_w, cy + half_h * 0.6),
                    ]
                else:
                    pts = [
                        QtCore.QPointF(cx - half_w, cy - half_h * 0.6),
                        QtCore.QPointF(cx + half_w, cy - half_h * 0.6),
                        QtCore.QPointF(cx, cy + half_h),
                    ]
                color = "#e8e8ea" if active else "#b4b4be"
                painter.setPen(QtCore.Qt.NoPen)
                painter.setBrush(QtGui.QColor(color))
                painter.drawPolygon(QtGui.QPolygonF(pts))

            _tri(mid_y - h * 0.22, True, self._hover_up)
            _tri(mid_y + h * 0.22, False, self._hover_down)

    return ToolbarSpinBox(parent)
