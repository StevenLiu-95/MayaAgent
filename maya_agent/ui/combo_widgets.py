"""Toolbar QComboBox with programmatic dropdown arrow (Maya Qt safe)."""

from __future__ import annotations

from typing import Optional

from maya_agent.utils.maya_compat import import_qt

_ARROW_WIDTH = 22


def create_toolbar_combo(parent=None, *, editable: bool = False):
    """Return a QComboBox subclass that always paints a visible dropdown arrow."""
    QtCore, QtGui, QtWidgets, _ = import_qt()

    class ToolbarComboBox(QtWidgets.QComboBox):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setObjectName("toolbarCombo")
            self.setEditable(editable)
            self._hover = False
            self.setAttribute(QtCore.Qt.WA_Hover, True)
            if editable:
                self._fix_line_edit()

        def _fix_line_edit(self) -> None:
            editor = self.lineEdit()
            if editor is None:
                return
            editor.setObjectName("toolbarComboEdit")
            editor.setFrame(False)
            editor.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
            editor.installEventFilter(self)

        def eventFilter(self, obj, event):
            if self.isEditable() and obj is self.lineEdit():
                if event.type() == QtCore.QEvent.Resize:
                    QtCore.QTimer.singleShot(0, self._sync_line_edit_geometry)
            return super().eventFilter(obj, event)

        def _sync_line_edit_geometry(self) -> None:
            editor = self.lineEdit()
            if editor is None:
                return
            margin_x = 6
            margin_y = 2
            editor.setGeometry(
                margin_x,
                margin_y,
                max(20, self.width() - _ARROW_WIDTH - margin_x - 2),
                max(16, self.height() - margin_y * 2),
            )

        def resizeEvent(self, event):
            super().resizeEvent(event)
            if self.isEditable():
                self._sync_line_edit_geometry()
            self.update()

        def enterEvent(self, event):
            self._hover = True
            self.update()
            super().enterEvent(event)

        def leaveEvent(self, event):
            self._hover = False
            self.update()
            super().leaveEvent(event)

        def showEvent(self, event):
            super().showEvent(event)
            if self.isEditable():
                QtCore.QTimer.singleShot(0, self._sync_line_edit_geometry)

        def paintEvent(self, event):
            super().paintEvent(event)
            painter = QtGui.QPainter(self)
            try:
                self._paint_dropdown(painter)
            finally:
                painter.end()

        def _paint_dropdown(self, painter: QtGui.QPainter) -> None:
            w, h = self.width(), self.height()
            if w < _ARROW_WIDTH + 8 or h < 8:
                return

            drop_left = w - _ARROW_WIDTH
            radius = 5
            drop_rect = QtCore.QRectF(drop_left + 0.5, 1.5, _ARROW_WIDTH - 2, h - 3)

            path = QtGui.QPainterPath()
            path.addRoundedRect(drop_rect, radius, radius)
            bg = QtGui.QColor("#3a3b44" if self._hover else "#32333c")
            painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
            painter.fillPath(path, bg)

            pen = QtGui.QPen(QtGui.QColor("#40414c"))
            pen.setWidthF(1.0)
            painter.setPen(pen)
            painter.drawLine(drop_left, 5, drop_left, h - 5)

            cx = drop_left + _ARROW_WIDTH * 0.5
            cy = h * 0.5 + 0.5
            tri = QtGui.QPolygonF(
                [
                    QtCore.QPointF(cx - 5.0, cy - 2.0),
                    QtCore.QPointF(cx + 5.0, cy - 2.0),
                    QtCore.QPointF(cx, cy + 3.5),
                ]
            )
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor("#e8e8ea" if self._hover else "#b4b4be"))
            painter.drawPolygon(tri)

    return ToolbarComboBox(parent)
