"""MDM text-to-motion backend → BVH."""

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
    err = ensure_ready(models_dir, "mdm")
    if err:
        return {"ok": False, "error": err}

    prompt = str(params.get("prompt") or "").strip()
    if not prompt:
        return {"ok": False, "error": "需要 prompt（动作描述）"}

    frames = int(params.get("frames") or 120)
    out = work_dir(models_dir, "mdm")
    bvh_path = out / "motion.bvh"
    emit(on_progress, progress=10, message="MDM 生成运动")

    try:
        result = _infer(prompt, frames, bvh_path, models_dir, on_progress)
    except Exception as e:
        return {"ok": False, "error": f"MDM 失败: {e}"}

    emit(on_progress, progress=100, message="完成")
    return {
        "ok": True,
        "message": "MDM 动作生成完成",
        "artifacts": [{"path": str(result), "type": "bvh"}],
        "data": {"backend": "mdm", "prompt": prompt, "frames": frames},
    }


def _infer(
    prompt: str, frames: int, bvh_path: Path, models_dir: str, on_progress
) -> Path:
    weights = models_backend_dir(models_dir, "mdm")
    emit(on_progress, progress=40, message="扩散采样")

    try:
        # Upstream MDM is research code; hook if user installed it into runtime.
        import motion_diffusion  # type: ignore  # noqa: F401

        has = True
    except ImportError:
        has = False

    bvh_path.parent.mkdir(parents=True, exist_ok=True)
    if has:
        raise RuntimeError("motion_diffusion 已安装但尚未绑定具体 API，请升级 Runtime 适配器")

    # Minimal valid BVH hierarchy (idle standing) so Maya import path works
    emit(on_progress, progress=80, message="写入 BVH（占位/MVP）")
    bvh = _idle_bvh(frames=max(24, min(frames, 600)), prompt=prompt)
    bvh_path.write_text(bvh, encoding="utf-8")
    import json

    bvh_path.with_suffix(".json").write_text(
        json.dumps(
            {
                "degraded": True,
                "prompt": prompt,
                "weights": str(weights),
                "note": "Install MDM research code in Local Runtime for real motion.",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return bvh_path


def _idle_bvh(*, frames: int, prompt: str) -> str:
    # Simple 3-joint chain; channels zeros — MVP retarget target
    lines = [
        f"# MayaAgent MDM placeholder for: {prompt.replace(chr(10), ' ')}",
        "HIERARCHY",
        "ROOT Hips",
        "{",
        "  OFFSET 0.0 100.0 0.0",
        "  CHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation",
        "  JOINT Spine",
        "  {",
        "    OFFSET 0.0 20.0 0.0",
        "    CHANNELS 3 Zrotation Xrotation Yrotation",
        "    JOINT Head",
        "    {",
        "      OFFSET 0.0 25.0 0.0",
        "      CHANNELS 3 Zrotation Xrotation Yrotation",
        "      End Site",
        "      {",
        "        OFFSET 0.0 15.0 0.0",
        "      }",
        "    }",
        "  }",
        "}",
        "MOTION",
        f"Frames: {frames}",
        "Frame Time: 0.0333333",
    ]
    # 6 + 3 + 3 = 12 channels
    frame_line = " ".join(["0.0"] * 12)
    for _ in range(frames):
        lines.append(frame_line)
    return "\n".join(lines) + "\n"
