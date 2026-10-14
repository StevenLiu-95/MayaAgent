"""Scrollable chat panel hosting message bubbles."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from maya_agent.ui import chat_format
from maya_agent.ui.chat.image_utils import image_dicts as _image_dicts
from maya_agent.ui.chat.message_block import MessageBlock
from maya_agent.ui.qt_bind import QtCore, QtGui, QtWidgets

class TurnSeparator(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(20)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(48, 10, 48, 10)
        line = QtWidgets.QFrame()
        line.setObjectName("chatTurnSeparatorLine")
        line.setFrameShape(QtWidgets.QFrame.HLine)
        line.setFixedHeight(1)
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
        # Width is synced manually; height must follow content only.
        # widgetResizable(True) would stretch the container to the viewport
        # and pour leftover height into the last bubble / a pin spacer.
        self.scroll.setWidgetResizable(False)
        self.scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.scroll.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)

        self.container = QtWidgets.QWidget()
        self.container.setObjectName("chatContainer")
        self.container.setMinimumWidth(0)
        self.container.setSizePolicy(
            QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Maximum
        )
        self.v = QtWidgets.QVBoxLayout(self.container)
        self.v.setContentsMargins(8, 8, 8, 8)
        self.v.setSpacing(6)
        self.v.setAlignment(QtCore.Qt.AlignTop)
        self.v.setSizeConstraint(QtWidgets.QLayout.SetMinimumSize)

        self.scroll.setWidget(self.container)
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
        self._turn_charts: List[Dict[str, str]] = []
        self._pending_separator = False
        self._on_choice_reply = None
        self._active_choice_block = None
        self._stick_to_bottom = True
        self._scrolling_programmatic = False
        self._layout_timer = QtCore.QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.setInterval(24)
        self._layout_timer.timeout.connect(self._relayout_container)
        self._batch_restoring = False
        self._scroll_near_margin = 80
        self._deferred_scroll = False
        self._scroll_settle_pending = False
        self._last_scroll_max = -1
        self._bar_syncing = False

        bar = self.scroll.verticalScrollBar()
        bar.rangeChanged.connect(self._on_scroll_range_changed)
        bar.valueChanged.connect(self._on_scroll_value_changed)
        bar.rangeChanged.connect(self._sync_rail_from_inner)
        bar.valueChanged.connect(self._sync_rail_from_inner)
        self._rail_bar.valueChanged.connect(self._sync_inner_from_rail)
        self._sync_rail_from_inner()
        self._refresh_jump_buttons()

    def _schedule_relayout(self) -> None:
        """Coalesce expensive container height measurements onto one timer."""
        if self._batch_restoring:
            return
        if not self._layout_timer.isActive():
            self._layout_timer.start()

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
        self._constrain_container_width()
        self._sync_rail_from_inner()
        self._refresh_jump_buttons()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._constrain_container_width()

    def _constrain_container_width(self) -> None:
        """Sync scroll widget size to viewport width + content height."""
        self._relayout_container()

    def _measure_content_height(self) -> int:
        """
        Tight height from visible children sizeHints (after exact-fit).

        Never shrink to a shorter laid-out geometry: if the container was
        previously too short, last.height() is undersized and min(summed, geo)
        would lock in clipped / overlapping bubble footers.
        """
        margins = self.v.contentsMargins()
        top_m = int(margins.top())
        bottom_m = int(margins.bottom())
        spacing = int(self.v.spacing() or 0)
        visible = [
            w for w in self._widgets if w is not None and w.isVisible()
        ]
        if not visible:
            return 1

        summed = top_m + bottom_m
        for i, w in enumerate(visible):
            hint_h = int(w.sizeHint().height() or 0)
            geo_h = int(w.height() or 0)
            # Prefer the larger of hint vs geometry so a just-grown body is
            # not measured with a stale short height.
            h = max(hint_h, geo_h)
            if h <= 0:
                h = max(int(w.minimumSizeHint().height() or 0), 1)
            summed += h
            if i:
                summed += spacing

        last = visible[-1]
        ly = int(last.y())
        lh = max(int(last.height() or 0), int(last.sizeHint().height() or 0))
        if lh > 0 and ly >= top_m:
            geo_bottom = ly + lh + bottom_m
            # Grow to cover laid-out bottom; never shrink below sizeHint sum.
            if geo_bottom > summed:
                return max(1, geo_bottom)
        return max(1, summed)

    def _relayout_container(self) -> None:
        """
        Width = viewport (no horizontal overflow).
        Height = content only (never stretched to fill the viewport).
        """
        vp = self.scroll.viewport()
        if vp is None:
            return
        w = int(vp.width() or 0)
        if w <= 0:
            return
        if self.container.width() != w:
            self.container.setFixedWidth(w)
        for wdg in self._widgets:
            if isinstance(wdg, MessageBlock):
                try:
                    wdg._constrain_inner_widths()
                except Exception:
                    pass
        # Tighten the newest bubble before measuring (stream leftovers).
        if self._widgets:
            tail = self._widgets[-1]
            if isinstance(tail, MessageBlock):
                try:
                    tail._refit_all_bodies()
                except Exception:
                    pass
        # Activate layout, then size height to the real content bottom.
        self.v.activate()
        hint_h = self._measure_content_height()
        if self.container.height() != hint_h:
            self.container.setFixedHeight(hint_h)
        else:
            self.container.updateGeometry()

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
        self._blocks.clear()
        self._widgets.clear()
        self._current = None
        self._stream_text = ""
        self._thinking_text = ""
        self._turn_charts = []
        self._pending_separator = False
        self._active_choice_block = None
        self._stick_to_bottom = True
        self._deferred_scroll = False
        self._scroll_settle_pending = False
        self._last_scroll_max = -1
        self._refresh_jump_buttons()
        self._schedule_relayout()

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
        """Append a chat row (name kept for call-site compatibility)."""
        self.v.addWidget(widget)
        self._widgets.append(widget)
        if not self._batch_restoring:
            self._schedule_relayout()

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
        # Only chase content growth. Shrink / layout noise must not yank scroll.
        prev = int(getattr(self, "_last_scroll_max", -1))
        self._last_scroll_max = int(_mx)
        if self._stick_to_bottom and int(_mx) > prev:
            self._schedule_scroll_bottom()

    def _apply_scroll_bottom(self) -> None:
        bar = self.scroll.verticalScrollBar()
        target = int(bar.maximum())
        cur = int(bar.value())
        if cur >= target:
            return
        self._scrolling_programmatic = True
        try:
            bar.setValue(target)
        finally:
            self._scrolling_programmatic = False

    def _schedule_scroll_bottom(self) -> None:
        if self._deferred_scroll:
            return
        self._deferred_scroll = True
        # ~1 frame coalesce — avoid zero-delay + settle double-pump jitter.
        QtCore.QTimer.singleShot(16, self._flush_deferred_scroll)

    def _scroll_to_bottom(self, force: bool = False):
        """Scroll to bottom. Soft (default): only while stick-to-bottom is on."""
        if force:
            self._stick_to_bottom = True
        elif not self._stick_to_bottom:
            return
        self._schedule_scroll_bottom()

    def _flush_deferred_scroll(self) -> None:
        self._deferred_scroll = False
        # Keep container height in sync with growing bubbles before scrolling.
        self._relayout_container()
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
        self._turn_charts = []
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
            self._schedule_relayout()

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
            # parts is the sole timeline; derive tools[] only at persist time
            self._parts().append(
                {"kind": "tool", "name": name, "status": "running"}
            )
        self._schedule_relayout()
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
        # Update parts only — no full relayout on progress ticks
        for p in reversed(self._parts()):
            if p.get("kind") == "tool" and p.get("status") == "running" and (
                not name or p.get("name") == name
            ):
                if progress is not None:
                    p["progress"] = progress
                if status:
                    p["task_status"] = status
                break

    def tool_end(self, name: str, result: str, images: Optional[List[Any]] = None):
        if not self._ensure_open_assistant():
            return
        self._current.finish_last_tool(name, result, images=images)
        if name == "generate_chart":
            parsed = chat_format.parse_chart_tool_result(result)
            if parsed:
                self._turn_charts.append(parsed)
        block = self._assistant_block()
        if block is not None:
            stored = _image_dicts(images)
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
        self._schedule_relayout()
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
        # Fix mangled chart paths and append any charts still missing from body.
        if self._turn_charts:
            text = chat_format.ensure_charts_in_body(text or "", self._turn_charts)
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
            # Persist chart-augmented final segment for session restore.
            parts = self._parts()
            if parts and parts[-1].get("kind") == "text":
                parts[-1]["text"] = text
            elif (text or "").strip():
                parts.append({"kind": "text", "text": text})
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
        # Tighten heights/widths so cancelled/finished turns leave no phantom gap.
        try:
            self._current.compact()
        except Exception:
            pass
        self._schedule_relayout()
        block = self._assistant_block()
        if block is not None:
            block["done"] = True
            parts = block.get("parts") or []
            # Derived summary fields for older readers / debugging
            agg_text = "".join(
                p.get("text") or "" for p in parts if p.get("kind") == "text"
            )
            agg_think = "".join(
                p.get("text") or "" for p in parts if p.get("kind") == "thinking"
            )
            if agg_text:
                block["text"] = agg_text
            elif text:
                block["text"] = text
            if agg_think:
                block["thinking"] = agg_think
            elif self._thinking_text:
                block["thinking"] = self._thinking_text
            block["tools"] = [
                {
                    "name": p.get("name") or "tool",
                    "status": p.get("status") or "done",
                    **(
                        {"result": p["result"]}
                        if p.get("result") is not None
                        else {}
                    ),
                    **({"images": p["images"]} if p.get("images") else {}),
                    **(
                        {"progress": p["progress"]}
                        if p.get("progress") is not None
                        else {}
                    ),
                }
                for p in parts
                if p.get("kind") == "tool"
            ]
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
        self._turn_charts = []
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
        self._batch_restoring = True
        self.setUpdatesEnabled(False)
        try:
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
            for wdg in self._widgets:
                if isinstance(wdg, MessageBlock):
                    try:
                        wdg.compact()
                    except Exception:
                        pass
        finally:
            self._batch_restoring = False
            self.setUpdatesEnabled(True)
        self._refresh_jump_buttons()
        self._relayout_container()
        self._scroll_to_bottom(force=True)

    @property
    def blocks(self) -> List[Dict[str, Any]]:
        return self._blocks

