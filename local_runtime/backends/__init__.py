"""Inference backend adapters."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from local_runtime.backends import atiss as atiss_mod
from local_runtime.backends import hunyuan3d2 as hunyuan_mod
from local_runtime.backends import mdm as mdm_mod
from local_runtime.backends import triposr as triposr_mod
from local_runtime.backends import unirig as unirig_mod

ProgressFn = Optional[Callable[[Dict[str, Any]], None]]

_HANDLERS = {
    "image_to_3d": None,  # resolved by backend param
    "text_to_3d": None,
    "auto_rig": unirig_mod.run,
    "text_to_motion": mdm_mod.run,
    "scene_layout": atiss_mod.run,
    "echo": None,
}


def run_kind(
    kind: str,
    params: Dict[str, Any],
    *,
    models_dir: str,
    on_progress: ProgressFn = None,
) -> Dict[str, Any]:
    kind = (kind or "").strip()
    params = dict(params or {})
    backend = str(params.get("backend") or "").strip()

    if kind == "echo":
        if on_progress:
            on_progress({"progress": 50, "message": "echo"})
        return {
            "ok": True,
            "message": "echo ok",
            "data": {"echo": params, "models_dir": models_dir},
            "artifacts": [],
        }

    if kind == "image_to_3d":
        if backend == "hunyuan3d2" or (not backend and _prefer_hunyuan(models_dir)):
            return hunyuan_mod.run_image_to_3d(
                params, models_dir=models_dir, on_progress=on_progress
            )
        return triposr_mod.run_image_to_3d(
            params, models_dir=models_dir, on_progress=on_progress
        )

    if kind == "text_to_3d":
        if backend == "triposr" or (
            backend != "hunyuan3d2" and not _backend_ready(models_dir, "hunyuan3d2")
        ):
            return triposr_mod.run_text_to_3d(
                params, models_dir=models_dir, on_progress=on_progress
            )
        return hunyuan_mod.run_text_to_3d(
            params, models_dir=models_dir, on_progress=on_progress
        )

    handler = _HANDLERS.get(kind)
    if handler is None:
        return {"ok": False, "error": f"未知任务类型: {kind}"}
    return handler(params, models_dir=models_dir, on_progress=on_progress)


def _backend_ready(models_dir: str, backend_id: str) -> bool:
    from pathlib import Path

    root = Path(models_dir) / backend_id
    return (root / ".installed").is_file() or root.is_dir() and any(root.iterdir())


def _prefer_hunyuan(models_dir: str) -> bool:
    return _backend_ready(models_dir, "hunyuan3d2") and not _backend_ready(
        models_dir, "triposr"
    )
