"""Collapsible tool-call row for chat bubbles."""

from __future__ import annotations

from typing import Any, List, Optional

from maya_agent.ui import chat_format
from maya_agent.ui.palette import SPINNER_FRAMES
from maya_agent.ui.qt_bind import QtCore, QtGui, QtWidgets

_SPINNER = SPINNER_FRAMES

class ToolRow(QtWidgets.QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("toolRow")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setMinimumWidth(0)
        self.setMaximumWidth(16777215)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Maximum
        )
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(4)
        self.title = QtWidgets.QLabel("⚙ …")
        self.title.setWordWrap(False)
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
        self.status = QtWidgets.QLabel("")
        self.status.setObjectName("toolStatus")
        self.status.setWordWrap(True)
        self.status.setMinimumWidth(0)
        self.status.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred
        )
        self.status.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.status.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.status.hide()
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
        self.detail.hide()
        self.expand_btn = QtWidgets.QPushButton("展开全部 ▾")
        self.expand_btn.setObjectName("toolExpandBtn")
        self.expand_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.expand_btn.setFlat(True)
        self.expand_btn.setFixedHeight(22)
        self.expand_btn.clicked.connect(self._toggle_expand)
        self.expand_btn.hide()
        lay.addWidget(self.title)
        lay.addWidget(self.bar)
        lay.addWidget(self.status)
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
        self._full_html = ""
        self._expanded = False
        self._has_images = False

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
            )
            self._image_lay.insertWidget(self._image_lay.count() - 1, label)
            shown += 1
        self._has_images = shown > 0
        # Viewport thumbnails stay visible in both collapsed and expanded states.
        self._image_host.setVisible(self._has_images)

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
            QFrame#toolRow QLabel#toolStatus {{
                color: #d0c8a8;
                font-size: 12px;
                font-weight: 400;
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
                QFrame#toolRow QLabel#toolStatus {
                    color: #d0d0d6;
                    font-size: 12px;
                    font-weight: 400;
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
            QFrame#toolRow QLabel#toolStatus {
                color: #e0b0b0;
                font-size: 12px;
                font-weight: 400;
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
        n = self._anim_frame % 4
        dots = "." * n + "\u00a0" * (3 - n)
        suffix = self._progress_suffix()
        # Fixed-width title pulse — avoid sizeHint/layout thrash.
        self.title.setText(
            f"{spin} 正在执行  {self._running_name}{suffix}{dots}"
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Cap wrapped labels so long tool JSON cannot widen the bubble.
        if self._anim_timer.isActive():
            return
        inner = max(80, int(self.width()) - 24)
        self.title.setMaximumWidth(inner)
        self.status.setMaximumWidth(inner)
        self.detail.setMaximumWidth(inner)
        if self._expanded and self.detail.isVisible():
            self._fit_detail_height()

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
        self.status.hide()
        self.status.clear()
        self.detail.setText("")
        self.detail.hide()
        self.expand_btn.hide()
        self._full_html = ""
        self._expanded = False
        self._has_images = False
        self._image_host.hide()
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
        title, status, full, ok, needs_expand = (
            chat_format.summarize_tool_result_views(name, result_json)
        )
        self.setStyleSheet(self._done_stylesheet(ok))
        self.title.setText(f"⚙ {title}")
        if status:
            self.status.setText(status)
            self.status.show()
        else:
            self.status.clear()
            self.status.hide()
        self._full_html = full or ""
        self._expanded = False
        # Collapsed: header (title + status) + thumbnails; hide detail body.
        self.detail.clear()
        self.detail.hide()
        self.detail.setFixedHeight(0)
        self._image_host.setVisible(self._has_images)
        if needs_expand and self._full_html:
            self.expand_btn.setText("展开全部 ▾")
            self.expand_btn.show()
        else:
            self.expand_btn.hide()

    def _estimate_html_height(self, width: int) -> int:
        """QTextDocument height — more reliable than QLabel for rich tables."""
        try:
            doc = QtGui.QTextDocument()
            doc.setDocumentMargin(0)
            doc.setHtml(self.detail.text() or "")
            doc.setTextWidth(max(80, int(width)))
            return max(int(doc.size().height() + 0.999) + 4, 16)
        except Exception:
            return 0

    def _fit_detail_height(self) -> None:
        """Exact-fit expanded detail so long tool output is not clipped."""
        if not self.detail.isVisible() or not (self.detail.text() or "").strip():
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
        doc_h = self._estimate_html_height(inner)
        if doc_h > 0:
            h = max(h, doc_h)
        if h <= 0:
            try:
                h = int(self.detail.sizeHint().height() or 0)
            except Exception:
                h = 0
        self.detail.setFixedHeight(max(16, h))

    def _notify_chat_layout(self) -> None:
        parent = self.parentWidget()
        while parent is not None:
            if hasattr(parent, "_schedule_relayout"):
                try:
                    parent._schedule_relayout()
                except Exception:
                    pass
            elif hasattr(parent, "_relayout_container"):
                try:
                    parent._relayout_container()
                except Exception:
                    pass
            if hasattr(parent, "_scroll_to_bottom"):
                parent._scroll_to_bottom()
                break
            parent = parent.parentWidget()

    def _toggle_expand(self):
        if not self._full_html:
            return
        self._expanded = not self._expanded
        if self._expanded:
            self.detail.setText(self._full_html)
            self.detail.show()
            self._fit_detail_height()
            self.expand_btn.setText("收起 ▴")
        else:
            self.detail.clear()
            self.detail.hide()
            self.detail.setFixedHeight(0)
            self.expand_btn.setText("展开全部 ▾")
        # Thumbnails remain visible while collapsed.
        self._image_host.setVisible(self._has_images)
        self.detail.updateGeometry()
        self.updateGeometry()
        self._notify_chat_layout()

