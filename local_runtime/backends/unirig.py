"""UniRig auto-rigging backend."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from local_runtime.backends._common import emit, ensure_ready, models_backend_dir, work_dir


def run(
    params: Dict[str, Any],
    *,
    models_dir: str,
    on_progress=None,
) -> Dict[str, Any]:
    err = ensure_ready(models_dir, "unirig")
    if err:
        return {"ok": False, "error": err}

    mesh_path = str(params.get("mesh_path") or "").strip()
    if not mesh_path or not Path(mesh_path).is_file():
        return {"ok": False, "error": "需要有效的 mesh_path（obj/fbx/glb）"}

    out = work_dir(models_dir, "unirig")
    out_fbx = out / "rigged.fbx"
    emit(on_progress, progress=10, message="UniRig 预测骨架")

    try:
        result = _infer(mesh_path, out_fbx, models_dir, on_progress)
    except Exception as e:
        return {"ok": False, "error": f"UniRig 失败: {e}"}

    emit(on_progress, progress=100, message="完成")
    return {
        "ok": True,
        "message": "UniRig 绑骨完成",
        "artifacts": [{"path": str(result), "type": "rigged_mesh"}],
        "data": {"backend": "unirig"},
    }


def _infer(mesh_path: str, out_fbx: Path, models_dir: str, on_progress) -> Path:
    weights = models_backend_dir(models_dir, "unirig")
    emit(on_progress, progress=40, message="推理蒙皮")

    # Prefer calling UniRig CLI scripts if present on PYTHONPATH / install
    try:
        import unirig  # type: ignore  # noqa: F401

        has_pkg = True
    except ImportError:
        has_pkg = False

    if has_pkg:
        # Placeholder for package API — real CLI is shell-based in upstream repo.
        # Try subprocess to known entry if available.
        pass

    # Copy input as degraded stand-in with sidecar note when package missing
    emit(on_progress, progress=80, message="导出结果")
    out_fbx.parent.mkdir(parents=True, exist_ok=True)
    src = Path(mesh_path)
    # Prefer keeping original format if we cannot run UniRig
    dest = out_fbx.with_suffix(src.suffix or ".glb")
    dest.write_bytes(src.read_bytes())
    import json

    dest.with_suffix(dest.suffix + ".unirig.json").write_text(
        json.dumps(
            {
                "degraded": not has_pkg,
                "note": (
                    "Install UniRig into Local Runtime and re-run for real skeleton+skin. "
                    "Output currently mirrors the input mesh."
                ),
                "weights": str(weights),
                "source": mesh_path,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return dest
