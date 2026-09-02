"""Widget-based chat panel with Qt-safe rich text bubbles."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from maya_agent.ui import chat_format
from maya_agent.ui.palette import SPINNER_FRAMES
from maya_agent.ui.status_anim import create_typing_indicator
from maya_agent.utils.maya_compat import import_qt

_SPINNER = SPINNER_FRAMES


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
            self.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum
            )
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

        def set_html(self, html: str):
            self.setHtml(html or "")
            self._refit()

        def set_plain(self, text: str):
            self.setPlainText(text or "")
            self._refit()

        def _refit(self):
            width = max(self.viewport().width(), self.width() - 4, 160)
            self.document().setTextWidth(width)
            # Keep height tight — large pads here show as empty bottom margin in bubbles
            h = int(self.document().size().height()) + 2
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
            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(10, 8, 10, 8)
            lay.setSpacing(4)
            self.title = QtWidgets.QLabel("⚙ …")
            self.title.setWordWrap(True)
            self.title.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
            self.detail = QtWidgets.QLabel("")
            self.detail.setWordWrap(True)
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
            lay.addWidget(self.expand_btn, 0, QtCore.Qt.AlignLeft)
            self._running_name = ""
            self._anim_frame = 0
            self._anim_timer = QtCore.QTimer(self)
            self._anim_timer.setInterval(130)
            self._anim_timer.timeout.connect(self._tick_running)
            self._preview_html = ""
            self._full_html = ""
            self._expanded = False

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
            self.detail.adjustSize()
            self.adjustSize()
            parent = self.parentWidget()
            while parent is not None:
                if hasattr(parent, "_scroll_to_bottom"):
                    parent._scroll_to_bottom()
                    break
                parent = parent.parentWidget()

    class MessageBlock(QtWidgets.QWidget):
        def __init__(self, role: str, parent=None):
            super().__init__(parent)
            self.role = role
            self._tools: List[ToolRow] = []
            self._body_view: Optional[BodyView] = None

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

            self.bubble.setSizePolicy(
                QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Minimum
            )

        def _ensure_body(self) -> BodyView:
            if self._body_view is None:
                view = BodyView(self.role, self.bubble)
                self.content.addWidget(view)
                self._body_view = view
            return self._body_view

        def set_plain_text(self, text: str):
            view = self._ensure_body()
            view.set_plain(text or "")
            view.setVisible(bool(text))
            self._set_typing(False)

        def set_markdown(self, text: str):
            if not text:
                if self._body_view is not None:
                    self._body_view.hide()
                self._set_typing(False)
                return
            view = self._ensure_body()
            view.set_html(chat_format.markdown_to_html(text))
            view.show()
            self._set_typing(False)

        def set_streaming_text(self, text: str):
            view = self._ensure_body()
            safe = chat_format.escape(text or "").replace("\n", "<br/>")
            view.set_html(
                f'<p style="margin:0;line-height:140%;">{safe}</p>'
            )
            view.setVisible(bool(text))
            if text:
                self._set_typing(False)
            elif not self._tools:
                self._set_typing(True)

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
            self._set_typing(on and not has_body and not self._tools)

        def add_tool_running(self, name: str) -> ToolRow:
            self._body_view = None
            row = ToolRow(self.bubble)
            row.set_running(name)
            self.content.addWidget(row)
            self._tools.append(row)
            self._set_typing(False)
            return row

        def finish_last_tool(self, name: str, result: str):
            for row in reversed(self._tools):
                if row._anim_timer.isActive() and name in row.title.text():
                    row.set_done(name, result)
                    return
            row = ToolRow(self.bubble)
            row.set_done(name, result)
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
            self.v = QtWidgets.QVBoxLayout(self.container)
            self.v.setContentsMargins(10, 14, 10, 18)
            self.v.setSpacing(6)
            self.v.addStretch(1)

            self.scroll.setWidget(self.container)
            outer.addWidget(self.scroll)

            self._blocks: List[Dict[str, Any]] = []
            self._widgets: List[QtWidgets.QWidget] = []
            self._current: Optional[MessageBlock] = None
            self._stream_text = ""
            self._pending_separator = False

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
            self._pending_separator = False

        def _insert_before_stretch(self, widget: QtWidgets.QWidget):
            idx = max(0, self.v.count() - 1)
            self.v.insertWidget(idx, widget)
            self._widgets.append(widget)

        def _scroll_to_bottom(self):
            bar = self.scroll.verticalScrollBar()
            QtCore.QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))

        def add_user(self, text: str):
            if self._pending_separator:
                self._insert_before_stretch(TurnSeparator())
            self._pending_separator = True
            block = MessageBlock("user")
            block.set_plain_text(text)
            self._insert_before_stretch(block)
            self._blocks.append({"type": "user", "text": text})
            self._current = None
            self._scroll_to_bottom()

        def begin_assistant(self):
            block = MessageBlock("assistant")
            block.show_typing(True)
            self._insert_before_stretch(block)
            self._current = block
            self._stream_text = ""
            self._blocks.append(
                {"type": "assistant", "text": "", "tools": [], "done": False}
            )
            self._scroll_to_bottom()
            return block

        def append_assistant_text(self, piece: str):
            if self._current is None:
                self.begin_assistant()
            self._stream_text += piece
            self._current.set_streaming_text(self._stream_text)
            if self._blocks and self._blocks[-1].get("type") == "assistant":
                self._blocks[-1]["text"] = (
                    self._blocks[-1].get("text") or ""
                ) + piece
            self._scroll_to_bottom()

        def tool_start(self, name: str):
            if self._current is None:
                self.begin_assistant()
            if self._stream_text:
                self._current.set_streaming_text(self._stream_text)
            self._stream_text = ""
            self._current.add_tool_running(name)
            if self._blocks and self._blocks[-1].get("type") == "assistant":
                self._blocks[-1].setdefault("tools", []).append(
                    {"name": name, "status": "running"}
                )
            self._scroll_to_bottom()

        def tool_end(self, name: str, result: str):
            if self._current is None:
                self.begin_assistant()
            self._current.finish_last_tool(name, result)
            if self._blocks and self._blocks[-1].get("type") == "assistant":
                tools = self._blocks[-1].setdefault("tools", [])
                for t in reversed(tools):
                    if t.get("name") == name and t.get("status") == "running":
                        t["status"] = "done"
                        t["result"] = result
                        break
            self._scroll_to_bottom()

        def finish_assistant(self, final_text: Optional[str] = None):
            if self._current is None:
                return
            text = self._stream_text
            if final_text and not text:
                text = final_text
            if text:
                self._current.set_markdown(text)
            else:
                self._current._set_typing(False)
                if self._current._body_view is not None and not self._current._body_view.toPlainText():
                    self._current._body_view.hide()
            if self._blocks and self._blocks[-1].get("type") == "assistant":
                self._blocks[-1]["done"] = True
            self._current = None
            self._stream_text = ""
            self._scroll_to_bottom()

        def add_error(self, text: str):
            block = MessageBlock("error")
            block.set_plain_text(text)
            self._insert_before_stretch(block)
            self._blocks.append({"type": "error", "text": text})
            self._scroll_to_bottom()

        def add_welcome(self, markdown: str):
            self.clear()
            block = MessageBlock("assistant")
            block.set_markdown(markdown)
            self._insert_before_stretch(block)
            self._blocks.append(
                {"type": "assistant", "text": markdown, "tools": [], "done": True}
            )
            self._pending_separator = True
            self._scroll_to_bottom()

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
                    mb.set_plain_text(block.get("text") or "")
                    self._insert_before_stretch(mb)
                elif btype == "error":
                    mb = MessageBlock("error")
                    mb.set_plain_text(block.get("text") or "")
                    self._insert_before_stretch(mb)
                elif btype == "assistant":
                    mb = MessageBlock("assistant")
                    for tool in block.get("tools") or []:
                        name = tool.get("name") or "tool"
                        mb.add_tool_running(name)
                        if tool.get("status") == "done":
                            mb.finish_last_tool(name, tool.get("result") or "")
                    text = block.get("text") or ""
                    if text:
                        mb.set_markdown(text)
                    else:
                        mb._set_typing(False)
                    self._insert_before_stretch(mb)

            self._blocks = [dict(b) for b in blocks]
            self._current = None
            self._stream_text = ""
            self._pending_separator = bool(blocks)
            self._scroll_to_bottom()

        @property
        def blocks(self) -> List[Dict[str, Any]]:
            return self._blocks

    return ChatPanel(parent)
