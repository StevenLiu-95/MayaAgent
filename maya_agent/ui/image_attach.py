"""UI helpers for attaching images — re-exports shared codec + Qt widgets glue."""

from __future__ import annotations

from maya_agent.llm.image_codec import (
    MAX_BYTES,
    MAX_EDGE,
    MAX_IMAGES,
    attachment_from_path,
    attachments_from_clipboard,
    is_image_path,
    pixmap_from_attachment,
    qimage_to_attachment,
)

__all__ = [
    "MAX_BYTES",
    "MAX_EDGE",
    "MAX_IMAGES",
    "attachment_from_path",
    "attachments_from_clipboard",
    "is_image_path",
    "pixmap_from_attachment",
    "qimage_to_attachment",
]
