"""Widget-based chat panel with Qt-safe rich text bubbles."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from maya_agent.ui import chat_format
from maya_agent.ui.palette import SPINNER_FRAMES
from maya_agent.ui.status_anim import create_typing_indicator
from maya_agent.utils.maya_compat import import_qt
from maya_agent.llm.base import format_turn_meta

_SPINNER = SPINNER_FRAMES


def _image_b64(img: Any) -> str:
    if isinstance(img, dict):
        return str(img.get("data_b64") or "")
    return str(getattr(img, "data_b64", "") or "")


def _image_dicts(images: Optional[List[Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for img in images or []:
        if isinstance(img, dict):
            if img.get("data_b64"):
                out.append(
                    {
                        "mime": img.get("mime") or "image/png",
                        "data_b64": img["data_b64"],
                        "name": img.get("name") or "",
                    }
                )
        elif getattr(img, "data_b64", ""):
            out.append(img.to_dict())
    return out


def create_chat_panel(parent=None):
    """Build ChatPanel bound to the current Qt binding and return an instance."""
    QtCore, QtGui, QtWidgets, _ = import_qt()

    class Avatar(QtWidgets.QLabel):
        def __init__(self, text: str, bg: str, fg: str = "#ffffff", parent=None):
            super().__init__(text, parent)
            self.setFixedSize(32, 32)
            self.setAlignment(QtCore.Qt.AlignCenter)
            self.setStyleSheet(
                f"""
                QLabel {{
                    background-color: {bg};
                    color: {fg};
                    border-radius: 16px;
                    font-size: 11px;
                    font-weight: 700;
                }}
                """
            )

    class Bubble(QtWidgets.QFrame):
        def __init__(self, kind: str, parent=None):
            super().__init__(parent)
            self.setObjectName(f"bubble_{kind}")
            self.setFrameShape(QtWidgets.QFrame.NoFrame)
            self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
            self.setMinimumWidth(0)
            self.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum
            )
            colors = {
                "user": ("#2c4f73", "#5a8fc4"),
                "assistant": ("#2c2d36", "#4a4b56"),
                "error": ("#3a2424", "#7a4040"),
            }
            bg, border = colors.get(kind, ("#25262c", "#3a3b44"))
            self.setStyleSheet(
                f"""
                QFrame#bubble_{kind} {{
                    background-color: {bg};
                    border: 1px solid {border};
                    border-radius: 14px;
                }}
                """
            )

    class BodyView(QtWidgets.QTextBrowser):
        """Read-only rich text that grows with content (no inner scroll)."""

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
            self.setMinimumWidth(0)
            self.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum
            )
            # Allow QTextDocument to break long tokens inside the bubble width
            try:
                opt = self.document().defaultTextOption()
                opt.setWrapMode(QtGui.QTextOption.WrapAtWordBoundaryOrAnywhere)
                self.document().setDefaultTextOption(opt)
            except Exception:
                pass
            self.document().setDocumentMargin(0)
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

        def _on_anchor(self, url):
            from maya_agent.ui.image_viewer import open_external_url

            open_external_url(url)

        def set_html(self, html: str):
            self._stream_cache = None
            self._stream_height = 0
            self.setHtml(html or "")
            self._refit(monotonic=False)

        def set_plain(self, text: str):
            self._stream_cache = None
            self._stream_height = 0
            self.setPlainText(text or "")
            self._refit(monotonic=False)

        def set_plain_streaming(self, text: str):
            """Fast live-update path: plain text + incremental insert when possible."""
            text = text or ""
            prev = self._stream_cache
            if prev is not None and text == prev:
                return
            if (
                prev
                and text.startswith(prev)
                and (len(text) - len(prev)) <= 800
            ):
                cursor = self.textCursor()
                end = getattr(QtGui.QTextCursor, "End", None)
                if end is None:
                    end = QtGui.QTextCursor.MoveOperation.End
                cursor.movePosition(end)
                cursor.insertText(text[len(prev) :])
                self.setTextCursor(cursor)
            else:
                self.setPlainText(text)
            self._stream_cache = text
            # Always measure from the document (no estimate/real oscillation).
            # Height is monotonic while streaming so bubbles never bounce upward.
            self._refit(monotonic=True)

        def _content_width(self) -> int:
            return max(self.viewport().width(), self.width() - 4, 160)

        def _refit(self, *, monotonic: bool = False):
            width = self._content_width()
            self.document().setTextWidth(width)
            # Keep height tight — large pads here show as empty bottom margin in bubbles
            h = max(int(self.document().size().height()) + 2, 16)
            if monotonic:
                h = max(h, int(getattr(self, "_stream_height", 0) or 0))
                self._stream_height = h
            else:
                self._stream_height = 0
            if self.height() != h:
                self.setFixedHeight(h)

        def resizeEvent(self, event):
            super().resizeEvent(event)
            # Width changes need a real reflow; keep streaming height monotonic
            # so a temporary narrow/wide pass does not yank the bubble upward.
            self._refit(monotonic=self._stream_cache is not None)

        def showEvent(self, event):
            super().showEvent(event)
            QtCore.QTimer.singleShot(
                0, lambda: self._refit(monotonic=self._stream_cache is not None)
            )
    class ToolRow(QtWidgets.QFrame):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setObjectName("toolRow")
            self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
            self.setMinimumWidth(0)
            self.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum
            )
            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(10, 8, 10, 8)
            lay.setSpacing(4)
            self.title = QtWidgets.QLabel("⚙ …")
            self.title.setWordWrap(True)
            self.title.setMinimumWidth(0)
            self.title.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
            self.bar = QtWidgets.QProgressBar()
            self.bar.setObjectName("toolProgress")
            self.bar.setRange(0, 100)
            self.bar.setValue(0)
            self.bar.setTextVisible(True)
            self.bar.setFormat("%p%")
            self.bar.setFixedHeight(16)
            self.bar.setMinimumWidth(0)
            self.bar.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
            )
            self.bar.hide()
            self.detail = QtWidgets.QLabel("")
            self.detail.setWordWrap(True)
            self.detail.setMinimumWidth(0)
            self.detail.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred
            )
            self.detail.setTextFormat(QtCore.Qt.RichText)
            self.detail.setObjectName("toolDetail")
            self.detail.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
            self.detail.setTextInteractionFlags(
                QtCore.Qt.TextSelectableByMouse | QtCore.Qt.LinksAccessibleByMouse
            )
            self.detail.setOpenExternalLinks(True)
            self.expand_btn = QtWidgets.QPushButton("展开全部")
            self.expand_btn.setObjectName("toolExpandBtn")
            self.expand_btn.setCursor(QtCore.Qt.PointingHandCursor)
            self.expand_btn.setFlat(True)
            self.expand_btn.setFixedHeight(22)
            self.expand_btn.clicked.connect(self._toggle_expand)
            self.expand_btn.hide()
            lay.addWidget(self.title)
            lay.addWidget(self.bar)
            lay.addWidget(self.detail)
            self._image_host = QtWidgets.QWidget()
            self._image_host.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
            self._image_lay = QtWidgets.QHBoxLayout(self._image_host)
            self._image_lay.setContentsMargins(0, 2, 0, 0)
            self._image_lay.setSpacing(6)
            self._image_lay.addStretch(1)
            self._image_host.hide()
            lay.addWidget(self._image_host)
            lay.addWidget(self.expand_btn, 0, QtCore.Qt.AlignLeft)
            self._running_name = ""
            self._progress_pct = None
            self._progress_status = ""
            self._anim_frame = 0
            self._anim_timer = QtCore.QTimer(self)
            self._anim_timer.setInterval(130)
            self._anim_timer.timeout.connect(self._tick_running)
            self._preview_html = ""
            self._full_html = ""
            self._expanded = False

        def set_images(self, images: Optional[List[Any]]) -> None:
            from maya_agent.llm.base import ImageAttachment
            from maya_agent.ui.image_viewer import make_clickable_thumb

            while self._image_lay.count() > 1:
                item = self._image_lay.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()
            shown = 0
            gallery: List[Any] = []
            for img in images or []:
                if isinstance(img, dict):
                    if not img.get("data_b64"):
                        continue
                    gallery.append(img)
                elif getattr(img, "data_b64", ""):
                    gallery.append(img)
            for idx, img in enumerate(gallery):
                if isinstance(img, dict):
                    att = ImageAttachment.from_dict(img)
                else:
                    att = img
                label = make_clickable_thumb(
                    att,
                    edge=96,
                    fixed_w=96,
                    fixed_h=72,
                    parent=self._image_host,
                    gallery=gallery,
                    index=idx,
                    tooltip=att.name or "视口截图",
                    stylesheet=(
                        "QLabel { background:#1a1b20; border:1px solid #5a4a30;"
                        " border-radius:6px; }"
                    ),
                )
                self._image_lay.insertWidget(self._image_lay.count() - 1, label)
                shown += 1
            self._image_host.setVisible(shown > 0)

        def _running_stylesheet(self, pulse: bool) -> str:
            bg = "#403828" if pulse else "#3a3428"
            border = "#9a8048" if pulse else "#6a5a38"
            return f"""
                QFrame#toolRow {{
                    background-color: {bg};
                    border: 1px solid {border};
                    border-radius: 8px;
                }}
                QFrame#toolRow QLabel {{
                    background: transparent;
                    border: none;
                    color: #e0c888;
                    font-size: 12px;
                }}
                QFrame#toolRow QLabel#toolDetail {{
                    color: #b0a080;
                    font-size: 11px;
                }}
                QFrame#toolRow QProgressBar#toolProgress {{
                    background-color: #2a2618;
                    border: 1px solid #6a5a38;
                    border-radius: 5px;
                    text-align: center;
                    color: #f0e0b0;
                    font-size: 10px;
                    font-weight: 600;
                    max-height: 16px;
                    min-height: 14px;
                }}
                QFrame#toolRow QProgressBar#toolProgress::chunk {{
                    background-color: qlineargradient(
                        x1:0, y1:0, x2:1, y2:0,
                        stop:0 #8a7040, stop:0.5 #c9a84a, stop:1 #e0c868
                    );
                    border-radius: 4px;
                }}
                QFrame#toolRow QPushButton#toolExpandBtn {{
                    background: transparent;
                    border: none;
                    color: #c0a868;
                    font-size: 11px;
                    font-weight: 500;
                    text-align: left;
                    padding: 0 2px;
                    min-height: 18px;
                }}
                QFrame#toolRow QPushButton#toolExpandBtn:hover {{
                    color: #e0c888;
                    text-decoration: underline;
                }}
            """

        def _done_stylesheet(self, ok: bool) -> str:
            if ok:
                return """
                    QFrame#toolRow {
                        background-color: #24352c;
                        border: 1px solid #3f6a50;
                        border-radius: 8px;
                    }
                    QFrame#toolRow QLabel {
                        background: transparent;
                        border: none;
                        color: #9fd4b0;
                        font-size: 12px;
                        font-weight: 600;
                    }
                    QFrame#toolRow QLabel#toolDetail {
                        color: #b8c8be;
                        font-size: 11px;
                        font-weight: 400;
                    }
                    QFrame#toolRow QPushButton#toolExpandBtn {
                        background: transparent;
                        border: none;
                        color: #7ab892;
                        font-size: 11px;
                        font-weight: 500;
                        text-align: left;
                        padding: 0 2px;
                        min-height: 18px;
                    }
                    QFrame#toolRow QPushButton#toolExpandBtn:hover {
                        color: #9fd4b0;
                        text-decoration: underline;
                    }
                """
            return """
                QFrame#toolRow {
                    background-color: #3a2828;
                    border: 1px solid #6a4040;
                    border-radius: 8px;
                }
                QFrame#toolRow QLabel {
                    background: transparent;
                    border: none;
                    color: #e09090;
                    font-size: 12px;
                    font-weight: 600;
                }
                QFrame#toolRow QLabel#toolDetail {
                    color: #c8a0a0;
                    font-size: 11px;
                    font-weight: 400;
                }
                QFrame#toolRow QPushButton#toolExpandBtn {
                    background: transparent;
                    border: none;
                    color: #d09090;
                    font-size: 11px;
                    font-weight: 500;
                    text-align: left;
                    padding: 0 2px;
                    min-height: 18px;
                }
                QFrame#toolRow QPushButton#toolExpandBtn:hover {
                    color: #e0b0b0;
                    text-decoration: underline;
                }
            """

        def _tick_running(self) -> None:
            self._anim_frame += 1
            spin = _SPINNER[self._anim_frame % len(_SPINNER)]
            dots = "." * (self._anim_frame % 4)
            suffix = self._progress_suffix()
            self.title.setText(
                f"{spin} 正在执行  {self._running_name}{suffix}{dots}"
            )
            self.setStyleSheet(self._running_stylesheet(self._anim_frame % 2 == 0))

        def _progress_suffix(self) -> str:
            if self._progress_status:
                return " · " + str(self._progress_status)
            return ""

        def set_running(self, name: str):
            self._running_name = name
            self._progress_pct = None
            self._progress_status = ""
            self._anim_frame = 0
            self.setStyleSheet(self._running_stylesheet(False))
            self.title.setText(f"◐ 正在执行  {name}")
            self.bar.hide()
            self.bar.setValue(0)
            self.detail.setText("")
            self.detail.hide()
            self.expand_btn.hide()
            self._preview_html = ""
            self._full_html = ""
            self._expanded = False
            if not self._anim_timer.isActive():
                self._anim_timer.start()

        def set_progress(
            self,
            progress=None,
            status: str = "",
            message: str = "",
        ) -> None:
            if progress is not None:
                try:
                    self._progress_pct = max(0, min(100, int(progress)))
                except (TypeError, ValueError):
                    self._progress_pct = progress
                try:
                    self.bar.setValue(int(self._progress_pct))
                except (TypeError, ValueError):
                    pass
                self.bar.show()
            if status:
                self._progress_status = status
            # Prefer the bar over repeating the same progress text in detail
            if self._progress_pct is not None:
                self.detail.hide()
            elif message:
                self.detail.setText(message)
                self.detail.show()
            if self._anim_timer.isActive():
                self._tick_running()
            else:
                suffix = self._progress_suffix()
                self.title.setText(f"◐ 正在执行  {self._running_name}{suffix}")

        def set_done(self, name: str, result_json: str):
            self._anim_timer.stop()
            self._progress_pct = None
            self._progress_status = ""
            self.bar.hide()
            self.bar.setValue(0)
            title, preview, full, ok, needs_expand = (
                chat_format.summarize_tool_result_views(name, result_json)
            )
            self.setStyleSheet(self._done_stylesheet(ok))
            self.title.setText(f"⚙ {title}")
            self._preview_html = preview
            self._full_html = full
            self._expanded = False
            self.detail.setText(preview)
            self.detail.setVisible(bool(preview))
            if needs_expand and full:
                self.expand_btn.setText("展开全部 ▾")
                self.expand_btn.show()
            else:
                self.expand_btn.hide()

        def _toggle_expand(self):
            if not self._full_html:
                return
            self._expanded = not self._expanded
            if self._expanded:
                self.detail.setText(self._full_html)
                self.expand_btn.setText("收起 ▴")
            else:
                self.detail.setText(self._preview_html or self._full_html)
                self.expand_btn.setText("展开全部 ▾")
            self.detail.updateGeometry()
            parent = self.parentWidget()
            while parent is not None:
                if hasattr(parent, "_scroll_to_bottom"):
                    parent._scroll_to_bottom()
                    break
                parent = parent.parentWidget()

    class ThinkingRow(QtWidgets.QFrame):
        """Collapsible block for model reasoning / thinking content."""

        _PREVIEW_CHARS = 840
        _STREAM_TAIL_CHARS = 2700

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setObjectName("thinkingRow")
            self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
            self.setMinimumWidth(0)
            self.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum
            )
            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(10, 8, 10, 8)
            lay.setSpacing(4)
            self.title = QtWidgets.QLabel("思考中…")
            self.title.setWordWrap(True)
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
            dots = "." * (self._anim_frame % 4)
            self.title.setText(f"{spin} 思考中{dots}")
            # Restyle infrequently — stylesheet rebuilds are expensive on Maya UI thread
            if self._anim_frame % 3 == 0:
                self.setStyleSheet(
                    self._stylesheet(running=True, pulse=self._anim_frame % 6 == 0)
                )

        def _escape_html(self, text: str) -> str:
            return chat_format.escape(text or "").replace("\n", "<br/>")

        def _stream_display_text(self, text: str) -> str:
            if len(text) <= self._STREAM_TAIL_CHARS:
                return text
            return "…\n" + text[-self._STREAM_TAIL_CHARS :]

        def _refresh_detail(self) -> None:
            text = self._text or ""
            if not text:
                self.detail.hide()
                self.expand_btn.hide()
                self._detail_cache = None
                return
            if not self._done:
                shown = self._stream_display_text(text)
                if shown == self._detail_cache:
                    return
                self._detail_cache = shown
                self.detail.setTextFormat(QtCore.Qt.PlainText)
                self.detail.setText(shown)
                self.expand_btn.hide()
                self.detail.show()
                return

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
            if cache_key == self._detail_cache:
                return
            self._detail_cache = cache_key
            self.detail.setTextFormat(QtCore.Qt.RichText)
            self.detail.setText(self._escape_html(shown))
            self.detail.show()

        def append(self, piece: str) -> None:
            if not piece:
                return
            self._text += piece
            self._done = False
            self._expanded = True
            if not self._anim_timer.isActive():
                self.title.setText("◐ 思考中…")
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

    class ChoiceBar(QtWidgets.QWidget):
        """Clickable confirmation options under an assistant bubble."""

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setObjectName("choiceBar")
            self._buttons: List[Any] = []
            self._on_pick = None
            self._lay = QtWidgets.QVBoxLayout(self)
            self._lay.setContentsMargins(0, 4, 0, 0)
            self._lay.setSpacing(6)
            hint = QtWidgets.QLabel("请选择：")
            hint.setObjectName("choiceHint")
            hint.setStyleSheet(
                "QLabel#choiceHint { color:#8a8a93; font-size:11px; "
                "background:transparent; border:none; }"
            )
            self._lay.addWidget(hint)
            self._btn_col = QtWidgets.QVBoxLayout()
            self._btn_col.setContentsMargins(0, 0, 0, 0)
            self._btn_col.setSpacing(6)
            self._lay.addLayout(self._btn_col)
            self.hide()

        def set_handler(self, fn) -> None:
            self._on_pick = fn

        def set_choices(self, choices: List[Dict[str, str]], *, enabled: bool = True) -> None:
            while self._btn_col.count():
                item = self._btn_col.takeAt(0)
                w = item.widget()
                if w:
                    w.deleteLater()
            self._buttons.clear()
            if not choices:
                self.hide()
                return
            for idx, ch in enumerate(choices, start=1):
                label = (ch.get("label") or "").strip()
                reply = (ch.get("reply") or label).strip()
                if not label:
                    continue
                # Numbered short label for long option text
                shown = label if len(label) <= 42 else (label[:40] + "…")
                btn = QtWidgets.QPushButton(f"{idx}.  {shown}")
                btn.setObjectName("choiceBtn")
                btn.setCursor(QtCore.Qt.PointingHandCursor)
                btn.setEnabled(enabled)
                btn.setToolTip(reply)
                btn.setSizePolicy(
                    QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
                )
                btn.setStyleSheet(
                    """
                    QPushButton#choiceBtn {
                        background-color: #2a3340;
                        border: 1px solid #4a6a8a;
                        border-radius: 8px;
                        color: #c8daf0;
                        font-size: 12px;
                        padding: 8px 12px;
                        min-height: 28px;
                        text-align: left;
                    }
                    QPushButton#choiceBtn:hover:enabled {
                        background-color: #334556;
                        border-color: #5b8fc7;
                        color: #e8f0fa;
                    }
                    QPushButton#choiceBtn:pressed:enabled {
                        background-color: #2c4054;
                    }
                    QPushButton#choiceBtn:disabled {
                        background-color: #25262c;
                        border-color: #3a3b44;
                        color: #6a6a72;
                    }
                    """
                )
                btn.clicked.connect(
                    lambda _checked=False, r=reply: self._emit(r)
                )
                self._btn_col.addWidget(btn)
                self._buttons.append(btn)
            self.show()

        def set_enabled(self, enabled: bool) -> None:
            for btn in self._buttons:
                btn.setEnabled(enabled)

        def clear(self) -> None:
            self.set_choices([])

        def _emit(self, reply: str) -> None:
            self.set_enabled(False)
            if self._on_pick:
                self._on_pick(reply)

    class MessageBlock(QtWidgets.QWidget):
        def __init__(self, role: str, parent=None):
            super().__init__(parent)
            self.role = role
            self.setMinimumWidth(0)
            self.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum
            )
            self._image_host = None
            self._tools: List[ToolRow] = []
            self._thinking_row: Optional[ThinkingRow] = None
            self._body_view: Optional[BodyView] = None
            self._choice_bar = None

            root = QtWidgets.QHBoxLayout(self)
            root.setContentsMargins(4, 6, 4, 6)
            root.setSpacing(10)

            self.bubble = Bubble(role if role in ("user", "assistant", "error") else "assistant")
            bubble_lay = QtWidgets.QVBoxLayout(self.bubble)
            bubble_lay.setContentsMargins(12, 8, 12, 8)
            bubble_lay.setSpacing(6)

            self.content = QtWidgets.QVBoxLayout()
            self.content.setContentsMargins(0, 0, 0, 0)
            self.content.setSpacing(6)
            bubble_lay.addLayout(self.content)

            self.typing = create_typing_indicator(self.bubble)
            self.typing.setMaximumHeight(0)
            bubble_lay.addWidget(self.typing)

            self._meta_label = None
            self._notice_label = None
            if role == "user":
                root.addStretch(1)
                root.addWidget(self.bubble, 6)
                root.addWidget(Avatar("你", "#3d7ab8"), 0, QtCore.Qt.AlignTop)
            elif role == "error":
                root.addWidget(Avatar("!", "#8b3a3a"), 0, QtCore.Qt.AlignTop)
                root.addWidget(self.bubble, 7)
                root.addStretch(1)
            else:
                root.addWidget(Avatar("AI", "#2f7d5b"), 0, QtCore.Qt.AlignTop)
                root.addWidget(self.bubble, 7)
                root.addStretch(1)
                self._choice_bar = ChoiceBar(self.bubble)
                bubble_lay.addWidget(self._choice_bar)
                self._notice_label = QtWidgets.QLabel("")
                self._notice_label.setObjectName("stopNotice")
                self._notice_label.setWordWrap(True)
                self._notice_label.setTextInteractionFlags(
                    QtCore.Qt.TextSelectableByMouse
                )
                self._notice_label.setStyleSheet(
                    "QLabel#stopNotice {"
                    " color:#d4b06a;"
                    " background-color:#2a281c;"
                    " border:1px solid #4a4330;"
                    " border-radius:6px;"
                    " font-size:12px;"
                    " padding:6px 8px;"
                    " margin-top:2px;"
                    "}"
                )
                self._notice_label.hide()
                bubble_lay.addWidget(self._notice_label)
                self._meta_label = QtWidgets.QLabel("")
                self._meta_label.setObjectName("turnMeta")
                self._meta_label.setWordWrap(True)
                self._meta_label.setTextInteractionFlags(
                    QtCore.Qt.TextSelectableByMouse
                )
                self._meta_label.setStyleSheet(
                    "QLabel#turnMeta {"
                    " color:#6a6a72; font-size:11px;"
                    " background:transparent; border:none;"
                    " padding-top:2px;"
                    "}"
                )
                self._meta_label.hide()
                bubble_lay.addWidget(self._meta_label)

            self.bubble.setMinimumWidth(0)
            self.bubble.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum
            )

        def set_turn_meta(
            self,
            model: str = "",
            usage: Optional[Dict[str, Any]] = None,
            text: Optional[str] = None,
            llm_calls: int = 0,
        ) -> None:
            if self._meta_label is None:
                return
            line = (text or "").strip() or format_turn_meta(
                model, usage, llm_calls=llm_calls
            )
            if not line:
                self._meta_label.hide()
                self._meta_label.clear()
                return
            self._meta_label.setText(line)
            self._meta_label.show()

        def set_stop_notice(self, text: str = "") -> None:
            """Show an abnormal-stop tip at the end of the assistant bubble."""
            if self._notice_label is None:
                return
            line = (text or "").strip()
            if not line:
                self._notice_label.hide()
                self._notice_label.clear()
                return
            self._notice_label.setText(line)
            self._notice_label.show()
            self._set_typing(False)

        def _ensure_body(self) -> BodyView:
            if self._body_view is None:
                view = BodyView(self.role, self.bubble)
                self.content.addWidget(view)
                self._body_view = view
            return self._body_view

        def set_images(self, images: Optional[List[Any]]) -> None:
            """Show thumbnails for user-attached images above the text."""
            images = [img for img in (images or []) if _image_b64(img)]
            if not images:
                if self._image_host is not None:
                    self._image_host.hide()
                return
            from maya_agent.llm.base import ImageAttachment
            from maya_agent.ui.image_viewer import make_clickable_thumb

            if self._image_host is None:
                host = QtWidgets.QWidget(self.bubble)
                host.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
                lay = QtWidgets.QHBoxLayout(host)
                lay.setContentsMargins(0, 0, 0, 0)
                lay.setSpacing(6)
                lay.addStretch(1)
                self.content.insertWidget(0, host)
                self._image_host = host
                self._image_lay = lay
            else:
                lay = self._image_lay
                while lay.count() > 1:
                    item = lay.takeAt(0)
                    w = item.widget()
                    if w is not None:
                        w.deleteLater()
            for idx, img in enumerate(images):
                if isinstance(img, ImageAttachment):
                    att = img
                else:
                    att = ImageAttachment.from_dict(img)
                tip = att.name or att.mime or "图片"
                label = make_clickable_thumb(
                    att,
                    edge=88,
                    fixed_w=88,
                    fixed_h=88,
                    parent=self._image_host,
                    gallery=images,
                    index=idx,
                    tooltip=tip,
                    stylesheet=(
                        "QLabel { background:#1a1b20; border:1px solid #4a5d78;"
                        " border-radius:8px; }"
                    ),
                )
                lay.insertWidget(lay.count() - 1, label)
            self._image_host.show()

        def set_plain_text(self, text: str):
            view = self._ensure_body()
            view.set_plain(text or "")
            view.setVisible(bool(text))
            self._set_typing(False)

        def set_markdown(self, text: str):
            self.finish_thinking()
            if not text:
                if self._body_view is not None:
                    self._body_view.hide()
                self._set_typing(False)
                return
            view = self._ensure_body()
            view.set_html(chat_format.markdown_to_html(text))
            view.show()
            self._set_typing(False)

        def set_choices(
            self,
            choices: List[Dict[str, str]],
            *,
            enabled: bool = True,
            on_pick=None,
        ) -> None:
            if self._choice_bar is None:
                return
            if on_pick is not None:
                self._choice_bar.set_handler(on_pick)
            self._choice_bar.set_choices(choices or [], enabled=enabled)

        def disable_choices(self) -> None:
            if self._choice_bar is not None:
                self._choice_bar.set_enabled(False)

        def clear_choices(self) -> None:
            if self._choice_bar is not None:
                self._choice_bar.clear()

        def set_streaming_text(self, text: str):
            self.finish_thinking()
            view = self._ensure_body()
            # Avoid expensive choice parsing while streaming; hide incomplete marker cheaply
            display = text or ""
            marker = display.find("[[CHOICES]]")
            if marker >= 0:
                display = display[:marker].rstrip()
            view.set_plain_streaming(display)
            view.setVisible(bool(display))
            if display:
                self._set_typing(False)
            elif not self._tools and self._thinking_row is None:
                self._set_typing(True)

        def append_thinking(self, piece: str) -> None:
            if not piece:
                return
            # Always append at the end so thinking stays in timeline order
            # (after prior text / tools), not stacked at the top.
            if self._thinking_row is None or self._thinking_row._done:
                row = ThinkingRow(self.bubble)
                self.content.addWidget(row)
                self._thinking_row = row
            self._thinking_row.append(piece)
            self._set_typing(False)

        def finish_thinking(self) -> None:
            if self._thinking_row is not None:
                self._thinking_row.set_done()

        def set_thinking_text(self, text: str) -> None:
            """Add a completed thinking block at the current timeline position."""
            if not text:
                return
            row = ThinkingRow(self.bubble)
            self.content.addWidget(row)
            self._thinking_row = row
            self._thinking_row.set_full(text, done=True)
            self._set_typing(False)

        def add_text_segment(self, text: str) -> None:
            """Add a completed text segment at the current timeline position."""
            if not text:
                return
            self._body_view = None
            display, _ = chat_format.extract_user_choices(text)
            self.set_markdown(display or text)

        def _set_typing(self, on: bool):
            if on:
                self.typing.setMaximumHeight(16777215)
                self.typing.start()
            else:
                self.typing.stop()
                self.typing.setMaximumHeight(0)

        def show_typing(self, on: bool = True):
            has_body = (
                self._body_view is not None and bool(self._body_view.toPlainText())
            )
            self._set_typing(
                on
                and not has_body
                and not self._tools
                and self._thinking_row is None
            )

        def add_tool_running(self, name: str) -> ToolRow:
            self.finish_thinking()
            self._body_view = None
            row = ToolRow(self.bubble)
            row.set_running(name)
            self.content.addWidget(row)
            self._tools.append(row)
            self._set_typing(False)
            return row

        def finish_last_tool(self, name: str, result: str, images: Optional[List[Any]] = None):
            for row in reversed(self._tools):
                if row._anim_timer.isActive() and name in row.title.text():
                    row.set_done(name, result)
                    if images:
                        row.set_images(images)
                    return
            row = ToolRow(self.bubble)
            row.set_done(name, result)
            if images:
                row.set_images(images)
            self.content.addWidget(row)
            self._tools.append(row)

    class TurnSeparator(QtWidgets.QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setFixedHeight(20)
            lay = QtWidgets.QHBoxLayout(self)
            lay.setContentsMargins(48, 10, 48, 10)
            line = QtWidgets.QFrame()
            line.setFrameShape(QtWidgets.QFrame.HLine)
            line.setFixedHeight(1)
            line.setStyleSheet("background:#33343c;border:none;")
            lay.addWidget(line)

    class ChatPanel(QtWidgets.QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setObjectName("chatPanel")
            outer = QtWidgets.QVBoxLayout(self)
            outer.setContentsMargins(0, 0, 0, 0)

            # Rounded shell: chat body + integrated scroll rail (buttons + bar)
            self._shell = QtWidgets.QFrame()
            self._shell.setObjectName("chatScrollShell")
            shell_lay = QtWidgets.QHBoxLayout(self._shell)
            shell_lay.setContentsMargins(0, 0, 0, 0)
            shell_lay.setSpacing(0)

            self.scroll = QtWidgets.QScrollArea()
            self.scroll.setObjectName("chatScroll")
            self.scroll.setWidgetResizable(True)
            self.scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            self.scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)

            self.container = QtWidgets.QWidget()
            self.container.setObjectName("chatContainer")
            self.container.setMinimumWidth(0)
            self.container.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred
            )
            self.v = QtWidgets.QVBoxLayout(self.container)
            self.v.setContentsMargins(10, 14, 10, 18)
            self.v.setSpacing(6)
            self.v.addStretch(1)

            self.scroll.setWidget(self.container)
            self.scroll.setWidgetResizable(True)
            shell_lay.addWidget(self.scroll, 1)

            # Classic scrollbar chrome: continuous track + end arrows + pill thumb.
            self._scroll_rail = QtWidgets.QFrame()
            self._scroll_rail.setObjectName("chatScrollRail")
            self._scroll_rail.setFixedWidth(14)
            rail_lay = QtWidgets.QVBoxLayout(self._scroll_rail)
            rail_lay.setContentsMargins(0, 0, 0, 0)
            rail_lay.setSpacing(0)

            self._jump_top_btn = self._make_jump_btn("▲", "chat.jump_top_tip")
            self._jump_prev_btn = self._make_jump_btn(
                "■", "chat.jump_prev_tip", font_px=14
            )
            self._jump_next_btn = self._make_jump_btn(
                "■", "chat.jump_next_tip", font_px=14
            )
            self._jump_bottom_btn = self._make_jump_btn("▼", "chat.jump_bottom_tip")
            self._jump_top_btn.clicked.connect(self.jump_to_top)
            self._jump_prev_btn.clicked.connect(self.jump_prev_user)
            self._jump_next_btn.clicked.connect(self.jump_next_user)
            self._jump_bottom_btn.clicked.connect(self.jump_to_bottom)

            self._rail_bar = QtWidgets.QScrollBar(QtCore.Qt.Vertical)
            self._rail_bar.setObjectName("chatRailBar")
            self._rail_bar.setFocusPolicy(QtCore.Qt.NoFocus)
            self._rail_bar.setFixedWidth(14)
            self._rail_bar.setSizePolicy(
                QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Expanding
            )
            # Maya's native style often ignores scrollbar QSS; Fusion honors it.
            try:
                fusion = QtWidgets.QStyleFactory.create("Fusion")
                if fusion is not None:
                    self._rail_bar.setStyle(fusion)
            except Exception:
                pass

            rail_lay.addWidget(self._jump_top_btn, 0)
            rail_lay.addWidget(self._jump_prev_btn, 0)
            rail_lay.addWidget(self._rail_bar, 1)
            rail_lay.addWidget(self._jump_next_btn, 0)
            rail_lay.addWidget(self._jump_bottom_btn, 0)
            shell_lay.addWidget(self._scroll_rail, 0)
            outer.addWidget(self._shell)

            self._blocks: List[Dict[str, Any]] = []
            self._widgets: List[QtWidgets.QWidget] = []
            self._current: Optional[MessageBlock] = None
            self._stream_text = ""
            self._thinking_text = ""
            self._pending_separator = False
            self._on_choice_reply = None
            self._active_choice_block = None
            self._stick_to_bottom = True
            self._scrolling_programmatic = False
            self._scroll_near_margin = 80
            self._deferred_scroll = False
            self._bar_syncing = False

            bar = self.scroll.verticalScrollBar()
            bar.rangeChanged.connect(self._on_scroll_range_changed)
            bar.valueChanged.connect(self._on_scroll_value_changed)
            bar.rangeChanged.connect(self._sync_rail_from_inner)
            bar.valueChanged.connect(self._sync_rail_from_inner)
            self._rail_bar.valueChanged.connect(self._sync_inner_from_rail)
            self._sync_rail_from_inner()
            self._refresh_jump_buttons()

            self.setStyleSheet(
                """
                QWidget#chatPanel, QWidget#chatContainer {
                    background-color: #17181d;
                }
                QFrame#chatScrollShell {
                    background-color: #17181d;
                    border: 1px solid #2e2f36;
                    border-radius: 10px;
                }
                QScrollArea#chatScroll {
                    background-color: #17181d;
                    border: none;
                }
                QFrame#chatScrollRail {
                    background-color: #3a3b42;
                    border: none;
                    border-left: 1px solid #2a2b30;
                    border-radius: 0px;
                }
                QScrollBar#chatRailBar:vertical {
                    background: transparent;
                    width: 14px;
                    /* Keep ~8px thumb: was 18-5*2, now 14-3*2 */
                    margin: 2px 3px;
                    border: none;
                }
                QScrollBar#chatRailBar::handle:vertical {
                    background: #7a7b84;
                    border-radius: 3px;
                    min-height: 32px;
                    border: none;
                }
                QScrollBar#chatRailBar::handle:vertical:hover {
                    background: #9697a0;
                }
                QScrollBar#chatRailBar::handle:vertical:pressed {
                    background: #6a8fb8;
                }
                QScrollBar#chatRailBar::add-line:vertical,
                QScrollBar#chatRailBar::sub-line:vertical {
                    height: 0px;
                    width: 0px;
                    background: none;
                    border: none;
                }
                QScrollBar#chatRailBar::add-page:vertical,
                QScrollBar#chatRailBar::sub-page:vertical {
                    background: transparent;
                }
                QPushButton#chatJumpBtn {
                    background: transparent;
                    border: none;
                    border-radius: 0px;
                    color: #e8e9ef;
                    font-size: 13px;
                    font-weight: 700;
                    padding: 0px;
                    margin: 0px;
                    text-align: center;
                }
                QPushButton#chatJumpBtn:hover {
                    color: #ffffff;
                    background-color: rgba(255, 255, 255, 36);
                }
                QPushButton#chatJumpBtn:pressed {
                    color: #ffffff;
                    background-color: rgba(91, 143, 199, 90);
                }
                QPushButton#chatJumpBtn:disabled {
                    color: #707179;
                    background: transparent;
                }
                """
            )

        def _make_jump_btn(self, label: str, tip_key: str, font_px: int = 13):
            from maya_agent.i18n import t

            btn = QtWidgets.QPushButton(label)
            btn.setObjectName("chatJumpBtn")
            # Match narrow rail; glyph size comes from font_px (unchanged).
            btn.setFixedSize(14, 22 if font_px > 13 else 20)
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            btn.setToolTip(t(tip_key))
            btn.setFocusPolicy(QtCore.Qt.NoFocus)
            btn.setFlat(True)
            font = btn.font()
            font.setPixelSize(int(font_px))
            font.setBold(True)
            btn.setFont(font)
            return btn

        def _jump_buttons(self):
            return (
                getattr(self, "_jump_top_btn", None),
                getattr(self, "_jump_prev_btn", None),
                getattr(self, "_jump_next_btn", None),
                getattr(self, "_jump_bottom_btn", None),
            )

        def _sync_rail_from_inner(self, *_args) -> None:
            if self._bar_syncing or not hasattr(self, "_rail_bar"):
                return
            inner = self.scroll.verticalScrollBar()
            self._bar_syncing = True
            try:
                self._rail_bar.setRange(inner.minimum(), inner.maximum())
                self._rail_bar.setPageStep(inner.pageStep())
                self._rail_bar.setSingleStep(inner.singleStep())
                self._rail_bar.setValue(inner.value())
            finally:
                self._bar_syncing = False

        def _sync_inner_from_rail(self, value: int = 0) -> None:
            if self._bar_syncing:
                return
            self._bar_syncing = True
            try:
                self.scroll.verticalScrollBar().setValue(int(value))
            finally:
                self._bar_syncing = False

        def showEvent(self, event):
            super().showEvent(event)
            self._sync_rail_from_inner()
            self._refresh_jump_buttons()

        def _user_widgets(self) -> List[Any]:
            return [
                w
                for w in self._widgets
                if getattr(w, "role", None) == "user" and w.isVisible()
            ]

        def _visible_top_in_container(self) -> int:
            """Y of the viewport top edge, in chat-container coordinates."""
            vp = self.scroll.viewport()
            top_left = self.container.mapFrom(vp, QtCore.QPoint(0, 0))
            return int(top_left.y())

        def _scroll_to_widget(self, widget: QtWidgets.QWidget) -> None:
            if widget is None:
                return
            self._stick_to_bottom = False
            # Align the bubble near the top of the viewport with a small pad.
            pad = 8
            target = max(0, int(widget.y()) - pad)
            bar = self.scroll.verticalScrollBar()
            self._scrolling_programmatic = True
            try:
                bar.setValue(min(target, bar.maximum()))
            finally:
                self._scrolling_programmatic = False
            # One deferred pass after layout / scrollbar range settle.
            QtCore.QTimer.singleShot(
                0, lambda w=widget: self._scroll_to_widget_settle(w)
            )

        def _scroll_to_widget_settle(self, widget: QtWidgets.QWidget) -> None:
            if widget is None or not widget.isVisible():
                return
            pad = 8
            target = max(0, int(widget.y()) - pad)
            bar = self.scroll.verticalScrollBar()
            self._scrolling_programmatic = True
            try:
                bar.setValue(min(target, bar.maximum()))
            finally:
                self._scrolling_programmatic = False
            self._refresh_jump_buttons()

        def jump_to_top(self) -> None:
            """Jump to the top of the conversation."""
            self._stick_to_bottom = False
            bar = self.scroll.verticalScrollBar()
            self._scrolling_programmatic = True
            try:
                bar.setValue(bar.minimum())
            finally:
                self._scrolling_programmatic = False
            QtCore.QTimer.singleShot(0, self._refresh_jump_buttons)

        def jump_to_bottom(self) -> None:
            """Jump to the bottom of the conversation."""
            self._stick_to_bottom = True
            self._apply_scroll_bottom()
            QtCore.QTimer.singleShot(0, self._refresh_jump_buttons)

        def jump_prev_user(self) -> None:
            """Jump to the previous user bubble above the current viewport."""
            users = self._user_widgets()
            if not users:
                return
            anchor = self._visible_top_in_container() + 12
            prev = None
            for w in users:
                if w.y() < anchor - 4:
                    prev = w
            if prev is None:
                prev = users[0]
            self._scroll_to_widget(prev)

        def jump_next_user(self) -> None:
            """Jump to the next user bubble below the current viewport."""
            users = self._user_widgets()
            if not users:
                return
            anchor = self._visible_top_in_container() + 12
            nxt = None
            for w in users:
                if w.y() > anchor + 4:
                    nxt = w
                    break
            if nxt is None:
                nxt = users[-1]
            self._scroll_to_widget(nxt)

        def _refresh_jump_buttons(self) -> None:
            top, prev, nxt, bottom = self._jump_buttons()
            if top is None or prev is None or nxt is None or bottom is None:
                return
            from maya_agent.i18n import t

            has_content = bool(self._widgets)
            users = self._user_widgets()
            has_users = len(users) > 0
            bar = self.scroll.verticalScrollBar()
            scrollable = bar.maximum() > bar.minimum()
            at_top = bar.value() <= bar.minimum() + 4
            at_bottom = (bar.maximum() - bar.value()) <= 4

            top.setToolTip(t("chat.jump_top_tip"))
            prev.setToolTip(t("chat.jump_prev_tip"))
            nxt.setToolTip(t("chat.jump_next_tip"))
            bottom.setToolTip(t("chat.jump_bottom_tip"))

            # Rail stays visible with content (matches classic scrollbar chrome).
            if hasattr(self, "_scroll_rail"):
                self._scroll_rail.setVisible(has_content)
            self._rail_bar.setEnabled(scrollable)

            if not has_content:
                for btn in (top, prev, nxt, bottom):
                    btn.setEnabled(False)
                return

            top.setEnabled(not at_top)
            bottom.setEnabled(not at_bottom)
            if has_users:
                anchor = self._visible_top_in_container() + 12
                prev.setEnabled(any(w.y() < anchor - 4 for w in users))
                nxt.setEnabled(any(w.y() > anchor + 4 for w in users))
            else:
                prev.setEnabled(False)
                nxt.setEnabled(False)

        def clear(self):
            self.disable_active_choices()
            while self.v.count():
                item = self.v.takeAt(0)
                w = item.widget()
                if w:
                    w.deleteLater()
            self.v.addStretch(1)
            self._blocks.clear()
            self._widgets.clear()
            self._current = None
            self._stream_text = ""
            self._thinking_text = ""
            self._pending_separator = False
            self._active_choice_block = None
            self._stick_to_bottom = True
            self._deferred_scroll = False
            self._refresh_jump_buttons()

        def set_choice_handler(self, fn) -> None:
            """fn(reply_text) called when user clicks a confirmation button."""
            self._on_choice_reply = fn

        def disable_active_choices(self) -> None:
            if self._active_choice_block is not None:
                try:
                    self._active_choice_block.disable_choices()
                except Exception:
                    pass
                self._active_choice_block = None

        def _insert_before_stretch(self, widget: QtWidgets.QWidget):
            idx = max(0, self.v.count() - 1)
            self.v.insertWidget(idx, widget)
            self._widgets.append(widget)

        def _is_near_bottom(self, margin: Optional[int] = None) -> bool:
            bar = self.scroll.verticalScrollBar()
            m = self._scroll_near_margin if margin is None else margin
            return (bar.maximum() - bar.value()) <= m

        def _on_scroll_value_changed(self, _value: int = 0) -> None:
            if self._scrolling_programmatic:
                self._refresh_jump_buttons()
                return
            # User scrolled: keep auto-stick only while near the bottom.
            self._stick_to_bottom = self._is_near_bottom()
            self._refresh_jump_buttons()

        def _on_scroll_range_changed(self, _mn: int = 0, _mx: int = 0) -> None:
            # Content grew (stream / images / tools). If we should stick, pin
            # immediately to the new maximum — avoids missing bottom when
            # setValue ran before layout updated the scrollbar range.
            if self._stick_to_bottom:
                self._apply_scroll_bottom()

        def _apply_scroll_bottom(self) -> None:
            bar = self.scroll.verticalScrollBar()
            self._scrolling_programmatic = True
            try:
                bar.setValue(bar.maximum())
            finally:
                self._scrolling_programmatic = False

        def _scroll_to_bottom(self, force: bool = False):
            """Scroll to bottom. Soft (default): only while stick-to-bottom is on."""
            if force:
                self._stick_to_bottom = True
            elif not self._stick_to_bottom:
                return
            self._apply_scroll_bottom()
            # Layout may still settle after setFixedHeight / insertWidget.
            # One deferred pass catches the post-layout maximum.
            if not self._deferred_scroll:
                self._deferred_scroll = True
                QtCore.QTimer.singleShot(0, self._flush_deferred_scroll)

        def _flush_deferred_scroll(self) -> None:
            self._deferred_scroll = False
            if self._stick_to_bottom:
                self._apply_scroll_bottom()

        def add_user(self, text: str, images: Optional[List[Any]] = None):
            self.disable_active_choices()
            if self._pending_separator:
                self._insert_before_stretch(TurnSeparator())
            self._pending_separator = True
            block = MessageBlock("user")
            stored = _image_dicts(images)
            if stored:
                block.set_images(stored)
            block.set_plain_text(text)
            self._insert_before_stretch(block)
            payload = {"type": "user", "text": text}
            if stored:
                payload["images"] = stored
            self._blocks.append(payload)
            self._current = None
            self._refresh_jump_buttons()
            self._scroll_to_bottom(force=True)

        def begin_assistant(self):
            block = MessageBlock("assistant")
            block.show_typing(True)
            self._insert_before_stretch(block)
            self._current = block
            self._stream_text = ""
            self._thinking_text = ""
            self._blocks.append(
                {
                    "type": "assistant",
                    "text": "",
                    "thinking": "",
                    "tools": [],
                    "parts": [],
                    "done": False,
                }
            )
            self._scroll_to_bottom(force=True)
            return block

        def _assistant_block(self) -> Optional[Dict[str, Any]]:
            if self._blocks and self._blocks[-1].get("type") == "assistant":
                return self._blocks[-1]
            return None

        def _parts(self) -> List[Dict[str, Any]]:
            block = self._assistant_block()
            if block is None:
                return []
            return block.setdefault("parts", [])

        def _extend_part(self, kind: str, text: str = "", **extra: Any) -> None:
            parts = self._parts()
            if kind in ("thinking", "text") and parts and parts[-1].get("kind") == kind:
                parts[-1]["text"] = (parts[-1].get("text") or "") + text
                return
            part: Dict[str, Any] = {"kind": kind}
            if kind in ("thinking", "text"):
                part["text"] = text
            part.update(extra)
            parts.append(part)

        def _ensure_open_assistant(self) -> bool:
            """Reuse the live bubble. Do not open a new one after the turn closed."""
            if self._current is not None:
                return True
            last = self._assistant_block()
            if last is not None and last.get("done"):
                return False
            self.begin_assistant()
            return self._current is not None

        def append_thinking(self, piece: str):
            if not piece:
                return
            if not self._ensure_open_assistant():
                return
            row = self._current._thinking_row
            started_new = row is None or row._done
            self._thinking_text += piece
            self._current.append_thinking(piece)
            block = self._assistant_block()
            if block is not None:
                block["thinking"] = self._thinking_text
                if started_new:
                    self._parts().append({"kind": "thinking", "text": piece})
                else:
                    self._extend_part("thinking", piece)
            self._scroll_to_bottom()

        def finish_thinking(self):
            if self._current is not None:
                self._current.finish_thinking()

        def append_assistant_text(self, piece: str):
            if not self._ensure_open_assistant():
                return
            self.finish_thinking()
            self._stream_text += piece
            # Streaming uses plain text; choice markers stripped cheaply inside
            self._current.set_streaming_text(self._stream_text)
            block = self._assistant_block()
            if block is not None:
                block["text"] = (block.get("text") or "") + piece
                self._extend_part("text", piece)
            self._scroll_to_bottom()

        def tool_start(self, name: str):
            if not self._ensure_open_assistant():
                return
            self.finish_thinking()
            if self._stream_text:
                self._current.set_streaming_text(self._stream_text)
            self._stream_text = ""
            self._current.add_tool_running(name)
            block = self._assistant_block()
            if block is not None:
                tool = {"name": name, "status": "running"}
                block.setdefault("tools", []).append(tool)
                self._parts().append(
                    {"kind": "tool", "name": name, "status": "running"}
                )
            self._scroll_to_bottom()

        def tool_progress(
            self,
            name: str = "",
            progress=None,
            status: str = "",
            message: str = "",
        ):
            if self._current is None:
                return
            for row in reversed(getattr(self._current, "_tools", []) or []):
                if not getattr(row, "_anim_timer", None) or not row._anim_timer.isActive():
                    continue
                if name and name not in (row._running_name or "") and name not in row.title.text():
                    continue
                row.set_progress(progress=progress, status=status, message=message)
                break
            block = self._assistant_block()
            if block is not None:
                for t in reversed(block.setdefault("tools", [])):
                    if t.get("status") == "running" and (
                        not name or t.get("name") == name
                    ):
                        if progress is not None:
                            t["progress"] = progress
                        if status:
                            t["task_status"] = status
                        break

        def tool_end(self, name: str, result: str, images: Optional[List[Any]] = None):
            if not self._ensure_open_assistant():
                return
            self._current.finish_last_tool(name, result, images=images)
            block = self._assistant_block()
            if block is not None:
                stored = _image_dicts(images)
                for t in reversed(block.setdefault("tools", [])):
                    if t.get("name") == name and t.get("status") == "running":
                        t["status"] = "done"
                        t["result"] = result
                        if stored:
                            t["images"] = stored
                        break
                for p in reversed(self._parts()):
                    if (
                        p.get("kind") == "tool"
                        and p.get("name") == name
                        and p.get("status") == "running"
                    ):
                        p["status"] = "done"
                        p["result"] = result
                        if stored:
                            p["images"] = stored
                        break
            self._scroll_to_bottom()

        def finish_assistant(
            self,
            final_text: Optional[str] = None,
            *,
            model: str = "",
            usage: Optional[Dict[str, Any]] = None,
            llm_calls: int = 0,
            stop_notice: str = "",
        ):
            if self._current is None:
                return
            self.finish_thinking()
            text = self._stream_text
            if final_text and not text:
                text = final_text
            choices: List[Dict[str, str]] = []
            display = text
            if text:
                display, choices = chat_format.extract_user_choices(text)
                self._current.set_markdown(display or text)
                if choices:
                    self._current.set_choices(
                        choices,
                        enabled=True,
                        on_pick=self._handle_choice,
                    )
                    self._active_choice_block = self._current
            else:
                self._current._set_typing(False)
                if self._current._body_view is not None and not self._current._body_view.toPlainText():
                    self._current._body_view.hide()
            if stop_notice:
                self._current.set_stop_notice(stop_notice)
            if model or usage or llm_calls:
                self._current.set_turn_meta(
                    model=model, usage=usage, llm_calls=llm_calls
                )
            block = self._assistant_block()
            if block is not None:
                block["done"] = True
                parts = block.get("parts") or []
                agg_text = "".join(
                    p.get("text") or "" for p in parts if p.get("kind") == "text"
                )
                if agg_text:
                    block["text"] = agg_text
                elif text:
                    block["text"] = text
                if self._thinking_text:
                    block["thinking"] = self._thinking_text
                if choices:
                    block["choices"] = choices
                if model:
                    block["model"] = model
                if usage:
                    block["usage"] = dict(usage)
                if llm_calls:
                    block["llm_calls"] = int(llm_calls)
                if stop_notice:
                    block["stop_notice"] = stop_notice
            self._current = None
            self._stream_text = ""
            self._thinking_text = ""
            self._scroll_to_bottom()

        def _handle_choice(self, reply: str) -> None:
            self.disable_active_choices()
            if self._on_choice_reply:
                self._on_choice_reply(reply)

        def add_error(self, text: str):
            block = MessageBlock("error")
            block.set_plain_text(text)
            self._insert_before_stretch(block)
            self._blocks.append({"type": "error", "text": text})
            self._scroll_to_bottom(force=True)

        def _restore_assistant(self, block: Dict[str, Any]) -> None:
            mb = MessageBlock("assistant")
            parts = block.get("parts")
            if parts:
                for part in parts:
                    kind = part.get("kind")
                    if kind == "thinking":
                        mb.set_thinking_text(part.get("text") or "")
                    elif kind == "text":
                        mb.add_text_segment(part.get("text") or "")
                    elif kind == "tool":
                        name = part.get("name") or "tool"
                        mb.add_tool_running(name)
                        if part.get("status") == "done":
                            mb.finish_last_tool(
                                name,
                                part.get("result") or "",
                                images=part.get("images"),
                            )
            else:
                # Legacy sessions: thinking → tools → text (order was lossy)
                thinking = block.get("thinking") or ""
                if thinking:
                    mb.set_thinking_text(thinking)
                for tool in block.get("tools") or []:
                    name = tool.get("name") or "tool"
                    mb.add_tool_running(name)
                    if tool.get("status") == "done":
                        mb.finish_last_tool(
                            name,
                            tool.get("result") or "",
                            images=tool.get("images"),
                        )
                text = block.get("text") or ""
                if text:
                    mb.add_text_segment(text)
            choices = block.get("choices") or []
            if not choices:
                raw = block.get("text") or ""
                if raw:
                    _, choices = chat_format.extract_user_choices(raw)
            if choices:
                mb.set_choices(choices, enabled=False)
            notice = block.get("stop_notice") or ""
            if notice:
                mb.set_stop_notice(notice)
            model = block.get("model") or ""
            usage = block.get("usage") or {}
            llm_calls = int(block.get("llm_calls") or 0)
            if model or usage or llm_calls:
                mb.set_turn_meta(model=model, usage=usage, llm_calls=llm_calls)
            if not (block.get("text") or block.get("parts")):
                mb._set_typing(False)
            self._insert_before_stretch(mb)

        def restore_blocks(self, blocks: List[Dict[str, Any]]) -> None:
            """Rebuild chat UI from persisted session blocks."""
            self.clear()
            blocks = blocks or []
            for bi, block in enumerate(blocks):
                btype = block.get("type")
                if bi > 0 and btype in ("user", "assistant", "error"):
                    prev = blocks[bi - 1]
                    if prev.get("type") in ("user", "assistant", "error"):
                        self._insert_before_stretch(TurnSeparator())

                if btype == "user":
                    mb = MessageBlock("user")
                    imgs = block.get("images") or []
                    if imgs:
                        mb.set_images(imgs)
                    mb.set_plain_text(block.get("text") or "")
                    self._insert_before_stretch(mb)
                elif btype == "error":
                    mb = MessageBlock("error")
                    mb.set_plain_text(block.get("text") or "")
                    self._insert_before_stretch(mb)
                elif btype == "assistant":
                    self._restore_assistant(block)

            self._blocks = [dict(b) for b in blocks]
            self._current = None
            self._stream_text = ""
            self._thinking_text = ""
            self._pending_separator = bool(blocks)
            self._refresh_jump_buttons()
            self._scroll_to_bottom(force=True)

        @property
        def blocks(self) -> List[Dict[str, Any]]:
            return self._blocks

    return ChatPanel(parent)
