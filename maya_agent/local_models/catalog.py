"""Whitelist catalog for local inference backends."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from maya_agent.utils.paths import project_root

_CATALOG_CACHE: Optional[Dict[str, Any]] = None


def catalog_path() -> Path:
    return project_root() / "local_runtime" / "catalog.json"


def load_catalog(*, force: bool = False) -> Dict[str, Any]:
    global _CATALOG_CACHE
    if _CATALOG_CACHE is not None and not force:
        return _CATALOG_CACHE
    path = catalog_path()
    if not path.is_file():
        _CATALOG_CACHE = {"version": 1, "backends": []}
        return _CATALOG_CACHE
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {"version": 1, "backends": []}
        data.setdefault("backends", [])
        _CATALOG_CACHE = data
    except (json.JSONDecodeError, OSError):
        _CATALOG_CACHE = {"version": 1, "backends": []}
    return _CATALOG_CACHE


def list_backends(*, include_hidden: bool = True) -> List[Dict[str, Any]]:
    cat = load_catalog()
    out: List[Dict[str, Any]] = []
    for item in cat.get("backends") or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        if not include_hidden and item.get("hidden"):
            continue
        out.append(dict(item))
    return out


def get_backend(backend_id: str) -> Optional[Dict[str, Any]]:
    bid = (backend_id or "").strip()
    if not bid:
        return None
    for item in list_backends(include_hidden=True):
        if item.get("id") == bid:
            return item
    return None
