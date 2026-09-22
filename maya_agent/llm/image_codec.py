"""Encode images to ImageAttachment (shared by UI attach + viewport tools)."""

from __future__ import annotations

import base64
from typing import List

from maya_agent.llm.base import ImageAttachment

MAX_IMAGES = 4
MAX_EDGE = 1568
MAX_BYTES = 1_400_000
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")


def qimage_to_attachment(image, name: str = "") -> ImageAttachment:
    """Scale and encode a QImage as JPEG (or PNG when it has alpha)."""
    from maya_agent.utils.maya_compat import import_qt

    QtCore, QtGui, _QtWidgets, _name = import_qt()
    if image is None or image.isNull():
        raise ValueError("无法读取图片")

    image = image.convertToFormat(QtGui.QImage.Format_ARGB32)
    edge = max(image.width(), image.height())
    if edge > MAX_EDGE:
        image = image.scaled(
            MAX_EDGE,
            MAX_EDGE,
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation,
        )

    use_png = bool(image.hasAlphaChannel())
    raw, mime = _encode(QtCore, image, png=use_png, quality=82)
    while len(raw) > MAX_BYTES and max(image.width(), image.height()) > 480:
        image = image.scaled(
            max(image.width() * 3 // 4, 1),
            max(image.height() * 3 // 4, 1),
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation,
        )
        raw, mime = _encode(QtCore, image, png=False, quality=75)
    if not raw:
        raise ValueError("图片编码失败")
    return ImageAttachment(
        mime=mime,
        data_b64=base64.b64encode(raw).decode("ascii"),
        name=name or "",
    )


def attachment_from_path(path: str) -> ImageAttachment:
    from maya_agent.utils.maya_compat import import_qt

    _QtCore, QtGui, _QtWidgets, _name = import_qt()
    image = QtGui.QImage(path)
    if image.isNull():
        raise ValueError(f"无法打开图片: {path}")
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    return qimage_to_attachment(image, name=name)


def attachment_from_raw_file(path: str) -> ImageAttachment:
    """
    Encode an on-disk image. Prefer Qt recompression; fall back to raw bytes
    when Qt is unavailable (e.g. unit tests outside Maya).
    """
    try:
        return attachment_from_path(path)
    except Exception:
        pass
    low = path.lower()
    if low.endswith((".jpg", ".jpeg")):
        mime = "image/jpeg"
    elif low.endswith(".png"):
        mime = "image/png"
    elif low.endswith(".webp"):
        mime = "image/webp"
    else:
        mime = "image/jpeg"
    with open(path, "rb") as f:
        raw = f.read()
    if not raw:
        raise ValueError(f"空图像文件: {path}")
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    return ImageAttachment(
        mime=mime,
        data_b64=base64.b64encode(raw).decode("ascii"),
        name=name,
    )


def is_image_path(path: str) -> bool:
    low = (path or "").lower()
    return low.endswith(_IMAGE_SUFFIXES)


def attachments_from_clipboard(clipboard) -> List[ImageAttachment]:
    """Return images from the clipboard. Empty when the clipboard has no image."""
    mime = clipboard.mimeData()
    if mime is None:
        return []
    found: List[ImageAttachment] = []
    if mime.hasImage():
        image = clipboard.image()
        if image is not None and not image.isNull():
            found.append(qimage_to_attachment(image, name="clipboard.png"))
            return found
    if mime.hasUrls():
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            if not is_image_path(path):
                continue
            found.append(attachment_from_path(path))
            if len(found) >= MAX_IMAGES:
                break
    return found


def pixmap_from_attachment(attachment: ImageAttachment, edge: int = 72):
    """Decode a thumbnail pixmap, or None if Qt cannot read the bytes."""
    from maya_agent.utils.maya_compat import import_qt

    QtCore, QtGui, _QtWidgets, _name = import_qt()
    try:
        raw = base64.b64decode(attachment.data_b64)
    except Exception:
        return None
    image = QtGui.QImage()
    if not image.loadFromData(raw):
        return None
    image = image.scaled(
        edge,
        edge,
        QtCore.Qt.KeepAspectRatio,
        QtCore.Qt.SmoothTransformation,
    )
    return QtGui.QPixmap.fromImage(image)


def _encode(QtCore, image, png: bool, quality: int):
    buf = QtCore.QBuffer()
    buf.open(QtCore.QIODevice.WriteOnly)
    if png:
        ok = image.save(buf, "PNG")
        mime = "image/png"
    else:
        ok = image.save(buf, "JPEG", quality)
        mime = "image/jpeg"
    if not ok:
        return b"", mime
    data = buf.data()
    if isinstance(data, (bytes, bytearray)):
        raw = bytes(data)
    elif hasattr(data, "data"):
        raw = data.data()
        raw = bytes(raw) if not isinstance(raw, (bytes, bytearray)) else bytes(raw)
    else:
        raw = bytes(data)
    return raw, mime
