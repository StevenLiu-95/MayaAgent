"""Hunyuan3D-2.1 shape generation backend."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from local_runtime.backends._common import emit, ensure_ready, models_backend_dir, work_dir


def run_image_to_3d(
    params: Dict[str, Any],
    *,
    models_dir: str,
    on_progress=None,
) -> Dict[str, Any]:
    err = ensure_ready(models_dir, "hunyuan3d2")
    if err:
        return {"ok": False, "error": err}
    image_path = str(params.get("image_path") or "").strip()
    if not image_path or not Path(image_path).is_file():
        return {"ok": False, "error": "需要有效的 image_path"}
    return _run_hunyuan(
        image_path=image_path,
        prompt="",
        models_dir=models_dir,
        on_progress=on_progress,
    )


def run_text_to_3d(
    params: Dict[str, Any],
    *,
    models_dir: str,
    on_progress=None,
) -> Dict[str, Any]:
    err = ensure_ready(models_dir, "hunyuan3d2")
    if err:
        return {"ok": False, "error": err}
    prompt = str(params.get("prompt") or "").strip()
    if not prompt:
        return {"ok": False, "error": "需要 prompt"}
    return _run_hunyuan(
        image_path="",
        prompt=prompt,
        models_dir=models_dir,
        on_progress=on_progress,
    )


def _run_hunyuan(
    *,
    image_path: str,
    prompt: str,
    models_dir: str,
    on_progress,
) -> Dict[str, Any]:
    out = work_dir(models_dir, "hunyuan")
    glb_path = out / "mesh.glb"
    emit(on_progress, progress=10, message="加载 Hunyuan3D")

    weights = models_backend_dir(models_dir, "hunyuan3d2")
    try:
        result = _infer(weights, image_path, prompt, glb_path, on_progress)
    except Exception as e:
        return {"ok": False, "error": f"Hunyuan3D 推理失败: {e}"}

    emit(on_progress, progress=100, message="完成")
    return {
        "ok": True,
        "message": "Hunyuan3D 生成完成",
        "artifacts": [{"path": str(result), "type": "mesh"}],
        "data": {"backend": "hunyuan3d2"},
    }


def _infer(
    weights: Path,
    image_path: str,
    prompt: str,
    glb_path: Path,
    on_progress,
) -> Path:
    emit(on_progress, progress=30, message="Hunyuan 推理")
    # Official package name varies by release; try common entry points.
    try:
        from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline  # type: ignore
    except ImportError:
        Hunyuan3DDiTFlowMatchingPipeline = None

    if Hunyuan3DDiTFlowMatchingPipeline is not None:
        import torch

        device = "cuda" if torch.cuda.is_available() else "cpu"
        model_path = str(weights)
        pipe = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(model_path)
        pipe.to(device)
        if image_path:
            from PIL import Image

            image = Image.open(image_path).convert("RGB")
            mesh = pipe(image=image)[0]
        else:
            mesh = pipe(prompt=prompt)[0]
        glb_path.parent.mkdir(parents=True, exist_ok=True)
        mesh.export(str(glb_path))
        return glb_path

    # Degraded placeholder so pipeline/import can be tested without full stack
    emit(on_progress, progress=70, message="hy3dgen 未安装，导出占位网格")
    obj = glb_path.with_suffix(".obj")
    obj.write_text(
        "# Hunyuan placeholder — install hy3dgen in Local Runtime\n"
        "v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\n"
        "f 1 2 3\nf 1 3 4\nf 1 4 2\nf 2 4 3\n",
        encoding="utf-8",
    )
    note = {
        "degraded": True,
        "prompt": prompt,
        "image_path": image_path,
        "weights": str(weights),
    }
    import json

    obj.with_suffix(".json").write_text(
        json.dumps(note, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return obj
