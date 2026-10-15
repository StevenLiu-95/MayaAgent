"""ATISS indoor scene layout backend."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from local_runtime.backends._common import emit, ensure_ready, models_backend_dir, work_dir


_DEFAULT_FURNITURE = [
    ("sofa", 2.0, 0.9, 0.9),
    ("coffee_table", 1.0, 0.4, 0.6),
    ("tv_stand", 1.4, 0.5, 0.4),
    ("floor_lamp", 0.3, 1.6, 0.3),
    ("plant", 0.4, 0.8, 0.4),
]


def run(
    params: Dict[str, Any],
    *,
    models_dir: str,
    on_progress=None,
) -> Dict[str, Any]:
    err = ensure_ready(models_dir, "atiss")
    if err:
        return {"ok": False, "error": err}

    prompt = str(params.get("prompt") or params.get("description") or "").strip()
    room = str(params.get("room_type") or "livingroom").strip() or "livingroom"
    width = float(params.get("width") or 6.0)
    depth = float(params.get("depth") or 5.0)

    out = work_dir(models_dir, "atiss")
    layout_path = out / "layout.json"
    emit(on_progress, progress=20, message="ATISS 布局")

    try:
        layout = _infer_layout(
            prompt, room, width, depth, models_dir, on_progress
        )
    except Exception as e:
        return {"ok": False, "error": f"ATISS 失败: {e}"}

    layout_path.write_text(
        json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    emit(on_progress, progress=100, message="完成")
    return {
        "ok": True,
        "message": f"场景布局完成（{len(layout.get('objects') or [])} 个物体）",
        "artifacts": [{"path": str(layout_path), "type": "layout_json"}],
        "data": layout,
    }


def _infer_layout(
    prompt: str,
    room: str,
    width: float,
    depth: float,
    models_dir: str,
    on_progress,
) -> Dict[str, Any]:
    weights = models_backend_dir(models_dir, "atiss")
    emit(on_progress, progress=40, message="采样布局")

    try:
        import atiss  # type: ignore  # noqa: F401

        has = True
    except ImportError:
        has = False

    if has:
        raise RuntimeError("atiss 包已安装但 API 适配待完善，请升级 Runtime")

    # Heuristic layout MVP driven by keywords in the prompt
    emit(on_progress, progress=70, message="生成摆放清单（启发式 MVP）")
    objects = _heuristic_objects(prompt, width, depth)
    return {
        "degraded": True,
        "room_type": room,
        "width": width,
        "depth": depth,
        "prompt": prompt,
        "weights": str(weights),
        "note": "Install ATISS for learned indoor layouts. Current result is heuristic.",
        "objects": objects,
    }


def _heuristic_objects(prompt: str, width: float, depth: float) -> List[Dict[str, Any]]:
    text = prompt.lower()
    picked = []
    mapping = {
        "sofa": ("沙发", "sofa", "couch"),
        "coffee_table": ("茶几", "table", "coffee"),
        "tv_stand": ("电视", "tv", "television"),
        "floor_lamp": ("灯", "lamp"),
        "plant": ("植物", "plant", "绿植"),
        "bed": ("床", "bed"),
        "desk": ("桌", "desk", "书桌"),
        "chair": ("椅", "chair"),
    }
    dims = {name: (w, h, d) for name, w, h, d in _DEFAULT_FURNITURE}
    dims.update(
        {
            "bed": (2.0, 0.5, 1.6),
            "desk": (1.2, 0.75, 0.6),
            "chair": (0.5, 0.9, 0.5),
        }
    )

    for name, keys in mapping.items():
        if any(k in text or k in prompt for k in keys):
            picked.append(name)
    if not picked:
        picked = [x[0] for x in _DEFAULT_FURNITURE[:4]]

    objects: List[Dict[str, Any]] = []
    n = len(picked)
    for i, name in enumerate(picked):
        w, h, d = dims.get(name, (0.6, 0.6, 0.6))
        # Simple grid along room
        col = i % max(1, int(width // 1.5) or 1)
        row = i // max(1, int(width // 1.5) or 1)
        x = -width / 2 + 1.0 + col * 1.5
        z = -depth / 2 + 1.0 + row * 1.5
        objects.append(
            {
                "id": f"{name}_{i}",
                "class": name,
                "translate": [round(x, 3), round(h / 2, 3), round(z, 3)],
                "rotate_y": 0.0,
                "size": [w, h, d],
                "placeholder": True,
            }
        )
    # Ensure unique-ish spacing if overflow
    if n == 1:
        objects[0]["translate"] = [0.0, objects[0]["size"][1] / 2, 0.0]
    return objects
