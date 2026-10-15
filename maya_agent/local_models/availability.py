"""Availability checks — hide Agent tools until weights are downloaded."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from maya_agent.local_models.catalog import get_backend, list_backends
from maya_agent.utils.config import get_config
from maya_agent.utils.paths import default_models_root, models_root


def local_cfg() -> Dict[str, Any]:
    cfg = get_config()
    return {
        "enabled": bool(cfg.get("local.enabled", True)),
        "models_dir": str(cfg.get("local.models_dir") or "").strip(),
        "runtime_host": str(cfg.get("local.runtime_host") or "127.0.0.1"),
        "runtime_port": int(cfg.get("local.runtime_port") or 8770),
        "port_auto": bool(cfg.get("local.port_auto", True)),
        "auto_start": bool(cfg.get("local.auto_start", False)),
        "wait_timeout": float(cfg.get("local.wait_timeout") or 1200),
        "poll_interval": float(cfg.get("local.poll_interval") or 2),
    }


def local_enabled() -> bool:
    return bool(local_cfg()["enabled"])


def backend_dir(backend_id: str) -> Path:
    return models_root() / (backend_id or "").strip()


def _marker_or_file_ready(root: Path, relpath: str) -> bool:
    path = root / relpath
    if path.is_file():
        return path.stat().st_size > 0
    if path.is_dir():
        return any(path.iterdir())
    # ".installed" markers under a directory
    if relpath.endswith("/.installed") or relpath.endswith("\\.installed"):
        parent = root / Path(relpath).parent
        marker = parent / ".installed"
        return marker.is_file()
    parent = path.parent
    marker = parent / ".installed"
    return marker.is_file()


def backend_ready(backend_id: str) -> bool:
    """True when all declared weight files / install markers exist under models_dir."""
    if not local_enabled():
        return False
    meta = get_backend(backend_id)
    if not meta:
        return False
    root = backend_dir(backend_id)
    if not root.is_dir():
        return False
    files = meta.get("files") or []
    if not files:
        return (root / ".installed").is_file()
    for entry in files:
        if not isinstance(entry, dict):
            continue
        rel = str(entry.get("relpath") or "").strip()
        if not rel:
            continue
        if not _marker_or_file_ready(root, rel):
            return False
    return True


def any_backend_ready(backend_ids: List[str]) -> bool:
    return any(backend_ready(b) for b in backend_ids if b)


def all_backends_ready(backend_ids: List[str]) -> bool:
    ids = [b for b in backend_ids if b]
    return bool(ids) and all(backend_ready(b) for b in ids)


def text_to_3d_ready() -> bool:
    if backend_ready("hunyuan3d2"):
        return True
    # TripoSR + SD-Turbo text→image→3D path
    return backend_ready("triposr") and backend_ready("sd_turbo")


def image_to_3d_ready() -> bool:
    return backend_ready("triposr") or backend_ready("hunyuan3d2")


def local_tools_gate(tool_name: str) -> bool:
    """
    Whether a local_* tool should be exposed to the LLM.
    Never auto-downloads; missing weights => False.
    """
    if not local_enabled():
        return False
    name = (tool_name or "").strip()
    if name == "local_runtime_status":
        return True
    if name in ("local_wait_task", "local_import_result"):
        # Utility tools: only when at least one generative backend is ready
        return any(
            backend_ready(b)
            for b in ("triposr", "hunyuan3d2", "unirig", "mdm", "atiss")
        )
    if name == "local_image_to_3d":
        return image_to_3d_ready()
    if name == "local_text_to_3d":
        return text_to_3d_ready()
    if name == "local_auto_rig":
        return backend_ready("unirig")
    if name == "local_text_to_motion":
        return backend_ready("mdm")
    if name == "local_scene_layout":
        return backend_ready("atiss")
    # Unknown local tool: hide by default
    if name.startswith("local_"):
        return False
    return True


def list_backend_status() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    root = models_root()
    for meta in list_backends(include_hidden=True):
        bid = str(meta.get("id") or "")
        ready = backend_ready(bid)
        rows.append(
            {
                "id": bid,
                "label": meta.get("label") or bid,
                "domain": meta.get("domain") or "",
                "description": meta.get("description") or "",
                "license": meta.get("license") or "",
                "vram_gb": meta.get("vram_gb"),
                "approx_size_gb": meta.get("approx_size_gb"),
                "ready": ready,
                "path": str(backend_dir(bid)),
                "models_root": str(root),
                "default_models_root": str(default_models_root()),
                "capabilities": list(meta.get("capabilities") or []),
                "hidden": bool(meta.get("hidden")),
            }
        )
    return rows


def filter_system_prompt_local(text: str) -> str:
    """Strip ## 本地模型 section when no generative local backend is ready."""
    has_any = any(
        backend_ready(b)
        for b in ("triposr", "hunyuan3d2", "unirig", "mdm", "atiss")
    )
    if has_any and local_enabled():
        return text
    lines = text.splitlines(keepends=True)
    out: List[str] = []
    skipping = False
    for line in lines:
        stripped = line.lstrip()
        if not skipping and stripped.startswith("## 本地模型"):
            skipping = True
            continue
        if skipping:
            if stripped.startswith("## ") and not stripped.startswith("## 本地模型"):
                skipping = False
                out.append(line)
            continue
        out.append(line)
    return "".join(out)
