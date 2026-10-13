"""MCP discovery file — port / token for IDE MCP clients."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from maya_agent.utils.paths import user_config_dir

BRIDGE_FILENAME = "bridge.json"


def bridge_discovery_path() -> Path:
    return user_config_dir() / BRIDGE_FILENAME


def write_discovery(
    *,
    host: str,
    port: int,
    token: str,
    pid: Optional[int] = None,
    base_url: Optional[str] = None,
) -> Path:
    path = bridge_discovery_path()
    payload: Dict[str, Any] = {
        "host": host,
        "port": int(port),
        "token": token,
        "pid": int(pid if pid is not None else os.getpid()),
        "base_url": base_url or f"http://{host}:{int(port)}",
        "api_prefix": "/v1",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp.replace(path)
    return path


def read_discovery() -> Optional[Dict[str, Any]]:
    path = bridge_discovery_path()
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        return data
    except (json.JSONDecodeError, OSError):
        return None


def clear_discovery(*, only_if_pid: Optional[int] = None) -> bool:
    """Remove discovery file. If only_if_pid is set, only clear when pid matches."""
    path = bridge_discovery_path()
    if not path.is_file():
        return False
    if only_if_pid is not None:
        data = read_discovery() or {}
        try:
            if int(data.get("pid") or 0) != int(only_if_pid):
                return False
        except (TypeError, ValueError):
            return False
    try:
        path.unlink()
        return True
    except OSError:
        return False


def discovery_base_url(data: Optional[Dict[str, Any]] = None) -> str:
    data = data if data is not None else read_discovery()
    if not data:
        return ""
    url = str(data.get("base_url") or "").strip()
    if url:
        return url.rstrip("/")
    host = str(data.get("host") or "127.0.0.1").strip() or "127.0.0.1"
    port = int(data.get("port") or 0)
    if not port:
        return ""
    return f"http://{host}:{port}"
