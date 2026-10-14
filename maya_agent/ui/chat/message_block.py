"""One chat message block (user / assistant / error)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from maya_agent.ui import chat_format
from maya_agent.ui.chat.body_view import BodyView
from maya_agent.ui.chat.code_block import CodeBlock
from maya_agent.ui.chat.image_utils import image_b64
from maya_agent.ui.chat.thinking_row import ThinkingRow
from maya_agent.ui.chat.tool_row import ToolRow
from maya_agent.ui.qt_bind import QtCore, QtGui, QtWidgets
from maya_agent.ui.status_anim import create_typing_indicator
from maya_agent.llm.base import format_turn_meta

class Avatar(QtWidgets.QLabel):
    def __init__(self, text: str, bg: str, fg: str = "#ffffff", parent=None):
        super().__init__(text, parent)
        self.setObjectName("chatAvatar")
        self.setFixedSize(32, 32)
        self.setAlignment(QtCore.Qt.AlignCenter)
        # Dynamic role colors (user/assistant/error) — keep minimal inline
        self.setStyleSheet(
            f"QLabel#chatAvatar {{ background-color: {bg}; color: {fg}; }}"
        )

class Bubble(QtWidgets.QFrame):
    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self.setObjectName(f"bubble_{kind}")
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setMinimumWidth(0)
        # Vertical Maximum: must not absorb leftover viewport height (that
        # stretched bubbles and created a fake bottom gap).
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Maximum
        )
        # Colors from dark.qss via objectName bubble_{kind}

    def minimumSizeHint(self):
        # Never let long unwrapped children dictate row width.
        s = super().minimumSizeHint()
        return QtCore.QSize(0, s.height())

    def sizeHint(self):
        s = super().sizeHint()
        return QtCore.QSize(max(0, int(self.width()) or s.width()), s.height())

class ChoiceBar(QtWidgets.QWidget):
    """Clickable confirmation options under an assistant bubble."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("choiceBar")
        self.setMinimumWidth(0)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Maximum
        )
        self._buttons: List[Any] = []
        self._on_pick = None
        self._lay = QtWidgets.QVBoxLayout(self)
        self._lay.setContentsMargins(0, 4, 0, 0)
        self._lay.setSpacing(6)
        hint = QtWidgets.QLabel("请选择：")
        hint.setObjectName("choiceHint")
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
            self.setMaximumHeight(0)
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
            btn.setMinimumWidth(0)
            btn.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
            )
            btn.clicked.connect(
                lambda _checked=False, r=reply: self._emit(r)
            )
            self._btn_col.addWidget(btn)
            self._buttons.append(btn)
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
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
    # avatar(32) + spacing(10) + margins(8) + opposite gutter(~40)
    _CHROME_W = 90
    # Bubble : side-gutter stretch — keeps AI/user side margins symmetric.
    _BUBBLE_STRETCH = 5
    _GUTTER_STRETCH = 1

    def __init__(self, role: str, parent=None):
        super().__init__(parent)
        self.role = role
        self.setMinimumWidth(0)
        # Vertical Maximum keeps the row tight — leftover viewport space must
        # not be poured into the last bubble (fake bottom gap).
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Maximum
        )
        self._image_host = None
        self._tools: List[ToolRow] = []
        self._thinking_rows: List[Any] = []
        self._thinking_row: Optional[ThinkingRow] = None
        self._body_views: List[Any] = []
        self._body_view: Optional[BodyView] = None
        self._code_blocks: List[Any] = []
        self._inline_images: List[Any] = []
        self._choice_bar = None

        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(4, 6, 4, 6)
        root.setSpacing(10)

        self.bubble = Bubble(role if role in ("user", "assistant", "error") else "assistant")
        bubble_lay = QtWidgets.QVBoxLayout(self.bubble)
        bubble_lay.setContentsMargins(12, 10, 12, 10)
        # Spacing lives on content rows only — keeps hidden typing/meta from
        # leaving a phantom gap under short bubbles.
        bubble_lay.setSpacing(0)

        self.content = QtWidgets.QVBoxLayout()
        self.content.setContentsMargins(0, 0, 0, 0)
        self.content.setSpacing(4)
        bubble_lay.addLayout(self.content)

        self.typing = create_typing_indicator(self.bubble)
        self.typing.setFixedHeight(0)
        self.typing.setMaximumHeight(0)
        self.typing.hide()
        bubble_lay.addWidget(self.typing)

        self._meta_label = None
        self._notice_label = None
        # Symmetric gutters: user has left stretch, AI/error have right stretch
        # with the same stretch ratio so bubbles align visually.
        if role == "user":
            root.addStretch(self._GUTTER_STRETCH)
            root.addWidget(self.bubble, self._BUBBLE_STRETCH, QtCore.Qt.AlignTop)
            root.addWidget(Avatar("你", "#3d7ab8"), 0, QtCore.Qt.AlignTop)
        elif role == "error":
            root.addWidget(Avatar("!", "#8b3a3a"), 0, QtCore.Qt.AlignTop)
            root.addWidget(self.bubble, self._BUBBLE_STRETCH, QtCore.Qt.AlignTop)
            root.addStretch(self._GUTTER_STRETCH)
        else:
            root.addWidget(Avatar("AI", "#2f7d5b"), 0, QtCore.Qt.AlignTop)
            root.addWidget(self.bubble, self._BUBBLE_STRETCH, QtCore.Qt.AlignTop)
            root.addStretch(self._GUTTER_STRETCH)
            self._choice_bar = ChoiceBar(self.bubble)
            self._choice_bar.setMaximumHeight(0)
            bubble_lay.addWidget(self._choice_bar)
            self._notice_label = QtWidgets.QLabel("")
            self._notice_label.setObjectName("stopNotice")
            self._notice_label.setWordWrap(True)
            self._notice_label.setMinimumWidth(0)
            self._notice_label.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred
            )
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
            self._notice_label.setMaximumHeight(0)
            bubble_lay.addWidget(self._notice_label)
            self._meta_label = QtWidgets.QLabel("")
            self._meta_label.setObjectName("turnMeta")
            self._meta_label.setWordWrap(True)
            self._meta_label.setMinimumWidth(0)
            self._meta_label.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred
            )
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
            self._meta_label.setMaximumHeight(0)
            bubble_lay.addWidget(self._meta_label)

        self.bubble.setMinimumWidth(0)
        self.bubble.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Maximum
        )

    def minimumSizeHint(self):
        # Do not let long unwrapped text dictate row minimum width.
        s = super().minimumSizeHint()
        return QtCore.QSize(0, s.height())

    def sizeHint(self):
        s = super().sizeHint()
        w = int(self.width() or 0)
        return QtCore.QSize(w if w > 0 else s.width(), s.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._constrain_inner_widths()

    def _iter_content_rows(self):
        for i in range(self.content.count()):
            item = self.content.itemAt(i)
            w = item.widget() if item is not None else None
            if w is not None:
                yield w

    def _constrain_inner_widths(self) -> None:
        """Keep bubble within the row; let thinking/tool rows fill the bubble."""
        total = int(self.width() or 0)
        if total <= 0:
            return
        bubble_max = max(120, total - self._CHROME_W)
        width_changed = self.bubble.maximumWidth() != bubble_max
        if width_changed:
            self.bubble.setMaximumWidth(bubble_max)

        # Clear stale max-width caps so rows can pin to bubble edges when wide.
        qmax = 16777215
        for row in self._iter_content_rows():
            try:
                if row.maximumWidth() < qmax:
                    row.setMaximumWidth(qmax)
            except Exception:
                pass

        inner = max(80, int(self.bubble.width() or bubble_max) - 28)
        for label in (self._meta_label, self._notice_label):
            if label is not None and label.maximumWidth() != inner:
                label.setMaximumWidth(inner)
        if self._choice_bar is not None and self._choice_bar.maximumWidth() != inner:
            self._choice_bar.setMaximumWidth(inner)

        if width_changed:
            self._refit_all_bodies()

    def _refit_all_bodies(self) -> None:
        """Exact-fit every text body (fixes clip + post-stream empty height)."""
        for w in self._iter_content_rows():
            if isinstance(w, BodyView):
                try:
                    if getattr(w, "_streaming", False) or getattr(
                        w, "_stream_cache", None
                    ) is not None:
                        w.finish_streaming()
                    w._layout_width = 0  # allow width re-measure
                    w._refit(streaming=False)
                except Exception:
                    pass
            elif isinstance(w, CodeBlock):
                try:
                    w._fit_height()
                except Exception:
                    pass
            elif isinstance(w, ThinkingRow) and getattr(w, "_done", False):
                try:
                    w._fit_detail_height()
                except Exception:
                    pass
        if (
            self._body_view is not None
            and self._body_view.isVisible()
        ):
            try:
                if (
                    self._body_view._streaming
                    or self._body_view._stream_cache is not None
                ):
                    self._body_view.finish_streaming()
                self._body_view._layout_width = 0
                self._body_view._refit(streaming=False)
            except Exception:
                pass

    def compact(self) -> None:
        """Tighten geometry after a turn ends."""
        self._set_typing(False)
        for row in self._thinking_rows:
            try:
                if not getattr(row, "_done", True):
                    row.set_done()
                elif getattr(row, "_done", False):
                    row._fit_detail_height()
            except Exception:
                pass
        for w in self._iter_content_rows():
            if isinstance(w, BodyView):
                try:
                    w.finish_streaming()
                except Exception:
                    pass
        self._constrain_inner_widths()
        self._refit_all_bodies()
        self.bubble.updateGeometry()
        self.updateGeometry()
        # Second pass after Qt applies max-width / layout geometry.
        QtCore.QTimer.singleShot(0, self._post_layout_refit)

    def _post_layout_refit(self) -> None:
        """Re-measure body height once bubble width is final — prevents footer overlap."""
        try:
            self._constrain_inner_widths()
            self._refit_all_bodies()
            self.bubble.updateGeometry()
            self.updateGeometry()
        except Exception:
            return
        parent = self.parentWidget()
        while parent is not None:
            if hasattr(parent, "_schedule_relayout"):
                try:
                    parent._schedule_relayout()
                except Exception:
                    pass
                break
            if hasattr(parent, "_relayout_container"):
                try:
                    parent._relayout_container()
                except Exception:
                    pass
                break
            parent = parent.parentWidget()

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
            self._meta_label.setMaximumHeight(0)
            return
        self._meta_label.setText(line)
        self._meta_label.setMinimumHeight(0)
        self._meta_label.setMaximumHeight(16777215)
        self._meta_label.show()

    def set_stop_notice(self, text: str = "") -> None:
        """Show an abnormal-stop tip at the end of the assistant bubble."""
        if self._notice_label is None:
            return
        line = (text or "").strip()
        if not line:
            self._notice_label.hide()
            self._notice_label.clear()
            self._notice_label.setMaximumHeight(0)
            return
        self._notice_label.setText(line)
        self._notice_label.setMinimumHeight(0)
        self._notice_label.setMaximumHeight(16777215)
        self._notice_label.show()
        self._set_typing(False)

    def _ensure_body(self) -> BodyView:
        if self._body_view is None:
            view = BodyView(self.role, self.bubble)
            self.content.addWidget(view)
            self._body_view = view
            self._body_views.append(view)
        return self._body_view

    def set_images(self, images: Optional[List[Any]]) -> None:
        """Show thumbnails for user-attached images above the text."""
        images = [img for img in (images or []) if image_b64(img)]
        if not images:
            if self._image_host is not None:
                self._image_host.hide()
                self._image_host.setMaximumHeight(0)
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
        self._image_host.setMinimumHeight(0)
        self._image_host.setMaximumHeight(16777215)
        self._image_host.show()

    def set_plain_text(self, text: str):
        view = self._ensure_body()
        view.set_plain(text or "")
        view.setVisible(bool(text))
        self._set_typing(False)
        # Defer refit until the bubble has its final width (avoids clipped user text).
        QtCore.QTimer.singleShot(0, self._post_layout_refit)

    def _remove_current_body(self) -> None:
        """Drop the live streaming BodyView so set_markdown can replace it."""
        view = self._body_view
        if view is None:
            return
        try:
            view.finish_streaming()
        except Exception:
            pass
        try:
            self.content.removeWidget(view)
        except Exception:
            pass
        view.hide()
        view.deleteLater()
        if view in self._body_views:
            try:
                self._body_views.remove(view)
            except ValueError:
                pass
        self._body_view = None

    def _add_inline_image(self, alt: str, path: str) -> None:
        """Insert a clickable chart/image thumbnail into the bubble body."""
        import os

        from maya_agent.llm.image_codec import attachment_from_raw_file
        from maya_agent.ui.image_viewer import make_clickable_thumb

        host = QtWidgets.QWidget(self.bubble)
        host.setObjectName("inlineChartHost")
        host.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        host.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Maximum
        )
        lay = QtWidgets.QVBoxLayout(host)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(4)

        label_text = (alt or "").strip() or "图表"
        caption = QtWidgets.QLabel(label_text)
        caption.setObjectName("inlineChartCaption")
        caption.setWordWrap(True)
        caption.setStyleSheet(
            "QLabel#inlineChartCaption { color:#9aa3b5; font-size:12px; }"
        )
        lay.addWidget(caption)

        norm = (path or "").replace("\\", "/")
        if not norm or not os.path.isfile(norm):
            missing = QtWidgets.QLabel(f"（图表文件不可用：{norm or '未知路径'}）")
            missing.setObjectName("inlineChartMissing")
            missing.setWordWrap(True)
            missing.setStyleSheet(
                "QLabel#inlineChartMissing { color:#8a9099; font-size:12px;"
                " background:#1a1b20; border:1px dashed #4a5d78;"
                " border-radius:8px; padding:12px; }"
            )
            lay.addWidget(missing)
            host.show()
            self.content.addWidget(host)
            self._inline_images.append(host)
            return

        try:
            att = attachment_from_raw_file(norm)
            if not att.name:
                att.name = label_text
        except Exception:
            att = None

        if att is None or not getattr(att, "data_b64", ""):
            missing = QtWidgets.QLabel(f"（无法加载图表：{norm}）")
            missing.setWordWrap(True)
            lay.addWidget(missing)
            host.show()
            self.content.addWidget(host)
            self._inline_images.append(host)
            return

        thumb = make_clickable_thumb(
            att,
            edge=280,
            fixed_w=360,
            fixed_h=220,
            parent=host,
            gallery=[att],
            index=0,
            tooltip=label_text,
            stylesheet=(
                "QLabel { background:#1a1b20; border:1px solid #4a5d78;"
                " border-radius:8px; }"
            ),
        )
        lay.addWidget(thumb, 0, QtCore.Qt.AlignLeft)
        host.show()
        self.content.addWidget(host)
        self._inline_images.append(host)

    def set_markdown(self, text: str):
        """
        Render assistant markdown. Fenced code becomes CodeBlock widgets
        (with copy); local chart/image embeds become inline thumbnails;
        surrounding text stays as BodyView rich text.
        Replaces the current streaming body when present.
        """
        self.finish_thinking()
        self._remove_current_body()
        if not text:
            self._set_typing(False)
            return

        segments = chat_format.split_markdown_segments(text)
        if not segments:
            self._set_typing(False)
            return

        last_body: Optional[BodyView] = None
        # Plain text only → keep a single BodyView (includes HTML fence fallback).
        if len(segments) == 1 and segments[0][0] == "text":
            view = BodyView(self.role, self.bubble)
            view.set_html(chat_format.markdown_to_html(segments[0][1]))
            view.show()
            self.content.addWidget(view)
            self._body_views.append(view)
            last_body = view
        else:
            for seg in segments:
                if seg[0] == "text":
                    md = seg[1]
                    if not (md or "").strip():
                        continue
                    view = BodyView(self.role, self.bubble)
                    view.set_html(chat_format.markdown_to_html(md))
                    view.show()
                    self.content.addWidget(view)
                    self._body_views.append(view)
                    last_body = view
                elif seg[0] == "code":
                    lang = seg[1] if len(seg) > 1 else ""
                    code = seg[2] if len(seg) > 2 else ""
                    try:
                        block = CodeBlock(
                            code, language=str(lang or ""), parent=self.bubble
                        )
                        block.show()
                        self.content.addWidget(block)
                        self._code_blocks.append(block)
                    except Exception:
                        # Fallback: keep code visible as rich-text fence.
                        fence = "```{}\n{}\n```".format(lang or "", code or "")
                        view = BodyView(self.role, self.bubble)
                        view.set_html(chat_format.markdown_to_html(fence))
                        view.show()
                        self.content.addWidget(view)
                        self._body_views.append(view)
                        last_body = view
                elif seg[0] == "image":
                    alt = seg[1] if len(seg) > 1 else ""
                    path = seg[2] if len(seg) > 2 else ""
                    try:
                        self._add_inline_image(str(alt or ""), str(path or ""))
                    except Exception:
                        view = BodyView(self.role, self.bubble)
                        view.set_html(
                            chat_format.markdown_to_html(
                                f"![{alt}]({path})"
                            )
                        )
                        view.show()
                        self.content.addWidget(view)
                        self._body_views.append(view)
                        last_body = view

        self._body_view = last_body
        self._set_typing(False)
        QtCore.QTimer.singleShot(0, self._refit_all_bodies)
        QtCore.QTimer.singleShot(0, self._post_layout_refit)

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
        # Strip in-progress CHOICES / CHART so height does not spike then collapse.
        display = chat_format.strip_streaming_markers(text or "")
        # Keep the body visible once created — show/hide toggles cause jitter.
        if not view.isVisible():
            view.show()
        view.set_plain_streaming(display)
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
            self._thinking_rows.append(row)
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
        self._thinking_rows.append(row)
        self._thinking_row.set_full(text, done=True)
        self._set_typing(False)

    def add_text_segment(self, text: str) -> None:
        """Add a completed text segment at the current timeline position."""
        if not text:
            return
        # Keep _body_view so set_markdown can remove the live streaming body;
        # clearing it first leaked the old widget and left a tall empty gap.
        display, _ = chat_format.extract_user_choices(text)
        self.set_markdown(display or text)

    def _set_typing(self, on: bool):
        if on:
            self.typing.setMaximumHeight(16777215)
            self.typing.setFixedHeight(22)
            self.typing.start()
        else:
            self.typing.stop()
            self.typing.setFixedHeight(0)
            self.typing.setMaximumHeight(0)
            self.typing.hide()

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
        # Commit prior streamed text as rich markdown (+ code blocks) before tools.
        if self._body_view is not None:
            raw = getattr(self._body_view, "_stream_cache", None)
            if raw is None:
                try:
                    raw = self._body_view.toPlainText()
                except Exception:
                    raw = ""
            if (raw or "").strip():
                self.set_markdown(raw)
            else:
                try:
                    self._body_view.finish_streaming()
                    self._body_view._layout_width = 0
                    self._body_view._refit(streaming=False)
                except Exception:
                    pass
        self._body_view = None
        row = ToolRow(self.bubble)
        row.set_running(name)
        # Fill bubble content width (no stale max-width from prior narrow layout).
        row.setMaximumWidth(16777215)
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

