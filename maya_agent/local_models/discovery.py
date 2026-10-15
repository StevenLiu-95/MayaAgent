"""Local Runtime discovery file (AppData/MayaAgent/local_runtime.json)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from maya_agent.utils.paths import user_config_dir

FILENAME = "local_runtime.json"


def discovery_path() -> Path:
    return user_config_dir() / FILENAME


def write_discovery(payload: Dict[str, Any]) -> Path:
    path = discovery_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = dict(payload)
    data.setdefault("api_prefix", "/v1")
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)
    return path


def read_discovery() -> Optional[Dict[str, Any]]:
    path = discovery_path()
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def clear_discovery(*, only_if_pid: Optional[int] = None) -> bool:
    path = discovery_path()
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


def is_runtime_installed() -> bool:
    data = read_discovery() or {}
    py = str(data.get("python_exe") or data.get("python_home") or "").strip()
    if py and Path(py).exists():
        return True
    # Fallback: install root marker
    try:
        from maya_agent.utils.paths import local_runtime_install_root

        root = local_runtime_install_root()
        return (root / "python" / "python.exe").is_file() or (
            root / "venv" / "Scripts" / "python.exe"
        ).is_file() or (root / "venv" / "bin" / "python").is_file()
    except Exception:
        return False
