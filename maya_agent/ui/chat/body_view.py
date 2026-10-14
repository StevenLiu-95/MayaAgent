"""Chat bubble body (QTextBrowser) with streaming height fit."""

from __future__ import annotations

from maya_agent.ui import chat_format
from maya_agent.ui.qt_bind import QtCore, QtGui, QtWidgets

class BodyView(QtWidgets.QTextBrowser):
    """Read-only rich text that grows with content (no inner scroll)."""

    _WIDTH_EPS = 6
    _BUBBLE_PAD = 28  # bubble left+right content margins

    def __init__(self, role: str, parent=None):
        super().__init__(parent)
        self.setObjectName("bubbleBody")
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setOpenExternalLinks(False)
        self.setOpenLinks(False)
        try:
            self.anchorClicked.connect(self._on_anchor)
        except Exception:
            self.setOpenExternalLinks(True)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        try:
            self.setLineWrapMode(QtWidgets.QTextEdit.WidgetWidth)
        except Exception:
            pass
        self.setMinimumWidth(0)
        self.setMinimumHeight(0)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
        )
        # Bubble grows with content — never keep an inner scroll offset.
        self._lock_scrollbars()
        # Allow QTextDocument to break long tokens inside the bubble width
        try:
            opt = self.document().defaultTextOption()
            opt.setWrapMode(QtGui.QTextOption.WrapAtWordBoundaryOrAnywhere)
            self.document().setDefaultTextOption(opt)
        except Exception:
            pass
        self._tighten_document_chrome()
        self.setAutoFillBackground(False)
        self.viewport().setAutoFillBackground(False)
        color = {
            "user": "#f2f7ff",
            "error": "#f0c0c0",
            "assistant": "#e8e8ea",
        }.get(role, "#e8e8ea")
        self.setStyleSheet(
            f"""
            QTextBrowser#bubbleBody {{
                background-color: transparent;
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
                min-height: 0px;
                color: {color};
                font-size: 13px;
            }}
            """
        )
        # Prevent palette from painting a solid base behind text
        pal = self.palette()
        pal.setColor(QtGui.QPalette.Base, QtCore.Qt.transparent)
        pal.setColor(QtGui.QPalette.Window, QtCore.Qt.transparent)
        self.setPalette(pal)
        self.viewport().setPalette(pal)
        self._stream_cache = None
        self._stream_height = 0
        self._layout_width = 0
        self._refit_guard = False
        self._streaming = False

    def minimumSizeHint(self):
        # Critical: default QTextBrowser sizeHint uses unwrapped doc width
        # and will push the chat row past the dialog edge.
        h = int(self._stream_height or self.height() or 16)
        return QtCore.QSize(0, max(h, 16))

    def sizeHint(self):
        w = int(self._layout_width or self.width() or 0)
        h = int(self._stream_height or self.height() or 16)
        return QtCore.QSize(max(w, 0), max(h, 16))

    def hasHeightForWidth(self):
        # Height is owned by setFixedHeight(_refit). Returning True lets some
        # Qt layouts re-measure with a narrow width and invent tall empty gaps.
        return False

    def heightForWidth(self, width: int) -> int:
        return max(int(self._stream_height or self.height() or 16), 16)

    def wheelEvent(self, event):
        # Do not scroll text inside the bubble — drive the chat panel instead.
        from maya_agent.ui.qt_wheel import redirect_wheel_to_parent_scroll

        if redirect_wheel_to_parent_scroll(self, event):
            return
        event.ignore()

    def scrollContentsBy(self, dx, dy):
        # Block vertical offset even if scrollbar value changes.
        super().scrollContentsBy(dx, 0)

    def _lock_scrollbars(self) -> None:
        try:
            vbar = self.verticalScrollBar()
            vbar.setEnabled(False)
            vbar.setRange(0, 0)
            vbar.setValue(0)
        except Exception:
            pass
        try:
            hbar = self.horizontalScrollBar()
            hbar.setEnabled(False)
            hbar.setRange(0, 0)
            hbar.setValue(0)
        except Exception:
            pass

    def _on_anchor(self, url):
        from maya_agent.ui.image_viewer import open_external_url

        open_external_url(url)

    def _tighten_document_chrome(self) -> None:
        """Zero document/frame margins (setHtml/setPlainText can restore defaults)."""
        doc = self.document()
        try:
            doc.setDocumentMargin(0)
        except Exception:
            pass
        try:
            root = doc.rootFrame()
            fmt = root.frameFormat()
            fmt.setMargin(0)
            fmt.setPadding(0)
            fmt.setBorder(0)
            root.setFrameFormat(fmt)
        except Exception:
            pass

    def set_html(self, html: str):
        self._streaming = False
        self._stream_cache = None
        self._stream_height = 0
        self._layout_width = 0
        self.setHtml(html or "")
        self._tighten_document_chrome()
        self._refit(streaming=False)

    def set_plain(self, text: str):
        self._streaming = False
        self._stream_cache = None
        self._stream_height = 0
        self._layout_width = 0
        self.setPlainText(text or "")
        self._tighten_document_chrome()
        self._refit(streaming=False)

    def finish_streaming(self) -> bool:
        """Leave streaming mode and allow height to shrink to exact content."""
        self._streaming = False
        self._stream_cache = None
        self._stream_height = 0
        self._tighten_document_chrome()
        return self._refit(streaming=False)

    def set_plain_streaming(self, text: str):
        """Fast live-update path: plain text + incremental insert when possible."""
        text = text or ""
        prev = self._stream_cache
        if prev is not None and text == prev:
            return
        self._streaming = True
        # Soft-break long runs so wrap width stays inside the bubble.
        display = chat_format.soft_break_long_runs(text)
        prev_display = (
            chat_format.soft_break_long_runs(prev) if prev is not None else None
        )
        if (
            prev_display is not None
            and display.startswith(prev_display)
            and (len(display) - len(prev_display)) <= 800
        ):
            cursor = self.textCursor()
            end = getattr(QtGui.QTextCursor, "End", None)
            if end is None:
                end = QtGui.QTextCursor.MoveOperation.End
            cursor.movePosition(end)
            cursor.insertText(display[len(prev_display) :])
            self.setTextCursor(cursor)
        else:
            self.setPlainText(display)
            self._tighten_document_chrome()
        self._stream_cache = text
        self._refit(streaming=True)

    def _viewport_content_width(self) -> int:
        """Walk up to the chat QScrollArea for a stable target width."""
        p = self.parentWidget()
        while p is not None:
            # BodyView → Bubble → MessageBlock → container → viewport → scroll
            if isinstance(p, QtWidgets.QScrollArea) or p.objectName() == "chatScroll":
                try:
                    vp = p.viewport() if hasattr(p, "viewport") else p
                    # margins + avatar + spacing + bubble pad + side gutter
                    inner = int(vp.width()) - 120
                    if inner >= 120:
                        return inner
                except Exception:
                    pass
                break
            p = p.parentWidget()
        return 0

    def _bubble_content_widths(self) -> tuple:
        """Return (painted_width, max_width) inside the parent bubble, or (0, 0)."""
        bubble = self.parentWidget()
        if bubble is None:
            return 0, 0
        painted = int(bubble.width() or 0) - self._BUBBLE_PAD
        capped = 0
        try:
            mw = int(bubble.maximumWidth() or 0) - self._BUBBLE_PAD
            if 120 <= mw < 16777215 - self._BUBBLE_PAD:
                capped = mw
        except Exception:
            pass
        return painted, capped

    def _resolve_text_width(self, *, streaming: bool) -> int:
        """Stable content width; lock while streaming (prevents jitter)."""
        # Once streaming has a width, keep it — any change reflows height.
        if streaming and self._layout_width >= 120:
            return int(self._layout_width)

        painted, capped = self._bubble_content_widths()
        self_w = int(self.width() or 0) - 4
        vp = int(self.viewport().width() or 0)

        if streaming:
            # Conservative: narrowest reliable width so mid-stream text never clips.
            candidates = [w for w in (painted, capped, self_w, vp) if w >= 120]
            width = min(candidates) if candidates else int(self._layout_width or 240)
        else:
            # Final fit: prefer the bubble's *painted* width so height can shrink.
            # Taking min(stale_self, bubble) left permanent empty gaps under short
            # lines after the bubble grew wider than the first measure.
            if painted >= 120:
                width = painted
            elif capped >= 120:
                width = capped
            elif self_w >= 120:
                width = self_w
            elif vp >= 120:
                width = vp
            elif self._layout_width >= 120:
                width = int(self._layout_width)
            else:
                width = 240

        prev_w = int(self._layout_width or 0)
        if streaming and prev_w and abs(width - prev_w) < self._WIDTH_EPS:
            return prev_w
        if (
            not streaming
            and prev_w
            and width >= prev_w
            and abs(width - prev_w) < self._WIDTH_EPS
        ):
            return prev_w
        return width

    def _document_height(self, width: int) -> int:
        """Content height for ``width`` (tight; skip trailing empty blocks)."""
        doc = self.document()
        doc.setTextWidth(max(int(width), 1))
        bottom = 0.0
        try:
            layout = doc.documentLayout()
            if layout is not None:
                # Force a layout pass before reading block geometry.
                _ = layout.documentSize()
                block = doc.begin()
                while block.isValid():
                    nxt = block.next()
                    text = block.text() or ""
                    # Trailing empty block is a common setHtml leftover that
                    # adds a full blank line inside the bubble.
                    if (
                        not nxt.isValid()
                        and not text.strip()
                        and block.blockNumber() > 0
                    ):
                        break
                    rect = layout.blockBoundingRect(block)
                    bottom = max(bottom, float(rect.bottom()))
                    block = nxt
                if bottom <= 0:
                    bottom = float(layout.documentSize().height() or 0)
        except Exception:
            bottom = 0.0
        if bottom <= 0:
            try:
                bottom = float(doc.size().height() or 0)
            except Exception:
                bottom = 0.0
        # Guard against Maya/Qt occasionally reporting a page-sized height for
        # a short single paragraph (leaves a huge empty band in the bubble).
        try:
            plain = self.toPlainText() or ""
            if plain and "\n" not in plain.rstrip("\n"):
                fm = self.fontMetrics()
                br = fm.boundingRect(
                    QtCore.QRect(0, 0, max(int(width), 1), 0),
                    int(QtCore.Qt.TextWordWrap),
                    plain,
                )
                fm_h = float(br.height() or 0)
                if fm_h > 0 and bottom <= 0:
                    bottom = fm_h
                elif fm_h > 0 and bottom > fm_h * 2.5 + 12.0:
                    # Absurdly tall vs font metrics — clamp, keep small slack
                    # for HTML line-height / paragraph margins.
                    bottom = fm_h + 8.0
        except Exception:
            pass
        return max(int(bottom + 0.999), 16)

    def _refit(self, *, streaming: bool = False) -> bool:
        """Recompute height. Returns True if height changed."""
        if self._refit_guard:
            return False
        width = self._resolve_text_width(streaming=streaming)
        self._layout_width = width

        self._refit_guard = True
        try:
            # Streaming: tiny pad. Final: 2px for sub-pixel / focus outline.
            pad = 2 if streaming else 2
            h = self._document_height(width) + pad
            if streaming:
                # Strictly monotonic while streaming — never shrink.
                h = max(h, int(self._stream_height or 0))
                self._stream_height = h
            else:
                self._stream_height = 0
            if self.height() != h or self.minimumHeight() != h:
                self.setMinimumHeight(h)
                self.setMaximumHeight(h)
                self.setFixedHeight(h)
                self.updateGeometry()
                changed = True
            else:
                changed = False
            self._lock_scrollbars()
            return changed
        finally:
            self._refit_guard = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._lock_scrollbars()
        # Streaming width/height is locked — ignore resize thrash entirely.
        if self._streaming or self._stream_cache is not None:
            return
        new_w = self._resolve_text_width(streaming=False)
        prev_w = int(self._layout_width or 0)
        if prev_w and abs(new_w - prev_w) < self._WIDTH_EPS:
            return
        self._refit(streaming=False)

    def showEvent(self, event):
        super().showEvent(event)
        self._lock_scrollbars()
        if self._streaming or self._stream_cache is not None:
            return
        QtCore.QTimer.singleShot(0, lambda: self._refit(streaming=False))

