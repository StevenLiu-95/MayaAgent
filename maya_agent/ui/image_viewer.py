"""Fullscreen-ish image viewer for chat / attachment thumbnails."""

from __future__ import annotations

import base64
from typing import Any, List, Optional, Sequence, Union

from maya_agent.llm.base import ImageAttachment
from maya_agent.utils.maya_compat import import_qt

_ImageSource = Union[ImageAttachment, dict]

_active_viewer = None  # keep one viewer alive; replaced on re-open


def _as_attachment(img: _ImageSource) -> Optional[ImageAttachment]:
    if isinstance(img, ImageAttachment):
        return img if img.data_b64 else None
    if isinstance(img, dict) and img.get("data_b64"):
        return ImageAttachment.from_dict(img)
    return None


def qimage_from_attachment(att: ImageAttachment):
    """Decode full-resolution QImage from an attachment (no thumbnail downscale)."""
    _QtCore, QtGui, _QtWidgets, _ = import_qt()
    if not att or not att.data_b64:
        return QtGui.QImage()
    try:
        raw = base64.b64decode(att.data_b64)
    except Exception:
        return QtGui.QImage()
    image = QtGui.QImage()
    if not image.loadFromData(raw):
        return QtGui.QImage()
    return image


def show_image_viewer(
    images: Union[_ImageSource, Sequence[_ImageSource]],
    *,
    index: int = 0,
    parent=None,
    title: str = "",
):
    """
    Open a dark image viewer dialog.

    ``images`` may be one attachment/dict or a list (gallery with ←/→).
    """
    global _active_viewer
    QtCore, QtGui, QtWidgets, _ = import_qt()

    if isinstance(images, (list, tuple)):
        gallery = [_as_attachment(x) for x in images]
        gallery = [g for g in gallery if g is not None]
    else:
        one = _as_attachment(images)
        gallery = [one] if one else []
    if not gallery:
        return None

    idx = max(0, min(int(index or 0), len(gallery) - 1))

    class ImageViewerDialog(QtWidgets.QDialog):
        def __init__(self, items: List[ImageAttachment], start: int, parent=None):
            super().__init__(parent)
            self.setObjectName("imageViewerDialog")
            self.setWindowTitle(title or "图片查看")
            self.setModal(False)
            self.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
            try:
                self.setWindowFlag(QtCore.Qt.Window, True)
            except Exception:
                pass
            self._items = items
            self._index = start
            self._zoom = 1.0
            self._fit = True
            self._dragging = False
            self._drag_origin = None  # QPoint
            self._drag_scroll = None  # (h, v)

            self.setMinimumSize(480, 360)
            self.resize(900, 640)
            self.setStyleSheet(
                """
                QDialog#imageViewerDialog {
                    background-color: #1a1b20;
                }
                QLabel#viewerTitle {
                    color: #e8e8ea;
                    font-size: 13px;
                    font-weight: 600;
                }
                QLabel#viewerHint {
                    color: #8a8a93;
                    font-size: 11px;
                }
                QPushButton#viewerBtn {
                    background-color: #2c2d36;
                    color: #e8e8ea;
                    border: 1px solid #4a4b56;
                    border-radius: 6px;
                    padding: 4px 12px;
                    min-height: 28px;
                }
                QPushButton#viewerBtn:hover {
                    background-color: #3a3b44;
                    border-color: #5a8fc4;
                }
                QPushButton#viewerBtn:disabled {
                    color: #5a5b64;
                    border-color: #2c2d36;
                }
                QScrollArea#viewerScroll {
                    background: #121318;
                    border: 1px solid #2c2d36;
                    border-radius: 8px;
                }
                """
            )

            root = QtWidgets.QVBoxLayout(self)
            root.setContentsMargins(12, 10, 12, 10)
            root.setSpacing(8)

            header = QtWidgets.QHBoxLayout()
            self._title_lbl = QtWidgets.QLabel("")
            self._title_lbl.setObjectName("viewerTitle")
            self._hint_lbl = QtWidgets.QLabel(
                "左键拖动 · 滚轮缩放 · 双击适应窗口 · Esc 关闭"
            )
            self._hint_lbl.setObjectName("viewerHint")
            header.addWidget(self._title_lbl, 1)
            header.addWidget(self._hint_lbl, 0, QtCore.Qt.AlignRight)
            root.addLayout(header)

            self._scroll = QtWidgets.QScrollArea()
            self._scroll.setObjectName("viewerScroll")
            self._scroll.setWidgetResizable(False)
            self._scroll.setAlignment(QtCore.Qt.AlignCenter)
            self._image_lbl = QtWidgets.QLabel()
            self._image_lbl.setAlignment(QtCore.Qt.AlignCenter)
            self._image_lbl.setStyleSheet("background: transparent;")
            self._image_lbl.setMinimumSize(1, 1)
            self._image_lbl.setCursor(QtCore.Qt.OpenHandCursor)
            self._scroll.setWidget(self._image_lbl)
            root.addWidget(self._scroll, 1)

            bar = QtWidgets.QHBoxLayout()
            bar.setSpacing(8)
            self._prev_btn = QtWidgets.QPushButton("← 上一张")
            self._prev_btn.setObjectName("viewerBtn")
            self._prev_btn.clicked.connect(lambda: self._nav(-1))
            self._fit_btn = QtWidgets.QPushButton("适应窗口")
            self._fit_btn.setObjectName("viewerBtn")
            self._fit_btn.clicked.connect(self._fit_to_view)
            self._zoom_out = QtWidgets.QPushButton("−")
            self._zoom_out.setObjectName("viewerBtn")
            self._zoom_out.setFixedWidth(36)
            self._zoom_out.clicked.connect(lambda: self._nudge_zoom(0.85))
            self._zoom_in = QtWidgets.QPushButton("+")
            self._zoom_in.setObjectName("viewerBtn")
            self._zoom_in.setFixedWidth(36)
            self._zoom_in.clicked.connect(lambda: self._nudge_zoom(1.15))
            self._next_btn = QtWidgets.QPushButton("下一张 →")
            self._next_btn.setObjectName("viewerBtn")
            self._next_btn.clicked.connect(lambda: self._nav(1))
            self._save_btn = QtWidgets.QPushButton("保存图片")
            self._save_btn.setObjectName("viewerBtn")
            self._save_btn.clicked.connect(self._save_image)
            bar.addWidget(self._prev_btn)
            bar.addStretch(1)
            bar.addWidget(self._zoom_out)
            bar.addWidget(self._fit_btn)
            bar.addWidget(self._zoom_in)
            bar.addStretch(1)
            bar.addWidget(self._next_btn)
            bar.addWidget(self._save_btn)
            root.addLayout(bar)

            self._source = QtGui.QImage()
            self._image_lbl.installEventFilter(self)
            self._scroll.viewport().installEventFilter(self)
            self._load_current()

        def _load_current(self) -> None:
            att = self._items[self._index]
            self._source = qimage_from_attachment(att)
            name = att.name or att.mime or "图片"
            if len(self._items) > 1:
                name = f"{name}  ({self._index + 1}/{len(self._items)})"
            self._title_lbl.setText(name)
            multi = len(self._items) > 1
            self._prev_btn.setEnabled(multi and self._index > 0)
            self._next_btn.setEnabled(multi and self._index < len(self._items) - 1)
            self._prev_btn.setVisible(multi)
            self._next_btn.setVisible(multi)
            self._save_btn.setEnabled(not self._source.isNull())
            self._fit = True
            self._zoom = 1.0
            self._dragging = False
            self._image_lbl.setCursor(QtCore.Qt.OpenHandCursor)
            self._render()

        def _nav(self, delta: int) -> None:
            nxt = self._index + delta
            if 0 <= nxt < len(self._items):
                self._index = nxt
                self._load_current()

        def _default_save_name(self) -> str:
            att = self._items[self._index]
            name = (att.name or "").strip() or "maya_agent_image"
            # strip path fragments
            name = name.replace("\\", "/").rsplit("/", 1)[-1]
            low = name.lower()
            if not low.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")):
                mime = (att.mime or "").lower()
                if "png" in mime:
                    name += ".png"
                elif "webp" in mime:
                    name += ".webp"
                elif "gif" in mime:
                    name += ".gif"
                else:
                    name += ".jpg"
            return name

        def _save_image(self) -> None:
            if self._source is None or self._source.isNull():
                QtWidgets.QMessageBox.warning(self, "保存图片", "当前没有可保存的图片。")
                return
            path, selected = QtWidgets.QFileDialog.getSaveFileName(
                self,
                "保存图片",
                self._default_save_name(),
                "JPEG 图片 (*.jpg *.jpeg);;PNG 图片 (*.png);;所有文件 (*.*)",
            )
            if not path:
                return
            low = path.lower()
            if low.endswith((".png",)):
                fmt = "PNG"
            elif low.endswith((".jpg", ".jpeg")):
                fmt = "JPEG"
            elif low.endswith((".bmp",)):
                fmt = "BMP"
            elif low.endswith((".webp",)):
                fmt = "WEBP"
            else:
                # Infer from filter / mime
                if "png" in (selected or "").lower():
                    path += ".png"
                    fmt = "PNG"
                else:
                    path += ".jpg"
                    fmt = "JPEG"
            ok = self._source.save(path, fmt, 92 if fmt == "JPEG" else -1)
            if not ok:
                # Fallback: write original bytes when Qt format save fails
                att = self._items[self._index]
                try:
                    raw = base64.b64decode(att.data_b64 or "")
                    if not raw:
                        raise ValueError("空数据")
                    with open(path, "wb") as f:
                        f.write(raw)
                    ok = True
                except Exception as e:
                    QtWidgets.QMessageBox.warning(
                        self, "保存图片", f"保存失败：{e}"
                    )
                    return
            if ok:
                self._title_lbl.setText(
                    f"{self._title_lbl.text().split('  ·  已保存')[0]}  ·  已保存"
                )

        def _viewport_size(self):
            vp = self._scroll.viewport().size()
            return max(vp.width() - 8, 40), max(vp.height() - 8, 40)

        def _render(self) -> None:
            if self._source is None or self._source.isNull():
                self._image_lbl.setText("无法解码图片")
                self._image_lbl.resize(200, 80)
                return
            w, h = self._source.width(), self._source.height()
            vw, vh = self._viewport_size()
            if self._fit:
                scale = min(vw / max(w, 1), vh / max(h, 1), 1.0)
                self._zoom = scale
            tw = max(1, int(w * self._zoom))
            th = max(1, int(h * self._zoom))
            scaled = self._source.scaled(
                tw,
                th,
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation,
            )
            self._image_lbl.setPixmap(QtGui.QPixmap.fromImage(scaled))
            self._image_lbl.resize(scaled.size())

        def _fit_to_view(self) -> None:
            self._fit = True
            self._render()

        def _nudge_zoom(self, factor: float, anchor_vp=None) -> None:
            """
            Zoom by ``factor``. When ``anchor_vp`` (viewport coords) is given,
            keep the image point under that position fixed (zoom-to-cursor).
            """
            self._fit = False
            old_zoom = max(float(self._zoom), 1e-9)
            new_zoom = max(0.05, min(8.0, old_zoom * float(factor)))
            if abs(new_zoom - old_zoom) < 1e-12:
                return

            vp = self._scroll.viewport()
            if anchor_vp is None:
                anchor_vp = QtCore.QPoint(vp.width() // 2, vp.height() // 2)

            old_w = max(1, self._image_lbl.width())
            old_h = max(1, self._image_lbl.height())
            pos_in_label = self._image_lbl.mapFrom(vp, anchor_vp)
            # If cursor is outside the image (letterbox), zoom toward label center
            if (
                pos_in_label.x() < 0
                or pos_in_label.y() < 0
                or pos_in_label.x() > old_w
                or pos_in_label.y() > old_h
            ):
                pos_in_label = QtCore.QPoint(old_w // 2, old_h // 2)
                anchor_vp = self._image_lbl.mapTo(vp, pos_in_label)

            rel_x = pos_in_label.x() / float(old_w)
            rel_y = pos_in_label.y() / float(old_h)

            self._zoom = new_zoom
            self._render()

            new_w = max(1, self._image_lbl.width())
            new_h = max(1, self._image_lbl.height())
            target = QtCore.QPoint(int(rel_x * new_w), int(rel_y * new_h))
            # Where that image point landed in the viewport after resize
            landed = self._image_lbl.mapTo(vp, target)
            dx = landed.x() - anchor_vp.x()
            dy = landed.y() - anchor_vp.y()
            hbar = self._scroll.horizontalScrollBar()
            vbar = self._scroll.verticalScrollBar()
            hbar.setValue(hbar.value() + dx)
            vbar.setValue(vbar.value() + dy)

        def _event_global_pos(self, event):
            try:
                return event.globalPosition().toPoint()
            except Exception:
                return event.globalPos()

        def _begin_drag(self, pos) -> None:
            self._dragging = True
            self._drag_origin = pos
            self._drag_scroll = (
                self._scroll.horizontalScrollBar().value(),
                self._scroll.verticalScrollBar().value(),
            )
            self._image_lbl.setCursor(QtCore.Qt.ClosedHandCursor)
            self._scroll.viewport().setCursor(QtCore.Qt.ClosedHandCursor)
            try:
                self._scroll.viewport().grabMouse()
            except Exception:
                pass

        def _update_drag(self, pos) -> None:
            if not self._dragging or self._drag_origin is None or self._drag_scroll is None:
                return
            dx = pos.x() - self._drag_origin.x()
            dy = pos.y() - self._drag_origin.y()
            h0, v0 = self._drag_scroll
            self._scroll.horizontalScrollBar().setValue(h0 - dx)
            self._scroll.verticalScrollBar().setValue(v0 - dy)

        def _end_drag(self) -> None:
            if not self._dragging:
                return
            self._dragging = False
            self._drag_origin = None
            self._drag_scroll = None
            try:
                self._scroll.viewport().releaseMouse()
            except Exception:
                pass
            self._image_lbl.setCursor(QtCore.Qt.OpenHandCursor)
            self._scroll.viewport().setCursor(QtCore.Qt.ArrowCursor)

        def eventFilter(self, obj, event):
            et = event.type()
            if et == QtCore.QEvent.Wheel and obj in (
                self._image_lbl,
                self._scroll.viewport(),
            ):
                delta = event.angleDelta().y()
                if delta != 0:
                    anchor = self._scroll.viewport().mapFromGlobal(
                        self._event_global_pos(event)
                    )
                    self._nudge_zoom(
                        1.12 if delta > 0 else 0.89,
                        anchor_vp=anchor,
                    )
                    return True
            if et == QtCore.QEvent.MouseButtonDblClick and obj in (
                self._image_lbl,
                self._scroll.viewport(),
            ):
                self._fit_to_view()
                return True
            if et == QtCore.QEvent.MouseButtonPress and obj in (
                self._image_lbl,
                self._scroll.viewport(),
            ):
                if event.button() == QtCore.Qt.LeftButton:
                    pos = self._scroll.viewport().mapFromGlobal(
                        self._event_global_pos(event)
                    )
                    self._begin_drag(pos)
                    return True
            if et == QtCore.QEvent.MouseMove and self._dragging:
                pos = self._scroll.viewport().mapFromGlobal(
                    self._event_global_pos(event)
                )
                self._update_drag(pos)
                return True
            if et == QtCore.QEvent.MouseButtonRelease and self._dragging:
                if event.button() == QtCore.Qt.LeftButton:
                    self._end_drag()
                    return True
            if et == QtCore.QEvent.Resize and obj == self._scroll.viewport():
                if self._fit:
                    QtCore.QTimer.singleShot(0, self._render)
            return super().eventFilter(obj, event)

        def keyPressEvent(self, event):
            key = event.key()
            if key in (QtCore.Qt.Key_Escape, QtCore.Qt.Key_Q):
                self.close()
                return
            if key in (QtCore.Qt.Key_Left, QtCore.Qt.Key_A):
                self._nav(-1)
                return
            if key in (QtCore.Qt.Key_Right, QtCore.Qt.Key_D):
                self._nav(1)
                return
            if key in (QtCore.Qt.Key_Plus, QtCore.Qt.Key_Equal):
                self._nudge_zoom(1.15)
                return
            if key in (QtCore.Qt.Key_Minus, QtCore.Qt.Key_Underscore):
                self._nudge_zoom(0.85)
                return
            if key == QtCore.Qt.Key_0:
                self._fit_to_view()
                return
            super().keyPressEvent(event)

        def resizeEvent(self, event):
            super().resizeEvent(event)
            if self._fit:
                self._render()

        def closeEvent(self, event):
            global _active_viewer
            if _active_viewer is self:
                _active_viewer = None
            super().closeEvent(event)

    # Replace previous viewer so only one floats around
    if _active_viewer is not None:
        try:
            _active_viewer.close()
        except Exception:
            pass

    dlg = ImageViewerDialog(gallery, idx, parent)
    _active_viewer = dlg
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    return dlg


def make_clickable_thumb(
    attachment: ImageAttachment,
    *,
    edge: int = 88,
    fixed_w: Optional[int] = None,
    fixed_h: Optional[int] = None,
    parent=None,
    gallery: Optional[Sequence[_ImageSource]] = None,
    index: int = 0,
    tooltip: str = "",
    stylesheet: str = "",
):
    """
    Build a QLabel thumbnail that opens the image viewer on left-click.
    """
    from maya_agent.ui.image_attach import pixmap_from_attachment

    QtCore, _QtGui, QtWidgets, _ = import_qt()
    label = QtWidgets.QLabel(parent)
    fw = fixed_w if fixed_w is not None else edge
    fh = fixed_h if fixed_h is not None else edge
    label.setFixedSize(fw, fh)
    label.setAlignment(QtCore.Qt.AlignCenter)
    label.setCursor(QtCore.Qt.PointingHandCursor)
    label.setStyleSheet(
        stylesheet
        or (
            "QLabel { background:#1a1b20; border:1px solid #4a5d78;"
            " border-radius:8px; }"
        )
    )
    pix = pixmap_from_attachment(attachment, edge=edge)
    if pix is not None and not pix.isNull():
        label.setPixmap(pix)
    else:
        label.setText("图片")
    tip = tooltip or attachment.name or attachment.mime or "图片"
    if "单击查看" not in tip:
        tip = f"{tip}\n单击查看大图"
    label.setToolTip(tip)

    gallery_list = list(gallery) if gallery is not None else [attachment]
    start = int(index or 0)

    def _on_click(event, att=attachment, gal=gallery_list, i=start, lbl=label):
        if event.button() == QtCore.Qt.LeftButton:
            show_image_viewer(gal, index=i, parent=lbl.window())
        event.accept()

    label.mousePressEvent = _on_click  # type: ignore[method-assign]
    return label


def open_external_url(url: Any) -> bool:
    """Open http(s) / file URL with the OS default handler."""
    QtCore, QtGui, _QtWidgets, _ = import_qt()
    if url is None:
        return False
    if isinstance(url, str):
        qurl = QtCore.QUrl(url)
    else:
        qurl = url
    if not isinstance(qurl, QtCore.QUrl):
        qurl = QtCore.QUrl(str(url))
    if not qurl.isValid():
        return False
    scheme = (qurl.scheme() or "").lower()
    if scheme not in ("http", "https", "file", "mailto"):
        return False
    return bool(QtGui.QDesktopServices.openUrl(qurl))
