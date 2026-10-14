"""Fenced code block widget with copy button."""

from __future__ import annotations

from maya_agent.ui.qt_bind import QtCore, QtGui, QtWidgets

class _CodePlainEdit(QtWidgets.QPlainTextEdit):
    """Code body: no wheel scrolling — horizontal only via scrollbar drag."""

    def wheelEvent(self, event):
        # No inner vertical pan — scroll the chat panel; h-bar is drag-only.
        from maya_agent.ui.qt_wheel import redirect_wheel_to_parent_scroll

        if redirect_wheel_to_parent_scroll(self, event):
            return
        event.ignore()

    def scrollContentsBy(self, dx, dy):
        # Block vertical content offset even if something sets scrollbar value.
        super().scrollContentsBy(dx, 0)

class CodeBlock(QtWidgets.QFrame):
    """Fenced code block: no wrap, horizontal scroll, tight height."""

    _COPY_BTN = 18
    _COPY_ICON = 12
    _HEADER_H = 26
    _DOC_MARGIN = 8
    _H_SCROLL_H = 10

    @staticmethod
    def _make_icon(kind: str, color: str, size: int = 12) -> "QtGui.QIcon":
        """Paint a tiny copy / check glyph — no external image assets."""
        dpr = 1.0
        try:
            app = QtWidgets.QApplication.instance()
            if app is not None:
                dpr = float(app.devicePixelRatio() or 1.0)
        except Exception:
            dpr = 1.0
        px = max(1, int(round(size * max(dpr, 1.0))))
        img = QtGui.QImage(px, px, QtGui.QImage.Format_ARGB32_Premultiplied)
        img.fill(QtCore.Qt.transparent)
        try:
            img.setDevicePixelRatio(dpr)
        except Exception:
            pass
        p = QtGui.QPainter(img)
        try:
            p.setRenderHint(QtGui.QPainter.Antialiasing, True)
            pen = QtGui.QPen(QtGui.QColor(color))
            pen.setWidthF(max(1.0, 1.2 * max(dpr, 1.0)))
            pen.setJoinStyle(QtCore.Qt.RoundJoin)
            pen.setCapStyle(QtCore.Qt.RoundCap)
            p.setPen(pen)
            p.setBrush(QtCore.Qt.NoBrush)
            s = float(px)
            if kind == "check":
                path = QtGui.QPainterPath()
                path.moveTo(s * 0.18, s * 0.52)
                path.lineTo(s * 0.40, s * 0.74)
                path.lineTo(s * 0.82, s * 0.26)
                p.drawPath(path)
            else:
                m = s * 0.12
                r = max(1.0, s * 0.12)
                p.drawRoundedRect(
                    QtCore.QRectF(m + s * 0.18, m, s * 0.58, s * 0.58), r, r
                )
                p.drawRoundedRect(
                    QtCore.QRectF(m, m + s * 0.18, s * 0.58, s * 0.58), r, r
                )
        finally:
            p.end()
        return QtGui.QIcon(QtGui.QPixmap.fromImage(img))

    def __init__(self, code: str, language: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("chatCodeBlock")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setMinimumWidth(0)
        self.setMaximumWidth(16777215)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
        )
        self._code = code or ""
        self._lang = (language or "").strip()
        self._fit_guard = False

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QtWidgets.QWidget()
        header.setObjectName("chatCodeHeader")
        header.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        header.setFixedHeight(self._HEADER_H)
        h_lay = QtWidgets.QHBoxLayout(header)
        h_lay.setContentsMargins(10, 0, 6, 0)
        h_lay.setSpacing(6)

        from maya_agent.i18n import t

        label_txt = self._lang if self._lang else t("chat.code", default="代码")
        self._lang_label = QtWidgets.QLabel(label_txt)
        self._lang_label.setObjectName("chatCodeLang")
        self._lang_label.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)

        try:
            self._icon_copy = self._make_icon("copy", "#a8a8b0", self._COPY_ICON)
            self._icon_copied = self._make_icon("check", "#9fd4b0", self._COPY_ICON)
        except Exception:
            self._icon_copy = QtGui.QIcon()
            self._icon_copied = QtGui.QIcon()

        self._copy_btn = QtWidgets.QToolButton()
        self._copy_btn.setObjectName("chatCodeCopyBtn")
        self._copy_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._copy_btn.setAutoRaise(True)
        self._copy_btn.setFocusPolicy(QtCore.Qt.NoFocus)
        self._copy_btn.setFixedSize(self._COPY_BTN, self._COPY_BTN)
        self._copy_btn.setIconSize(QtCore.QSize(self._COPY_ICON, self._COPY_ICON))
        if not self._icon_copy.isNull():
            self._copy_btn.setIcon(self._icon_copy)
        else:
            self._copy_btn.setText("⎘")
        self._copy_btn.setToolTip(t("chat.copy_tip", default="复制到剪贴板"))
        self._copy_btn.clicked.connect(self._copy)

        h_lay.addWidget(self._lang_label, 1)
        h_lay.addWidget(self._copy_btn, 0, QtCore.Qt.AlignVCenter)

        self._body = _CodePlainEdit()
        self._body.setObjectName("chatCodeBody")
        self._body.setReadOnly(True)
        self._body.setFrameShape(QtWidgets.QFrame.NoFrame)
        self._body.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self._body.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self._body.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self._body.setTabChangesFocus(True)
        self._body.setMinimumWidth(0)
        self._body.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
        )
        try:
            font = QtGui.QFont("Consolas")
            if not font.exactMatch():
                font = QtGui.QFont("Courier New")
            font.setStyleHint(QtGui.QFont.Monospace)
            font.setPointSize(10)
            self._body.setFont(font)
        except Exception:
            pass
        try:
            self._body.document().setDocumentMargin(self._DOC_MARGIN)
        except Exception:
            pass
        # Keep original newlines/paths — no soft-break, no wrap.
        self._body.setPlainText(self._code)
        # Lock vertical scroll position (scrollbar already hidden).
        try:
            vbar = self._body.verticalScrollBar()
            vbar.setEnabled(False)
            vbar.setRange(0, 0)
            vbar.valueChanged.connect(lambda _v: vbar.setValue(0))
        except Exception:
            pass
        # Horizontal bar: drag only — swallow wheel when cursor is on the bar.
        try:
            hbar = self._body.horizontalScrollBar()
            hbar.installEventFilter(self)
        except Exception:
            pass

        root.addWidget(header)
        root.addWidget(self._body)

        # Immediate tight height from line count (avoids a tall empty flash).
        self._body.setFixedHeight(self._calc_height(include_hscroll=False))

        self.setStyleSheet(
            """
            QFrame#chatCodeBlock {
                background-color: #16171c;
                border: 1px solid #3a3b48;
                border-radius: 8px;
            }
            QWidget#chatCodeHeader {
                background-color: #1c1d24;
                border: none;
                border-bottom: 1px solid #2e2f38;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
            }
            QLabel#chatCodeLang {
                background: transparent;
                border: none;
                color: #8a8a93;
                font-size: 11px;
                font-weight: 600;
            }
            QToolButton#chatCodeCopyBtn {
                background: transparent;
                border: none;
                border-radius: 4px;
                padding: 2px;
                margin: 0px;
                color: #a8a8b0;
                font-size: 12px;
            }
            QToolButton#chatCodeCopyBtn:hover {
                background-color: #2a2b34;
            }
            QToolButton#chatCodeCopyBtn:pressed {
                background-color: #32333c;
            }
            QPlainTextEdit#chatCodeBody {
                background-color: #16171c;
                border: none;
                border-bottom-left-radius: 8px;
                border-bottom-right-radius: 8px;
                color: #d4d4da;
                padding: 0px;
                selection-background-color: #3a4a62;
            }
            QPlainTextEdit#chatCodeBody QScrollBar:vertical {
                width: 0px;
                height: 0px;
                background: transparent;
            }
            QPlainTextEdit#chatCodeBody QScrollBar:horizontal {
                background: #16171c;
                height: 10px;
                margin: 0px 6px 2px 6px;
                border: none;
            }
            QPlainTextEdit#chatCodeBody QScrollBar::handle:horizontal {
                background: #4a4b56;
                border-radius: 4px;
                min-width: 28px;
            }
            QPlainTextEdit#chatCodeBody QScrollBar::handle:horizontal:hover {
                background: #5b8fc7;
            }
            QPlainTextEdit#chatCodeBody QScrollBar::add-line:horizontal,
            QPlainTextEdit#chatCodeBody QScrollBar::sub-line:horizontal {
                width: 0px;
                height: 0px;
            }
            QPlainTextEdit#chatCodeBody QScrollBar::add-page:horizontal,
            QPlainTextEdit#chatCodeBody QScrollBar::sub-page:horizontal {
                background: transparent;
            }
            """
        )
        self._copy_timer = QtCore.QTimer(self)
        self._copy_timer.setSingleShot(True)
        self._copy_timer.timeout.connect(self._reset_copy_icon)
        QtCore.QTimer.singleShot(0, self._fit_height)

    def minimumSizeHint(self):
        return QtCore.QSize(0, self._HEADER_H + max(24, int(self._body.height() or 24)))

    def sizeHint(self):
        w = int(self.width() or 0)
        return QtCore.QSize(w if w > 0 else 200, self._HEADER_H + int(self._body.height() or 24))

    def showEvent(self, event):
        super().showEvent(event)
        QtCore.QTimer.singleShot(0, self._fit_height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_height()

    def eventFilter(self, obj, event):
        # Block wheel on the horizontal scrollbar; mouse drag still works.
        try:
            if obj is self._body.horizontalScrollBar():
                if event.type() == QtCore.QEvent.Wheel:
                    event.ignore()
                    return True
        except Exception:
            pass
        return super().eventFilter(obj, event)

    def _calc_height(self, *, include_hscroll: bool) -> int:
        """Exact height for NoWrap content (+ optional horizontal scrollbar)."""
        fm = self._body.fontMetrics()
        lines = max(1, self._code.count("\n") + 1)
        try:
            lines = max(lines, int(self._body.document().blockCount() or 1))
        except Exception:
            pass
        # Prefer document layout height when available (more accurate than
        # lineSpacing * N on some Maya/Qt builds).
        doc_h = 0
        try:
            doc = self._body.document()
            doc.setTextWidth(-1)
            doc_h = int(doc.size().height() + 0.999)
        except Exception:
            doc_h = 0
        line_h = lines * int(fm.lineSpacing()) + 2 * self._DOC_MARGIN
        h = max(doc_h, line_h) + 2
        if include_hscroll:
            h += self._H_SCROLL_H
        return max(24, h)

    def _needs_hscroll(self) -> bool:
        try:
            doc = self._body.document()
            # -1 => do not wrap; idealWidth is the full content width.
            doc.setTextWidth(-1)
            ideal = float(doc.idealWidth() or 0)
            view_w = float(self._body.viewport().width() or 0)
            if view_w <= 1:
                view_w = float(max(0, int(self.width() or 0) - 4))
            return ideal > view_w + 1.0
        except Exception:
            return False

    def _fit_height(self) -> None:
        if self._fit_guard:
            return
        self._fit_guard = True
        try:
            need_bar = self._needs_hscroll()
            h = self._calc_height(include_hscroll=need_bar)
            if self._body.height() != h:
                self._body.setFixedHeight(h)
                self.updateGeometry()
            # Keep vertical scroll disabled after layout.
            try:
                vbar = self._body.verticalScrollBar()
                vbar.setRange(0, 0)
                vbar.setValue(0)
            except Exception:
                pass
        finally:
            self._fit_guard = False

    def _copy(self) -> None:
        clip = QtWidgets.QApplication.clipboard()
        if clip is None:
            return
        clip.setText(self._code)
        from maya_agent.i18n import t

        if not self._icon_copied.isNull():
            self._copy_btn.setIcon(self._icon_copied)
        else:
            self._copy_btn.setText("✓")
        self._copy_btn.setToolTip(t("chat.copied", default="已复制"))
        self._copy_timer.start(1400)

    def _reset_copy_icon(self) -> None:
        from maya_agent.i18n import t

        if not self._icon_copy.isNull():
            self._copy_btn.setIcon(self._icon_copy)
            self._copy_btn.setText("")
        else:
            self._copy_btn.setText("⎘")
        self._copy_btn.setToolTip(t("chat.copy_tip", default="复制到剪贴板"))

