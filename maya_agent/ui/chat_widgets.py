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
            self._stream_refit_n = 0

        def set_html(self, html: str):
            self._stream_cache = None
            self._stream_refit_n = 0
            self.setHtml(html or "")
            self._refit()

        def set_plain(self, text: str):
            self._stream_cache = None
            self._stream_refit_n = 0
            self.setPlainText(text or "")
            self._refit()

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
            self._stream_refit_n = getattr(self, "_stream_refit_n", 0) + 1
            self._refit_streaming(text, force=self._stream_refit_n % 5 == 0)

        def _refit(self):
            width = max(self.viewport().width(), self.width() - 4, 160)
            self.document().setTextWidth(width)
            # Keep height tight — large pads here show as empty bottom margin in bubbles
            h = int(self.document().size().height()) + 2
            self.setFixedHeight(max(h, 16))

        def _refit_streaming(self, text: str, force: bool = False):
            """Cheaper height estimate while tokens are still arriving."""
            width = max(self.viewport().width(), self.width() - 4, 160)
            fm = self.fontMetrics()
            line_h = max(fm.lineSpacing(), 14)
            char_w = max(fm.averageCharWidth(), 6)
            cols = max(int(width / char_w), 8)
            wrapped = 0
            for line in (text or "").splitlines() or [""]:
                wrapped += max(1, (len(line) + cols - 1) // cols)
            if force or wrapped <= 24:
                self.document().setTextWidth(width)
                h = int(self.document().size().height()) + 2
            else:
                h = wrapped * line_h + 6
            self.setFixedHeight(max(h, 16))

        def resizeEvent(self, event):
            super().resizeEvent(event)
            self._refit()

        def showEvent(self, event):
            super().showEvent(event)
            QtCore.QTimer.singleShot(0, self._refit)

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
            self.detail = QtWidgets.QLabel("")
            self.detail.setWordWrap(True)
            self.detail.setMinimumWidth(0)
            self.detail.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred
            )
            self.detail.setTextFormat(QtCore.Qt.RichText)
            self.detail.setObjectName("toolDetail")
            self.detail.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
            self.detail.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            self.expand_btn = QtWidgets.QPushButton("展开全部")
            self.expand_btn.setObjectName("toolExpandBtn")
            self.expand_btn.setCursor(QtCore.Qt.PointingHandCursor)
            self.expand_btn.setFlat(True)
            self.expand_btn.setFixedHeight(22)
            self.expand_btn.clicked.connect(self._toggle_expand)
            self.expand_btn.hide()
            lay.addWidget(self.title)
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
            self._anim_frame = 0
            self._anim_timer = QtCore.QTimer(self)
            self._anim_timer.setInterval(130)
            self._anim_timer.timeout.connect(self._tick_running)
            self._preview_html = ""
            self._full_html = ""
            self._expanded = False

        def set_images(self, images: Optional[List[Any]]) -> None:
            from maya_agent.llm.base import ImageAttachment
            from maya_agent.ui.image_attach import pixmap_from_attachment

            while self._image_lay.count() > 1:
                item = self._image_lay.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()
            shown = 0
            for img in images or []:
                if isinstance(img, dict):
                    if not img.get("data_b64"):
                        continue
                    att = ImageAttachment.from_dict(img)
                elif getattr(img, "data_b64", ""):
                    att = img
                else:
                    continue
                pix = pixmap_from_attachment(att, edge=96)
                label = QtWidgets.QLabel(self._image_host)
                label.setFixedSize(96, 72)
                label.setAlignment(QtCore.Qt.AlignCenter)
                label.setStyleSheet(
                    "QLabel { background:#1a1b20; border:1px solid #5a4a30;"
                    " border-radius:6px; }"
                )
                if pix is not None and not pix.isNull():
                    label.setPixmap(pix)
                else:
                    label.setText("截图")
                label.setToolTip(att.name or "视口截图")
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
            self.title.setText(f"{spin} 正在执行  {self._running_name}{dots}")
            self.setStyleSheet(self._running_stylesheet(self._anim_frame % 2 == 0))

        def set_running(self, name: str):
            self._running_name = name
            self._anim_frame = 0
            self.setStyleSheet(self._running_stylesheet(False))
            self.title.setText(f"◐ 正在执行  {name}")
            self.detail.setText("")
            self.detail.hide()
            self.expand_btn.hide()
            self._preview_html = ""
            self._full_html = ""
            self._expanded = False
            if not self._anim_timer.isActive():
                self._anim_timer.start()

        def set_done(self, name: str, result_json: str):
            self._anim_timer.stop()
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
            from maya_agent.ui.image_attach import pixmap_from_attachment

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
            for img in images:
                if isinstance(img, ImageAttachment):
                    att = img
                else:
                    att = ImageAttachment.from_dict(img)
                pix = pixmap_from_attachment(att, edge=88)
                label = QtWidgets.QLabel(self._image_host)
                label.setFixedSize(88, 88)
                label.setAlignment(QtCore.Qt.AlignCenter)
                label.setStyleSheet(
                    "QLabel { background:#1a1b20; border:1px solid #4a5d78;"
                    " border-radius:8px; }"
                )
                if pix is not None and not pix.isNull():
                    label.setPixmap(pix)
                else:
                    label.setText("图片")
                tip = att.name or att.mime or "图片"
                label.setToolTip(tip)
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

            self.scroll = QtWidgets.QScrollArea()
            self.scroll.setObjectName("chatScroll")
            self.scroll.setWidgetResizable(True)
            self.scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
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
            # Prevent wide children from expanding the scroll content past viewport
            self.scroll.setWidgetResizable(True)
            outer.addWidget(self.scroll)

            self._blocks: List[Dict[str, Any]] = []
            self._widgets: List[QtWidgets.QWidget] = []
            self._current: Optional[MessageBlock] = None
            self._stream_text = ""
            self._thinking_text = ""
            self._pending_separator = False
            self._on_choice_reply = None
            self._active_choice_block = None
            self._last_scroll_ms = 0
            self._scroll_pending = False
            self._scroll_min_interval_ms = 120

            self.setStyleSheet(
                """
                QWidget#chatPanel, QWidget#chatContainer {
                    background-color: #17181d;
                }
                QScrollArea#chatScroll {
                    background-color: #17181d;
                    border: 1px solid #2e2f36;
                    border-radius: 10px;
                }
                """
            )

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
            self._last_scroll_ms = 0
            self._scroll_pending = False

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

        def _is_near_bottom(self, margin: int = 96) -> bool:
            bar = self.scroll.verticalScrollBar()
            return (bar.maximum() - bar.value()) <= margin

        def _scroll_to_bottom(self, force: bool = False):
            """Scroll to bottom. Soft (default): only if already near bottom."""
            if not force and not self._is_near_bottom():
                self._scroll_pending = False
                return
            if not force:
                now = QtCore.QDateTime.currentMSecsSinceEpoch()
                elapsed = now - self._last_scroll_ms
                if elapsed < self._scroll_min_interval_ms:
                    if not self._scroll_pending:
                        self._scroll_pending = True
                        QtCore.QTimer.singleShot(
                            max(1, self._scroll_min_interval_ms - elapsed),
                            self._flush_pending_scroll,
                        )
                    return
            self._scroll_pending = False
            self._last_scroll_ms = QtCore.QDateTime.currentMSecsSinceEpoch()
            bar = self.scroll.verticalScrollBar()
            QtCore.QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))

        def _flush_pending_scroll(self) -> None:
            if not self._scroll_pending:
                return
            self._scroll_pending = False
            self._scroll_to_bottom(force=False)

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

        def append_thinking(self, piece: str):
            if not piece:
                return
            if self._current is None:
                self.begin_assistant()
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
            if self._current is None:
                self.begin_assistant()
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
            if self._current is None:
                self.begin_assistant()
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

        def tool_end(self, name: str, result: str, images: Optional[List[Any]] = None):
            if self._current is None:
                self.begin_assistant()
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
            self._scroll_to_bottom(force=True)

        @property
        def blocks(self) -> List[Dict[str, Any]]:
            return self._blocks

    return ChatPanel(parent)
