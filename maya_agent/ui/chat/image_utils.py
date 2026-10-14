"""Shared helpers for chat image attachments."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def image_b64(img: Any) -> str:
    if isinstance(img, dict):
        return str(img.get("data_b64") or "")
    return str(getattr(img, "data_b64", "") or "")


def image_dicts(images: Optional[List[Any]]) -> List[Dict[str, Any]]:
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
