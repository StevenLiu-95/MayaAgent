"""Flow layout — wraps child widgets onto the next row when width is exceeded."""

from __future__ import annotations

from maya_agent.utils.maya_compat import import_qt


def create_flow_layout(parent=None, *, hspacing: int = 6, vspacing: int = 6):
    """Return a FlowLayout bound to the current Qt binding."""
    QtCore, _QtGui, QtWidgets, _ = import_qt()

    class FlowLayout(QtWidgets.QLayout):
        def __init__(self, parent=None, hspacing: int = 6, vspacing: int = 6):
            super().__init__(parent)
            self._items = []
            self._hspacing = int(hspacing)
            self._vspacing = int(vspacing)
            self.setContentsMargins(0, 0, 0, 0)

        def addItem(self, item):
            self._items.append(item)

        def count(self):
            return len(self._items)

        def itemAt(self, index):
            if 0 <= index < len(self._items):
                return self._items[index]
            return None

        def takeAt(self, index):
            if 0 <= index < len(self._items):
                return self._items.pop(index)
            return None

        def expandingDirections(self):
            return QtCore.Qt.Orientations(QtCore.Qt.Orientation(0))

        def hasHeightForWidth(self):
            return True

        def heightForWidth(self, width):
            return self._do_layout(QtCore.QRect(0, 0, width, 0), test_only=True)

        def setGeometry(self, rect):
            super().setGeometry(rect)
            self._do_layout(rect, test_only=False)

        def sizeHint(self):
            return self.minimumSize()

        def minimumSize(self):
            size = QtCore.QSize()
            for item in self._items:
                size = size.expandedTo(item.minimumSize())
            left, top, right, bottom = self.getContentsMargins()
            size += QtCore.QSize(left + right, top + bottom)
            return size

        def _horizontal_spacing(self) -> int:
            return self._hspacing

        def _vertical_spacing(self) -> int:
            return self._vspacing

        def _do_layout(self, rect, *, test_only: bool) -> int:
            left, top, right, bottom = self.getContentsMargins()
            effective = rect.adjusted(+left, +top, -right, -bottom)
            x = effective.x()
            y = effective.y()
            line_height = 0
            space_x = self._horizontal_spacing()
            space_y = self._vertical_spacing()

            for item in self._items:
                wid = item.widget()
                hint = item.sizeHint()
                next_x = x + hint.width() + space_x
                if next_x - space_x > effective.right() and line_height > 0:
                    x = effective.x()
                    y = y + line_height + space_y
                    next_x = x + hint.width() + space_x
                    line_height = 0
                if not test_only:
                    item.setGeometry(QtCore.QRect(QtCore.QPoint(x, y), hint))
                x = next_x
                line_height = max(line_height, hint.height())

            return y + line_height - rect.y() + bottom

    return FlowLayout(parent, hspacing=hspacing, vspacing=vspacing)
