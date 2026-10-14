"""Collapsible model-thinking row for chat bubbles."""

from __future__ import annotations

from maya_agent.ui import chat_format
from maya_agent.ui.palette import SPINNER_FRAMES
from maya_agent.ui.qt_bind import QtCore, QtGui, QtWidgets

_SPINNER = SPINNER_FRAMES

class ThinkingRow(QtWidgets.QFrame):
    """Collapsible block for model reasoning / thinking content."""

    _PREVIEW_CHARS = 840
    _STREAM_TAIL_CHARS = 1200
    # Cap streaming body height so growing thought text cannot bounce the chat.
    _STREAM_DETAIL_MAX_H = 112

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("thinkingRow")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setMinimumWidth(0)
        self.setMaximumWidth(16777215)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Maximum
        )
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(4)
        self.title = QtWidgets.QLabel("思考中…")
        self.title.setWordWrap(False)
        self.title.setMinimumWidth(0)
        self.title.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.detail = QtWidgets.QLabel("")
        self.detail.setWordWrap(True)
        self.detail.setMinimumWidth(0)
        self.detail.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred
        )
        self.detail.setTextFormat(QtCore.Qt.PlainText)
        self.detail.setObjectName("thinkingDetail")
        self.detail.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.detail.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.expand_btn = QtWidgets.QPushButton("展开全部 ▾")
        self.expand_btn.setObjectName("thinkingExpandBtn")
        self.expand_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.expand_btn.setFlat(True)
        self.expand_btn.setFixedHeight(22)
        self.expand_btn.clicked.connect(self._toggle_expand)
        self.expand_btn.hide()
        lay.addWidget(self.title)
        lay.addWidget(self.detail)
        lay.addWidget(self.expand_btn, 0, QtCore.Qt.AlignLeft)
        self._text = ""
        self._done = False
        self._expanded = True
        self._anim_frame = 0
        self._detail_cache = None
        self._stream_detail_h = 0
        self._anim_timer = QtCore.QTimer(self)
        self._anim_timer.setInterval(220)
        self._anim_timer.timeout.connect(self._tick)
        self.setStyleSheet(self._stylesheet(running=True, pulse=False))

    def _stylesheet(self, *, running: bool, pulse: bool = False) -> str:
        if running:
            bg = "#2a3040" if pulse else "#262c3a"
            border = "#5a6a8a" if pulse else "#3e4a62"
            title = "#b0c4e0"
            detail = "#8a9bb8"
            btn = "#7a90b0"
        else:
            bg = "#242830"
            border = "#3a4252"
            title = "#9aabcc"
            detail = "#7a879c"
            btn = "#6a7a96"
        return f"""
            QFrame#thinkingRow {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 8px;
            }}
            QFrame#thinkingRow QLabel {{
                background: transparent;
                border: none;
                color: {title};
                font-size: 12px;
            }}
            QFrame#thinkingRow QLabel#thinkingDetail {{
                color: {detail};
                font-size: 11px;
                font-weight: 400;
            }}
            QFrame#thinkingRow QPushButton#thinkingExpandBtn {{
                background: transparent;
                border: none;
                color: {btn};
                font-size: 11px;
                font-weight: 500;
                text-align: left;
                padding: 0 2px;
                min-height: 18px;
            }}
            QFrame#thinkingRow QPushButton#thinkingExpandBtn:hover {{
                color: {title};
                text-decoration: underline;
            }}
        """

    def _tick(self) -> None:
        self._anim_frame += 1
        spin = _SPINNER[self._anim_frame % len(_SPINNER)]
        # Fixed-width dots pad so title sizeHint never changes.
        n = self._anim_frame % 4
        dots = "." * n + "\u00a0" * (3 - n)
        self.title.setText(f"{spin} 思考中{dots}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Keep labels within this row; the row itself fills the bubble width.
        inner = max(80, int(self.width()) - 24)
        if self.title.maximumWidth() != inner:
            self.title.setMaximumWidth(inner)
        if self.detail.maximumWidth() != inner:
            self.detail.setMaximumWidth(inner)

    def _escape_html(self, text: str) -> str:
        return chat_format.escape(text or "").replace("\n", "<br/>")

    def _stream_display_text(self, text: str) -> str:
        if len(text) <= self._STREAM_TAIL_CHARS:
            return text
        return "…\n" + text[-self._STREAM_TAIL_CHARS :]

    def _fit_detail_height(self) -> None:
        """Pin detail to an exact height after streaming (kills leftover fixed gaps)."""
        if not self.detail.isVisible() or not (self._text or "").strip():
            self.detail.setMinimumHeight(0)
            self.detail.setMaximumHeight(0)
            self.detail.setFixedHeight(0)
            return
        inner = max(80, int(self.width() or 0) - 24)
        try:
            mw = int(self.detail.maximumWidth() or 0)
            if 80 <= mw < 16777215:
                inner = min(inner, mw)
        except Exception:
            pass
        self.detail.setMinimumHeight(0)
        self.detail.setMaximumHeight(16777215)
        h = 0
        try:
            h = int(self.detail.heightForWidth(inner) or 0)
        except Exception:
            h = 0
        if h <= 0:
            try:
                h = int(self.detail.sizeHint().height() or 0)
            except Exception:
                h = 0
        h = max(16, h)
        self.detail.setFixedHeight(h)

    def _refresh_detail(self) -> None:
        text = self._text or ""
        if not text:
            self.detail.hide()
            self.expand_btn.hide()
            self._detail_cache = None
            self._stream_detail_h = 0
            self._fit_detail_height()
            return
        if not self._done:
            shown = self._stream_display_text(text)
            if shown == self._detail_cache:
                return
            self._detail_cache = shown
            self.detail.setTextFormat(QtCore.Qt.PlainText)
            self.detail.setText(shown)
            self.detail.show()
            # Grow detail height monotonically up to a hard cap — never shrink.
            hint = max(int(self.detail.sizeHint().height() or 0), 20)
            h = min(
                self._STREAM_DETAIL_MAX_H,
                max(hint, int(self._stream_detail_h or 0)),
            )
            self._stream_detail_h = h
            if self.detail.height() != h:
                self.detail.setFixedHeight(h)
            self.expand_btn.hide()
            return

        # Unlock stream cap, then exact-fit to final copy.
        self._stream_detail_h = 0
        long = len(text) > self._PREVIEW_CHARS
        if long and not self._expanded:
            shown = text[: self._PREVIEW_CHARS].rstrip() + "…"
            self.expand_btn.setText("展开全部 ▾")
            self.expand_btn.show()
        else:
            shown = text
            if long:
                self.expand_btn.setText("收起 ▴")
                self.expand_btn.show()
            else:
                self.expand_btn.hide()
        cache_key = ("done", self._expanded, shown)
        if cache_key != self._detail_cache:
            self._detail_cache = cache_key
            self.detail.setTextFormat(QtCore.Qt.RichText)
            self.detail.setText(self._escape_html(shown))
        self.detail.show()
        self._fit_detail_height()

    def append(self, piece: str) -> None:
        if not piece:
            return
        self._text += piece
        self._done = False
        self._expanded = True
        if not self._anim_timer.isActive():
            self.title.setText("◐ 思考中\u00a0\u00a0\u00a0")
            self._anim_timer.start()
        self._refresh_detail()

    def set_full(self, text: str, *, done: bool = True) -> None:
        self._text = text or ""
        if done:
            self.set_done()
        else:
            self._done = False
            self._refresh_detail()

    def set_done(self) -> None:
        if not self._text:
            self.hide()
            self._anim_timer.stop()
            return
        self._anim_timer.stop()
        self._done = True
        # Collapse long thinking by default once finished
        self._expanded = len(self._text) <= self._PREVIEW_CHARS
        self.setStyleSheet(self._stylesheet(running=False))
        self.title.setText("💭 思考过程")
        self._detail_cache = None
        self._refresh_detail()
        self.show()

    def _toggle_expand(self) -> None:
        self._expanded = not self._expanded
        self._detail_cache = None
        self._refresh_detail()
        self.detail.updateGeometry()
        parent = self.parentWidget()
        while parent is not None:
            if hasattr(parent, "_scroll_to_bottom"):
                parent._scroll_to_bottom()
                break
            parent = parent.parentWidget()

