"""Shared helpers for backends."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

ProgressFn = Optional[Callable[[Dict[str, Any]], None]]


def models_backend_dir(models_dir: str, backend_id: str) -> Path:
    return Path(models_dir) / backend_id


def ensure_ready(models_dir: str, backend_id: str) -> Optional[str]:
    root = models_backend_dir(models_dir, backend_id)
    marker = root / ".installed"
    if marker.is_file():
        return None
    # Accept presence of any weight file
    if root.is_dir() and any(root.rglob("*")):
        return None
    return (
        f"后端 {backend_id} 权重未下载。请在 MayaAgent「模型 → 本地模型」中手动下载，"
        "Agent 不会自动下载。"
    )


def work_dir(models_dir: str, prefix: str = "job") -> Path:
    base = Path(models_dir) / "_jobs" / f"{prefix}_{uuid.uuid4().hex[:10]}"
    base.mkdir(parents=True, exist_ok=True)
    return base


def emit(on_progress: ProgressFn, **payload: Any) -> None:
    if on_progress:
        try:
            on_progress(dict(payload))
        except Exception:
            pass


def run_python_script(
    script: str,
    args: List[str],
    *,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    timeout: float = 3600,
) -> subprocess.CompletedProcess:
    cmd = [sys.executable, script, *args]
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=full_env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
