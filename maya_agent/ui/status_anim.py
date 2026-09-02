"""Animated status indicators for Maya Agent chat UI."""

from __future__ import annotations

from typing import Optional

from maya_agent.ui.palette import SPINNER_FRAMES
from maya_agent.utils.maya_compat import import_qt

_SPINNER = SPINNER_FRAMES


def create_animated_status(parent=None):
    """Build AnimatedStatusBar with the current Qt binding."""
    QtCore, QtGui, QtWidgets, _ = import_qt()

    class IndeterminateBar(QtWidgets.QWidget):
        """Thin sliding highlight bar shown while the agent is busy."""

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setFixedHeight(2)
            self._phase = 0
            self._timer = QtCore.QTimer(self)
            self._timer.setInterval(40)
            self._timer.timeout.connect(self._tick)
            self.hide()

        def start(self):
            self._phase = 0
            self.show()
            self._timer.start()

        def stop(self):
            self._timer.stop()
            self.hide()
            self.update()

        def _tick(self):
            self._phase = (self._phase + 3) % 200
            self.update()

        def paintEvent(self, _event):
            painter = QtGui.QPainter(self)
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            w, h = self.width(), self.height()
            painter.fillRect(0, 0, w, h, QtGui.QColor("#2e2f36"))

            bar_w = max(36, w // 5)
            x = int((w + bar_w) * self._phase / 200) - bar_w
            grad = QtGui.QLinearGradient(x, 0, x + bar_w, 0)
            grad.setColorAt(0.0, QtGui.QColor(0, 0, 0, 0))
            grad.setColorAt(0.35, QtGui.QColor("#5b8fc7"))
            grad.setColorAt(0.65, QtGui.QColor("#2f7d5b"))
            grad.setColorAt(1.0, QtGui.QColor(0, 0, 0, 0))
            painter.fillRect(x, 0, bar_w, h, grad)

    class AnimatedStatusBar(QtWidgets.QWidget):
        """Spinner + animated text + optional progress strip."""

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setObjectName("statusBar")
            self._mode = "idle"
            self._base_text = "就绪"
            self._tool_name = ""
            self._frame = 0

            outer = QtWidgets.QVBoxLayout(self)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.setSpacing(4)

            row = QtWidgets.QHBoxLayout()
            row.setContentsMargins(2, 0, 2, 0)
            row.setSpacing(6)

            self.spinner = QtWidgets.QLabel("")
            self.spinner.setObjectName("statusSpinner")
            self.spinner.setFixedWidth(16)
            self.spinner.setAlignment(QtCore.Qt.AlignCenter)
            self.spinner.hide()

            self.text_label = QtWidgets.QLabel("就绪")
            self.text_label.setObjectName("statusLabel")

            row.addWidget(self.spinner, 0)
            row.addWidget(self.text_label, 1)
            outer.addLayout(row)

            self.progress = IndeterminateBar(self)
            outer.addWidget(self.progress)

            self._timer = QtCore.QTimer(self)
            self._timer.setInterval(120)
            self._timer.timeout.connect(self._tick)

        def setText(self, text: str) -> None:
            """Static status (QLabel-compatible)."""
            self.stop_animation()
            self.text_label.setText(text)

        def text(self) -> str:
            return self.text_label.text()

        def set_idle(self, text: str = "就绪") -> None:
            self.stop_animation()
            self.text_label.setText(text)

        def set_thinking(self) -> None:
            self._start_mode("thinking", "思考中")

        def set_tool(self, name: str) -> None:
            self._tool_name = name or "tool"
            self._start_mode("tool", f"执行工具: {self._tool_name}")

        def set_error(self, text: str = "出错") -> None:
            self.stop_animation()
            self.spinner.setText("✕")
            self.spinner.setStyleSheet("color: #e09090; font-size: 12px;")
            self.spinner.show()
            self.text_label.setText(text)

        def stop_animation(self) -> None:
            self._timer.stop()
            self.progress.stop()
            self.spinner.hide()
            self.spinner.setStyleSheet("")
            self._mode = "idle"

        def _start_mode(self, mode: str, base_text: str) -> None:
            self._mode = mode
            self._base_text = base_text
            self._frame = 0
            self.spinner.setStyleSheet("color: #8fd4a8; font-size: 13px;")
            self.spinner.show()
            self.progress.start()
            if not self._timer.isActive():
                self._timer.start()
            self._tick()

        def _tick(self) -> None:
            self._frame += 1
            spin = _SPINNER[self._frame % len(_SPINNER)]
            self.spinner.setText(spin)

            dots = "." * (self._frame % 4)
            if self._mode == "thinking":
                self.text_label.setText(f"{self._base_text}{dots}")
            elif self._mode == "tool":
                self.text_label.setText(f"{self._base_text}{dots}")
            else:
                self.text_label.setText(self._base_text)

    return AnimatedStatusBar(parent)


def create_typing_indicator(parent=None):
    """Animated '正在思考…' label for assistant bubbles."""
    QtCore, _, QtWidgets, _binding = import_qt()

    class TypingIndicator(QtWidgets.QLabel):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setObjectName("typingIndicator")
            self._frame = 0
            self._timer = QtCore.QTimer(self)
            self._timer.setInterval(380)
            self._timer.timeout.connect(self._tick)
            self.setStyleSheet(
                "QLabel#typingIndicator {"
                "  background: transparent; border: none;"
                "  color: #8a8a93; font-size: 12px;"
                "}"
            )
            self.hide()

        def start(self) -> None:
            self._frame = 0
            self.show()
            self._tick()
            if not self._timer.isActive():
                self._timer.start()

        def stop(self) -> None:
            self._timer.stop()
            self.hide()

        def _tick(self) -> None:
            dots = "." * (self._frame % 4)
            self.setText(f"正在思考{dots}")
            self._frame += 1

    return TypingIndicator(parent)
