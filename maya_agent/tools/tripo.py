"""Tripo AI tools — generation, mesh edit, rig, download & import into Maya."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set

from maya_agent.core.tool_progress import report_tool_progress
from maya_agent.tools.registry import ToolResult, obj_schema, tool
from maya_agent.tools.tripo_client import (
    ANIMATION_PRESETS,
    ENDPOINT_PATHS,
    TripoClient,
    TripoError,
    download_dir,
    drop_none,
    pick_image_urls,
    pick_model_url,
    summarize_task,
    tripo_cfg,
)
from maya_agent.utils.logger import get_logger
from maya_agent.utils.maya_compat import run_on_main_thread

log = get_logger("maya_agent.tripo_tools")

_ENDPOINT_ENUM = sorted(ENDPOINT_PATHS.keys())

_ROT_ATTRS = ("rotateX", "rotateY", "rotateZ")
_TRANS_ATTRS = ("translateX", "translateY", "translateZ")
_DEFAULT_ROOT_SHORTS = frozenset(
    {"Root", "root", "Hips", "Hip", "hip", "Armature", "armature", "PELVIS", "Pelvis"}
)


def animation_attrs_for_mode(
    mode: str,
    joint_short: str,
    *,
    root_shorts: Optional[Sequence[str]] = None,
) -> List[str]:
    """
    Channels to copy for Tripo animation apply.

    Default ``rotations_only`` never copies limb translates (Hip t≈3.14 style
    constants from unit-scaled retarget FBX explode bind chains).
    """
    m = (mode or "rotations_only").strip()
    attrs = list(_ROT_ATTRS)
    roots: Set[str] = set(root_shorts) if root_shorts else set(_DEFAULT_ROOT_SHORTS)
    if m == "rotations_and_root_translate" and joint_short in roots:
        attrs.extend(_TRANS_ATTRS)
    return attrs


def short_joint_name(node: str) -> str:
    """``ns:Hip`` / ``|a|b|Hip`` → ``Hip``."""
    leaf = (node or "").split("|")[-1]
    if ":" in leaf:
        return leaf.rsplit(":", 1)[-1]
    return leaf


def _client() -> TripoClient:
    return TripoClient()


def _err(exc: Exception) -> ToolResult:
    if isinstance(exc, TripoError):
        data = summarize_task(exc.payload) if isinstance(exc.payload, dict) else exc.payload
        return ToolResult(ok=False, error=str(exc), data=data)
    log.exception("tripo tool failed")
    return ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}")


def _normalize_progress(value: Any) -> Optional[int]:
    """Map Tripo progress to 0–100 int for the UI progress bar."""
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    # Only treat open interval (0, 1) as a fraction — keep int 1 as 1%.
    if 0.0 < num < 1.0:
        num = num * 100.0
    return max(0, min(100, int(round(num))))


def _wait_progress(endpoint: str, task_id: str):
    def _on(info: Dict[str, Any]) -> None:
        status = str(info.get("status") or "")
        progress = _normalize_progress(info.get("progress"))
        pct = f" {progress}%" if progress is not None else ""
        report_tool_progress(
            kind=endpoint,
            task_id=task_id,
            status=status,
            progress=progress,
            message=f"Tripo {endpoint} {status}{pct}".strip(),
        )

    return _on


def _create_and_maybe_wait(
    endpoint: str,
    body: Dict[str, Any],
    *,
    wait: bool = False,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    client = _client()
    task_id = client.create(endpoint, drop_none(body))
    if not wait:
        return ToolResult(
            ok=True,
            data={"endpoint": endpoint, "task_id": task_id, "status": "CREATED"},
            message=(
                f"已创建 Tripo 任务 {endpoint}：{task_id}。"
                f"请调用 tripo_wait_task(task_id=...) 等待完成，"
                "再用 tripo_import_to_maya 或 tripo_download 获取结果。"
            ),
        )
    report_tool_progress(
        kind=endpoint,
        task_id=task_id,
        status="queued",
        progress=0,
        message=f"Tripo {endpoint} 已创建，等待中…",
    )
    task = client.wait(
        task_id,
        timeout=wait_timeout,
        on_progress=_wait_progress(endpoint, task_id),
        endpoint=endpoint,
    )
    return ToolResult(
        ok=True,
        data={"endpoint": endpoint, "task_id": task_id, "task": summarize_task(task)},
        message=f"Tripo 任务已完成：{task_id}",
    )


def _default_model(model: str = "") -> str:
    m = (model or "").strip()
    if m:
        return m
    return str(tripo_cfg().get("default_model") or "v3.1-20260211")


def _default_image_model(model: str = "") -> str:
    m = (model or "").strip()
    if m:
        return m
    return str(tripo_cfg().get("default_image_model") or "seedream_v4")


def _gen_common_body(
    *,
    model: str = "",
    texture: Optional[bool] = None,
    pbr: Optional[bool] = None,
    face_limit: Optional[int] = None,
    texture_quality: str = "",
    geometry_quality: str = "",
    auto_size: Optional[bool] = None,
    quad: Optional[bool] = None,
    smart_low_poly: Optional[bool] = None,
    generate_parts: Optional[bool] = None,
    model_seed: Optional[int] = None,
    texture_seed: Optional[int] = None,
    texture_version: str = "",
    delight: Optional[bool] = None,
    export_orientation: str = "",
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"model": _default_model(model)}
    if texture is not None:
        body["texture"] = bool(texture)
    if pbr is not None:
        body["pbr"] = bool(pbr)
    if face_limit is not None:
        body["face_limit"] = int(face_limit)
    if texture_quality:
        body["texture_quality"] = texture_quality
    if geometry_quality:
        body["geometry_quality"] = geometry_quality
    if auto_size is not None:
        body["auto_size"] = bool(auto_size)
    if quad is not None:
        body["quad"] = bool(quad)
    if smart_low_poly is not None:
        body["smart_low_poly"] = bool(smart_low_poly)
    if generate_parts is not None:
        body["generate_parts"] = bool(generate_parts)
    if model_seed is not None:
        body["model_seed"] = int(model_seed)
    if texture_seed is not None:
        body["texture_seed"] = int(texture_seed)
    if texture_version:
        body["texture_version"] = texture_version
    if delight is not None:
        body["delight"] = bool(delight)
    if export_orientation:
        body["export_orientation"] = export_orientation
    return body


_GEN_PARAMS = {
    "model": {
        "type": "string",
        "description": "几何模型版本，如 v3.1-20260211 / tripo-v3.1 / tripo-p1",
    },
    "texture": {"type": "boolean", "default": True},
    "pbr": {"type": "boolean", "default": True},
    "face_limit": {"type": "integer"},
    "texture_quality": {
        "type": "string",
        "enum": ["fast", "standard", "detailed", "extreme"],
    },
    "geometry_quality": {"type": "string", "enum": ["standard", "detailed"]},
    "auto_size": {"type": "boolean"},
    "quad": {"type": "boolean"},
    "smart_low_poly": {"type": "boolean"},
    "generate_parts": {"type": "boolean"},
    "model_seed": {"type": "integer"},
    "texture_seed": {"type": "integer"},
    "texture_version": {"type": "string"},
    "delight": {"type": "boolean"},
    "export_orientation": {
        "type": "string",
        "enum": ["+x", "-x", "+y", "-y"],
    },
    "wait": {"type": "boolean", "default": False},
    "wait_timeout": {"type": "number"},
}


# ---------------------------------------------------------------------------
# 3D Generation
# ---------------------------------------------------------------------------


@tool(
    name="tripo_text_to_model",
    description=(
        "Tripo 文生 3D。先查 tripo_balance；默认只返回 task_id，"
        "设 wait=true 则轮询至完成。完成后用 tripo_import_to_maya（优先 FBX）。"
    ),
    parameters=obj_schema(
        {
            "prompt": {"type": "string", "description": "最多约 1024 字符"},
            **_GEN_PARAMS,
        },
        required=["prompt"],
    ),
    category="tripo",
    main_thread=False,
)
def tripo_text_to_model(
    prompt: str,
    model: str = "",
    texture: Optional[bool] = None,
    pbr: Optional[bool] = None,
    face_limit: Optional[int] = None,
    texture_quality: str = "",
    geometry_quality: str = "",
    auto_size: Optional[bool] = None,
    quad: Optional[bool] = None,
    smart_low_poly: Optional[bool] = None,
    generate_parts: Optional[bool] = None,
    model_seed: Optional[int] = None,
    texture_seed: Optional[int] = None,
    texture_version: str = "",
    delight: Optional[bool] = None,
    export_orientation: str = "",
    wait: bool = False,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    try:
        if not (prompt or "").strip():
            return ToolResult(ok=False, error="需要 prompt")
        body = _gen_common_body(
            model=model,
            texture=texture,
            pbr=pbr,
            face_limit=face_limit,
            texture_quality=texture_quality,
            geometry_quality=geometry_quality,
            auto_size=auto_size,
            quad=quad,
            smart_low_poly=smart_low_poly,
            generate_parts=generate_parts,
            model_seed=model_seed,
            texture_seed=texture_seed,
            texture_version=texture_version,
            delight=delight,
            export_orientation=export_orientation,
        )
        body["prompt"] = prompt.strip()
        return _create_and_maybe_wait(
            "text-to-model", body, wait=wait, wait_timeout=wait_timeout
        )
    except Exception as e:
        return _err(e)


@tool(
    name="tripo_image_to_model",
    description=(
        "Tripo 图生 3D。可用 image_url / image_path / file_token / 上游图像 task_id，"
        "或 use_latest_chat_image=true。本地图会先 upload 得 file_token。"
    ),
    parameters=obj_schema(
        {
            "image_url": {"type": "string"},
            "image_path": {"type": "string"},
            "file_token": {"type": "string"},
            "input_task_id": {
                "type": "string",
                "description": "此前 text-to-image / image-to-image 任务 id",
            },
            "use_latest_chat_image": {
                "type": "boolean",
                "description": "使用对话中最近落盘的附图",
            },
            **_GEN_PARAMS,
            "texture_alignment": {
                "type": "string",
                "enum": ["original_image", "geometry"],
            },
        },
    ),
    category="tripo",
    main_thread=False,
)
def tripo_image_to_model(
    image_url: str = "",
    image_path: str = "",
    file_token: str = "",
    input_task_id: str = "",
    use_latest_chat_image: bool = False,
    model: str = "",
    texture: Optional[bool] = None,
    pbr: Optional[bool] = None,
    face_limit: Optional[int] = None,
    texture_quality: str = "",
    geometry_quality: str = "",
    auto_size: Optional[bool] = None,
    quad: Optional[bool] = None,
    smart_low_poly: Optional[bool] = None,
    generate_parts: Optional[bool] = None,
    model_seed: Optional[int] = None,
    texture_seed: Optional[int] = None,
    texture_version: str = "",
    delight: Optional[bool] = None,
    export_orientation: str = "",
    texture_alignment: str = "",
    wait: bool = False,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    try:
        client = _client()
        path = (image_path or "").strip()
        if use_latest_chat_image and not path and not image_url and not file_token and not input_task_id:
            from maya_agent.tools.fsutil import latest_chat_image_paths

            paths = latest_chat_image_paths(limit=1)
            if not paths:
                return ToolResult(ok=False, error="对话中没有可用附图")
            path = paths[0]
        inp = client.resolve_file_input(
            url=image_url,
            path=path,
            file_token=file_token,
            task_id=input_task_id,
        )
        body = _gen_common_body(
            model=model,
            texture=texture,
            pbr=pbr,
            face_limit=face_limit,
            texture_quality=texture_quality,
            geometry_quality=geometry_quality,
            auto_size=auto_size,
            quad=quad,
            smart_low_poly=smart_low_poly,
            generate_parts=generate_parts,
            model_seed=model_seed,
            texture_seed=texture_seed,
            texture_version=texture_version,
            delight=delight,
            export_orientation=export_orientation,
        )
        body["input"] = inp
        if texture_alignment:
            body["texture_alignment"] = texture_alignment
        return _create_and_maybe_wait(
            "image-to-model", body, wait=wait, wait_timeout=wait_timeout
        )
    except Exception as e:
        return _err(e)


@tool(
    name="tripo_multiview_to_model",
    description=(
        "Tripo 多视角图生 3D。提供 front/left/back/right 路径或 URL（正面必填，至少 2 张），"
        "或 multiview_task_id 复用 image-to-multiview / edit-multiview 输出。"
    ),
    parameters=obj_schema(
        {
            "front": {"type": "string", "description": "正面图路径或 URL"},
            "left": {"type": "string"},
            "back": {"type": "string"},
            "right": {"type": "string"},
            "multiview_task_id": {
                "type": "string",
                "description": "复用多视角图像任务",
            },
            "use_latest_chat_images": {
                "type": "boolean",
                "description": "用最近最多 4 张对话附图按 front/left/back/right 顺序",
            },
            **_GEN_PARAMS,
            "texture_alignment": {
                "type": "string",
                "enum": ["original_image", "geometry"],
            },
            "orientation": {
                "type": "string",
                "enum": ["default", "align_image"],
            },
        },
    ),
    category="tripo",
    main_thread=False,
)
def tripo_multiview_to_model(
    front: str = "",
    left: str = "",
    back: str = "",
    right: str = "",
    multiview_task_id: str = "",
    use_latest_chat_images: bool = False,
    model: str = "",
    texture: Optional[bool] = None,
    pbr: Optional[bool] = None,
    face_limit: Optional[int] = None,
    texture_quality: str = "",
    geometry_quality: str = "",
    auto_size: Optional[bool] = None,
    quad: Optional[bool] = None,
    smart_low_poly: Optional[bool] = None,
    generate_parts: Optional[bool] = None,
    model_seed: Optional[int] = None,
    texture_seed: Optional[int] = None,
    texture_version: str = "",
    delight: Optional[bool] = None,
    export_orientation: str = "",
    texture_alignment: str = "",
    orientation: str = "",
    wait: bool = False,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    try:
        client = _client()
        mv_tid = (multiview_task_id or "").strip()
        if mv_tid:
            inputs: Any = [{"task_id": mv_tid}]
        else:
            views = {
                "front": (front or "").strip(),
                "left": (left or "").strip(),
                "back": (back or "").strip(),
                "right": (right or "").strip(),
            }
            if use_latest_chat_images and not any(views.values()):
                from maya_agent.tools.fsutil import latest_chat_image_paths

                paths = latest_chat_image_paths(limit=4)
                keys = ["front", "left", "back", "right"]
                for i, p in enumerate(paths):
                    views[keys[i]] = p
            if not views["front"]:
                return ToolResult(ok=False, error="多视图生成需要正面图 front（或 multiview_task_id）")
            filled = [k for k, v in views.items() if v]
            if len(filled) < 2:
                return ToolResult(ok=False, error="至少需要 2 张视角图（含正面）")
            inputs = []
            for key, raw in views.items():
                if not raw:
                    continue
                if raw.startswith(("http://", "https://")):
                    val = raw
                elif raw.startswith(("file_", "task_")):
                    val = raw
                elif Path(raw).is_file():
                    val = client.upload_file(raw)
                else:
                    val = client.resolve_file_input(url=raw, path=raw)
                inputs.append({key: val})
        body = _gen_common_body(
            model=model,
            texture=texture,
            pbr=pbr,
            face_limit=face_limit,
            texture_quality=texture_quality,
            geometry_quality=geometry_quality,
            auto_size=auto_size,
            quad=quad,
            smart_low_poly=smart_low_poly,
            generate_parts=generate_parts,
            model_seed=model_seed,
            texture_seed=texture_seed,
            texture_version=texture_version,
            delight=delight,
            export_orientation=export_orientation,
        )
        body["inputs"] = inputs
        if texture_alignment:
            body["texture_alignment"] = texture_alignment
        if orientation:
            body["orientation"] = orientation
        return _create_and_maybe_wait(
            "multiview-to-model", body, wait=wait, wait_timeout=wait_timeout
        )
    except Exception as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Image generation
# ---------------------------------------------------------------------------


def _download_task_images(task: Dict[str, Any], task_id: str) -> List[str]:
    client = _client()
    urls = pick_image_urls(task)
    paths: List[str] = []
    out_dir = download_dir()
    for i, url in enumerate(urls):
        ext = "png"
        low = url.lower().split("?", 1)[0]
        for e in ("png", "jpg", "jpeg", "webp"):
            if low.endswith("." + e):
                ext = "jpg" if e == "jpeg" else e
                break
        dest = out_dir / f"tripo_{task_id}_{i}.{ext}"
        client.download(url, dest)
        paths.append(str(dest))
    return paths


@tool(
    name="tripo_text_to_image",
    description=(
        "Tripo 文生图。成功后可将图片下载到本地，再接 tripo_image_to_model。"
        "model 如 seedream_v4 / seedream_v5 / banana / chat_image_2。"
    ),
    parameters=obj_schema(
        {
            "prompt": {"type": "string"},
            "model": {"type": "string"},
            "size": {"type": "string", "description": "如 2K / 2048x2048"},
            "aspect_ratio": {"type": "string"},
            "output_format": {"type": "string", "enum": ["png", "jpeg"]},
            "quality": {"type": "string"},
            "background": {
                "type": "string",
                "enum": ["auto", "opaque", "transparent"],
            },
            "watermark": {"type": "boolean"},
            "template": {"type": "string"},
            "wait": {"type": "boolean", "default": True},
            "wait_timeout": {"type": "number"},
            "download": {
                "type": "boolean",
                "default": True,
                "description": "完成后是否下载图片到本地",
            },
        },
        required=["prompt"],
    ),
    category="tripo",
    main_thread=False,
)
def tripo_text_to_image(
    prompt: str,
    model: str = "",
    size: str = "",
    aspect_ratio: str = "",
    output_format: str = "",
    quality: str = "",
    background: str = "",
    watermark: Optional[bool] = None,
    template: str = "",
    wait: bool = True,
    wait_timeout: Optional[float] = None,
    download: bool = True,
) -> ToolResult:
    try:
        body: Dict[str, Any] = {
            "prompt": (prompt or "").strip(),
            "model": _default_image_model(model),
        }
        if not body["prompt"]:
            return ToolResult(ok=False, error="需要 prompt")
        if size:
            body["size"] = size
        if aspect_ratio:
            body["aspect_ratio"] = aspect_ratio
        if output_format:
            body["output_format"] = output_format
        if quality:
            body["quality"] = quality
        if background:
            body["background"] = background
        if watermark is not None:
            body["watermark"] = bool(watermark)
        if template:
            body["template"] = template
        result = _create_and_maybe_wait(
            "text-to-image", body, wait=wait, wait_timeout=wait_timeout
        )
        if result.ok and wait and download and isinstance(result.data, dict):
            task = (result.data.get("task") or {}) if isinstance(result.data.get("task"), dict) else {}
            # summarize_task nests output; re-fetch full task for URLs
            tid = str(result.data.get("task_id") or "")
            if tid:
                full = _client().get_task(tid)
                paths = _download_task_images(full, tid)
                result.data["local_images"] = paths
                if paths:
                    result.message = (result.message or "") + f"；已下载: {', '.join(paths)}"
        return result
    except Exception as e:
        return _err(e)


@tool(
    name="tripo_image_to_image",
    description="Tripo 图生图 / 风格转换。input 为参考图（url/path/file_token/task_id）。",
    parameters=obj_schema(
        {
            "prompt": {"type": "string"},
            "image_url": {"type": "string"},
            "image_path": {"type": "string"},
            "file_token": {"type": "string"},
            "input_task_id": {"type": "string"},
            "use_latest_chat_image": {"type": "boolean"},
            "model": {"type": "string"},
            "size": {"type": "string"},
            "output_format": {"type": "string", "enum": ["png", "jpeg"]},
            "wait": {"type": "boolean", "default": True},
            "wait_timeout": {"type": "number"},
            "download": {"type": "boolean", "default": True},
        },
    ),
    category="tripo",
    main_thread=False,
)
def tripo_image_to_image(
    prompt: str = "",
    image_url: str = "",
    image_path: str = "",
    file_token: str = "",
    input_task_id: str = "",
    use_latest_chat_image: bool = False,
    model: str = "",
    size: str = "",
    output_format: str = "",
    wait: bool = True,
    wait_timeout: Optional[float] = None,
    download: bool = True,
) -> ToolResult:
    try:
        client = _client()
        path = (image_path or "").strip()
        if use_latest_chat_image and not path and not image_url and not file_token and not input_task_id:
            from maya_agent.tools.fsutil import latest_chat_image_paths

            paths = latest_chat_image_paths(limit=1)
            if not paths:
                return ToolResult(ok=False, error="对话中没有可用附图")
            path = paths[0]
        inp = client.resolve_file_input(
            url=image_url, path=path, file_token=file_token, task_id=input_task_id
        )
        body: Dict[str, Any] = {
            "input": inp,
            "model": _default_image_model(model),
        }
        if prompt:
            body["prompt"] = prompt.strip()
        if size:
            body["size"] = size
        if output_format:
            body["output_format"] = output_format
        result = _create_and_maybe_wait(
            "image-to-image", body, wait=wait, wait_timeout=wait_timeout
        )
        if result.ok and wait and download and isinstance(result.data, dict):
            tid = str(result.data.get("task_id") or "")
            if tid:
                full = client.get_task(tid)
                paths = _download_task_images(full, tid)
                result.data["local_images"] = paths
        return result
    except Exception as e:
        return _err(e)


@tool(
    name="tripo_image_to_multiview",
    description="从单张图生成多视角图，可再接 tripo_multiview_to_model(multiview_task_id=...)。",
    parameters=obj_schema(
        {
            "image_url": {"type": "string"},
            "image_path": {"type": "string"},
            "file_token": {"type": "string"},
            "input_task_id": {"type": "string"},
            "use_latest_chat_image": {"type": "boolean"},
            "model": {"type": "string"},
            "wait": {"type": "boolean", "default": True},
            "wait_timeout": {"type": "number"},
            "download": {"type": "boolean", "default": True},
        },
    ),
    category="tripo",
    main_thread=False,
)
def tripo_image_to_multiview(
    image_url: str = "",
    image_path: str = "",
    file_token: str = "",
    input_task_id: str = "",
    use_latest_chat_image: bool = False,
    model: str = "",
    wait: bool = True,
    wait_timeout: Optional[float] = None,
    download: bool = True,
) -> ToolResult:
    try:
        client = _client()
        path = (image_path or "").strip()
        if use_latest_chat_image and not path and not image_url and not file_token and not input_task_id:
            from maya_agent.tools.fsutil import latest_chat_image_paths

            paths = latest_chat_image_paths(limit=1)
            if not paths:
                return ToolResult(ok=False, error="对话中没有可用附图")
            path = paths[0]
        inp = client.resolve_file_input(
            url=image_url, path=path, file_token=file_token, task_id=input_task_id
        )
        body: Dict[str, Any] = {"input": inp}
        if model:
            body["model"] = model
        result = _create_and_maybe_wait(
            "image-to-multiview", body, wait=wait, wait_timeout=wait_timeout
        )
        if result.ok and wait and download and isinstance(result.data, dict):
            tid = str(result.data.get("task_id") or "")
            if tid:
                full = client.get_task(tid)
                paths = _download_task_images(full, tid)
                result.data["local_images"] = paths
        return result
    except Exception as e:
        return _err(e)


@tool(
    name="tripo_edit_multiview",
    description="编辑多视角图像。input 为多视角任务 id 或图像源；可附 prompt。",
    parameters=obj_schema(
        {
            "input_task_id": {"type": "string", "description": "多视角任务 id"},
            "prompt": {"type": "string"},
            "image_url": {"type": "string"},
            "image_path": {"type": "string"},
            "file_token": {"type": "string"},
            "model": {"type": "string"},
            "wait": {"type": "boolean", "default": True},
            "wait_timeout": {"type": "number"},
            "download": {"type": "boolean", "default": True},
        },
    ),
    category="tripo",
    main_thread=False,
)
def tripo_edit_multiview(
    input_task_id: str = "",
    prompt: str = "",
    image_url: str = "",
    image_path: str = "",
    file_token: str = "",
    model: str = "",
    wait: bool = True,
    wait_timeout: Optional[float] = None,
    download: bool = True,
) -> ToolResult:
    try:
        client = _client()
        inp = client.resolve_file_input(
            url=image_url,
            path=image_path,
            file_token=file_token,
            task_id=input_task_id,
        )
        body: Dict[str, Any] = {"input": inp}
        if prompt:
            body["prompt"] = prompt.strip()
        if model:
            body["model"] = model
        result = _create_and_maybe_wait(
            "edit-multiview", body, wait=wait, wait_timeout=wait_timeout
        )
        if result.ok and wait and download and isinstance(result.data, dict):
            tid = str(result.data.get("task_id") or "")
            if tid:
                full = client.get_task(tid)
                paths = _download_task_images(full, tid)
                result.data["local_images"] = paths
        return result
    except Exception as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------


def _resolve_model_input(
    client: TripoClient,
    *,
    input_task_id: str = "",
    model_url: str = "",
    model_path: str = "",
    file_token: str = "",
) -> str:
    return client.resolve_file_input(
        url=model_url,
        path=model_path,
        file_token=file_token,
        task_id=input_task_id,
    )


@tool(
    name="tripo_texture",
    description=(
        "为已有模型重新贴图。input 为 3D 任务 id / file_token / URL / 本地路径。"
        "texture_prompt_text / style 图 / 单图 / 四视图引导互斥。"
    ),
    parameters=obj_schema(
        {
            "input_task_id": {"type": "string"},
            "model_url": {"type": "string"},
            "model_path": {"type": "string"},
            "file_token": {"type": "string"},
            "model": {"type": "string", "description": "贴图模型版本"},
            "texture_prompt_text": {"type": "string"},
            "style_image_url": {"type": "string"},
            "style_image_path": {"type": "string"},
            "ref_image_url": {"type": "string"},
            "ref_image_path": {"type": "string"},
            "pbr": {"type": "boolean", "default": True},
            "texture_quality": {
                "type": "string",
                "enum": ["fast", "standard", "detailed", "extreme"],
            },
            "texture_alignment": {
                "type": "string",
                "enum": ["original_image", "geometry"],
            },
            "texture_seed": {"type": "integer"},
            "delight": {"type": "boolean"},
            "bake": {"type": "boolean"},
            "wait": {"type": "boolean", "default": False},
            "wait_timeout": {"type": "number"},
        },
    ),
    category="tripo",
    main_thread=False,
)
def tripo_texture(
    input_task_id: str = "",
    model_url: str = "",
    model_path: str = "",
    file_token: str = "",
    model: str = "",
    texture_prompt_text: str = "",
    style_image_url: str = "",
    style_image_path: str = "",
    ref_image_url: str = "",
    ref_image_path: str = "",
    pbr: Optional[bool] = None,
    texture_quality: str = "",
    texture_alignment: str = "",
    texture_seed: Optional[int] = None,
    delight: Optional[bool] = None,
    bake: Optional[bool] = None,
    wait: bool = False,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    try:
        client = _client()
        inp = _resolve_model_input(
            client,
            input_task_id=input_task_id,
            model_url=model_url,
            model_path=model_path,
            file_token=file_token,
        )
        body: Dict[str, Any] = {"input": inp}
        if model:
            body["model"] = model
        if pbr is not None:
            body["pbr"] = bool(pbr)
        if texture_quality:
            body["texture_quality"] = texture_quality
        if texture_alignment:
            body["texture_alignment"] = texture_alignment
        if texture_seed is not None:
            body["texture_seed"] = int(texture_seed)
        if delight is not None:
            body["delight"] = bool(delight)
        if bake is not None:
            body["bake"] = bool(bake)
        tp: Dict[str, Any] = {}
        if texture_prompt_text:
            tp["text"] = texture_prompt_text.strip()
            if style_image_path or style_image_url:
                style = client.resolve_file_input(
                    url=style_image_url, path=style_image_path
                )
                if style.startswith(("http://", "https://")):
                    tp["style_image"] = {"url": style}
                else:
                    tp["style_image"] = {"file_token": style}
        elif ref_image_path or ref_image_url:
            ref = client.resolve_file_input(url=ref_image_url, path=ref_image_path)
            if ref.startswith(("http://", "https://")):
                tp["image"] = {"url": ref}
            else:
                tp["image"] = {"file_token": ref}
        if tp:
            body["texture_prompt"] = tp
        return _create_and_maybe_wait(
            "texture", body, wait=wait, wait_timeout=wait_timeout
        )
    except Exception as e:
        return _err(e)


@tool(
    name="tripo_convert",
    description=(
        "Tripo 模型格式转换。导入 Maya 前建议 format=FBX。"
        "可设 face_limit / quad / bake / fbx_preset 等。"
    ),
    parameters=obj_schema(
        {
            "input_task_id": {"type": "string"},
            "model_url": {"type": "string"},
            "model_path": {"type": "string"},
            "file_token": {"type": "string"},
            "format": {
                "type": "string",
                "enum": ["FBX", "GLTF", "USDZ", "OBJ", "STL", "3MF"],
                "default": "FBX",
            },
            "quad": {"type": "boolean"},
            "face_limit": {"type": "integer"},
            "bake": {"type": "boolean"},
            "texture_size": {"type": "integer"},
            "texture_format": {"type": "string"},
            "fbx_preset": {
                "type": "string",
                "enum": ["blender", "3dsmax", "mixamo", "bake_scale"],
            },
            "pivot_to_center_bottom": {"type": "boolean"},
            "export_orientation": {
                "type": "string",
                "enum": ["+x", "-x", "+y", "-y"],
            },
            "with_animation": {"type": "boolean"},
            "scale_factor": {"type": "number"},
            "wait": {"type": "boolean", "default": False},
            "wait_timeout": {"type": "number"},
        },
        required=["format"],
    ),
    category="tripo",
    main_thread=False,
)
def tripo_convert(
    format: str = "FBX",
    input_task_id: str = "",
    model_url: str = "",
    model_path: str = "",
    file_token: str = "",
    quad: Optional[bool] = None,
    face_limit: Optional[int] = None,
    bake: Optional[bool] = None,
    texture_size: Optional[int] = None,
    texture_format: str = "",
    fbx_preset: str = "",
    pivot_to_center_bottom: Optional[bool] = None,
    export_orientation: str = "",
    with_animation: Optional[bool] = None,
    scale_factor: Optional[float] = None,
    wait: bool = False,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    try:
        client = _client()
        inp = _resolve_model_input(
            client,
            input_task_id=input_task_id,
            model_url=model_url,
            model_path=model_path,
            file_token=file_token,
        )
        fmt = (format or "FBX").strip().upper()
        body: Dict[str, Any] = {"input": inp, "format": fmt}
        if quad is not None:
            body["quad"] = bool(quad)
        if face_limit is not None:
            body["face_limit"] = int(face_limit)
        if bake is not None:
            body["bake"] = bool(bake)
        if texture_size is not None:
            body["texture_size"] = int(texture_size)
        if texture_format:
            body["texture_format"] = texture_format
        if fbx_preset:
            body["fbx_preset"] = fbx_preset
        if pivot_to_center_bottom is not None:
            body["pivot_to_center_bottom"] = bool(pivot_to_center_bottom)
        if export_orientation:
            body["export_orientation"] = export_orientation
        if with_animation is not None:
            body["with_animation"] = bool(with_animation)
        if scale_factor is not None:
            body["scale_factor"] = float(scale_factor)
        return _create_and_maybe_wait(
            "convert", body, wait=wait, wait_timeout=wait_timeout
        )
    except Exception as e:
        return _err(e)


@tool(
    name="tripo_mesh_segment",
    description="Tripo 语义分割网格，产出可编辑部件（part_names 可供后续贴图/减面）。",
    parameters=obj_schema(
        {
            "input_task_id": {"type": "string"},
            "model_url": {"type": "string"},
            "model_path": {"type": "string"},
            "file_token": {"type": "string"},
            "wait": {"type": "boolean", "default": False},
            "wait_timeout": {"type": "number"},
        },
    ),
    category="tripo",
    main_thread=False,
)
def tripo_mesh_segment(
    input_task_id: str = "",
    model_url: str = "",
    model_path: str = "",
    file_token: str = "",
    wait: bool = False,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    try:
        client = _client()
        inp = _resolve_model_input(
            client,
            input_task_id=input_task_id,
            model_url=model_url,
            model_path=model_path,
            file_token=file_token,
        )
        return _create_and_maybe_wait(
            "mesh-segment",
            {"input": inp},
            wait=wait,
            wait_timeout=wait_timeout,
        )
    except Exception as e:
        return _err(e)


@tool(
    name="tripo_mesh_complete",
    description="Tripo 网格补全（填补破洞 / 不完整网格）。",
    parameters=obj_schema(
        {
            "input_task_id": {"type": "string"},
            "model_url": {"type": "string"},
            "model_path": {"type": "string"},
            "file_token": {"type": "string"},
            "wait": {"type": "boolean", "default": False},
            "wait_timeout": {"type": "number"},
        },
    ),
    category="tripo",
    main_thread=False,
)
def tripo_mesh_complete(
    input_task_id: str = "",
    model_url: str = "",
    model_path: str = "",
    file_token: str = "",
    wait: bool = False,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    try:
        client = _client()
        inp = _resolve_model_input(
            client,
            input_task_id=input_task_id,
            model_url=model_url,
            model_path=model_path,
            file_token=file_token,
        )
        return _create_and_maybe_wait(
            "mesh-complete",
            {"input": inp},
            wait=wait,
            wait_timeout=wait_timeout,
        )
    except Exception as e:
        return _err(e)


@tool(
    name="tripo_mesh_decimate",
    description=(
        "Tripo 重拓扑/减面。model: v3.0（可 smart_uv）/ v2.0（智能）/ v1.0（基础，face_limit 必填）。"
    ),
    parameters=obj_schema(
        {
            "input_task_id": {"type": "string"},
            "model_url": {"type": "string"},
            "model_path": {"type": "string"},
            "file_token": {"type": "string"},
            "model": {
                "type": "string",
                "enum": ["v3.0", "v2.0", "v1.0"],
                "default": "v2.0",
            },
            "face_limit": {"type": "integer"},
            "quad": {"type": "boolean"},
            "smart_uv": {"type": "boolean"},
            "bake": {"type": "boolean"},
            "part_names": {
                "type": "array",
                "items": {"type": "string"},
            },
            "wait": {"type": "boolean", "default": False},
            "wait_timeout": {"type": "number"},
        },
    ),
    category="tripo",
    main_thread=False,
)
def tripo_mesh_decimate(
    input_task_id: str = "",
    model_url: str = "",
    model_path: str = "",
    file_token: str = "",
    model: str = "v2.0",
    face_limit: Optional[int] = None,
    quad: Optional[bool] = None,
    smart_uv: Optional[bool] = None,
    bake: Optional[bool] = None,
    part_names: Optional[List[str]] = None,
    wait: bool = False,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    try:
        client = _client()
        inp = _resolve_model_input(
            client,
            input_task_id=input_task_id,
            model_url=model_url,
            model_path=model_path,
            file_token=file_token,
        )
        ver = (model or "v2.0").strip()
        if ver == "v1.0" and face_limit is None:
            return ToolResult(ok=False, error="model=v1.0 时 face_limit 必填")
        body: Dict[str, Any] = {"input": inp, "model": ver}
        if face_limit is not None:
            body["face_limit"] = int(face_limit)
        if quad is not None:
            body["quad"] = bool(quad)
        if smart_uv is not None:
            body["smart_uv"] = bool(smart_uv)
        if bake is not None:
            body["bake"] = bool(bake)
        if part_names:
            body["part_names"] = list(part_names)
        return _create_and_maybe_wait(
            "mesh-decimate", body, wait=wait, wait_timeout=wait_timeout
        )
    except Exception as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Animation
# ---------------------------------------------------------------------------


@tool(
    name="tripo_rig_check",
    description="检查模型是否可绑骨，并返回推荐 rig_type。绑骨前应先调用。",
    parameters=obj_schema(
        {
            "input_task_id": {"type": "string"},
            "model_url": {"type": "string"},
            "model_path": {"type": "string"},
            "file_token": {"type": "string"},
            "wait": {"type": "boolean", "default": True},
            "wait_timeout": {"type": "number"},
        },
    ),
    category="tripo",
    main_thread=False,
)
def tripo_rig_check(
    input_task_id: str = "",
    model_url: str = "",
    model_path: str = "",
    file_token: str = "",
    wait: bool = True,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    try:
        client = _client()
        inp = _resolve_model_input(
            client,
            input_task_id=input_task_id,
            model_url=model_url,
            model_path=model_path,
            file_token=file_token,
        )
        return _create_and_maybe_wait(
            "rig-check",
            {"input": inp},
            wait=wait,
            wait_timeout=wait_timeout,
        )
    except Exception as e:
        return _err(e)


@tool(
    name="tripo_rig",
    description=(
        "Tripo 自动绑骨。建议先 tripo_rig_check。"
        "rig_type: biped/quadruped/hexapod/octopod/avian/serpentine/aquatic；"
        "spec: tripo|mixamo；out_format 默认 fbx 便于导入 Maya。"
    ),
    parameters=obj_schema(
        {
            "input_task_id": {"type": "string"},
            "model_url": {"type": "string"},
            "model_path": {"type": "string"},
            "file_token": {"type": "string"},
            "model": {
                "type": "string",
                "description": "v1.0-20240301（双足）或 v2.5-20260210（动物等）",
            },
            "rig_type": {
                "type": "string",
                "enum": [
                    "biped",
                    "quadruped",
                    "hexapod",
                    "octopod",
                    "avian",
                    "serpentine",
                    "aquatic",
                ],
            },
            "spec": {"type": "string", "enum": ["tripo", "mixamo"]},
            "out_format": {"type": "string", "enum": ["fbx", "glb"], "default": "fbx"},
            "wait": {"type": "boolean", "default": False},
            "wait_timeout": {"type": "number"},
        },
    ),
    category="tripo",
    main_thread=False,
)
def tripo_rig(
    input_task_id: str = "",
    model_url: str = "",
    model_path: str = "",
    file_token: str = "",
    model: str = "",
    rig_type: str = "",
    spec: str = "",
    out_format: str = "fbx",
    wait: bool = False,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    try:
        client = _client()
        inp = _resolve_model_input(
            client,
            input_task_id=input_task_id,
            model_url=model_url,
            model_path=model_path,
            file_token=file_token,
        )
        body: Dict[str, Any] = {
            "input": inp,
            "out_format": (out_format or "fbx").strip().lower(),
        }
        if model:
            body["model"] = model
        if rig_type:
            body["rig_type"] = rig_type
        if spec:
            body["spec"] = spec
        return _create_and_maybe_wait(
            "rig", body, wait=wait, wait_timeout=wait_timeout
        )
    except Exception as e:
        return _err(e)


@tool(
    name="tripo_retarget",
    description=(
        "将预设动画重定向到已绑骨模型。input 为 rig 任务 id；"
        "animation 或 animations[]（如 preset:run / preset:biped:run）。"
        "默认 animate_in_place=true、export_with_geometry=true（游戏循环友好）。"
        "导入后若要驱动原分件：用 tripo_apply_to_meshes + tripo_apply_animation，"
        "禁止手写 xform/worldMatrix 迁曲线。可用 tripo_list_animations 查看预设。"
    ),
    parameters=obj_schema(
        {
            "input_task_id": {
                "type": "string",
                "description": "已绑骨任务 task_id",
            },
            "animation": {"type": "string"},
            "animations": {"type": "array", "items": {"type": "string"}},
            "out_format": {"type": "string", "enum": ["fbx", "glb"], "default": "fbx"},
            "bake_animation": {"type": "boolean"},
            "export_with_geometry": {
                "type": "boolean",
                "default": True,
                "description": "导出带几何的 FBX，便于直接导入 Maya",
            },
            "animate_in_place": {
                "type": "boolean",
                "default": True,
                "description": "原地动画（去掉根位移）；需要位移跑圈时显式传 false",
            },
            "wait": {"type": "boolean", "default": False},
            "wait_timeout": {"type": "number"},
        },
        required=["input_task_id"],
    ),
    category="tripo",
    main_thread=False,
)
def tripo_retarget(
    input_task_id: str,
    animation: str = "",
    animations: Optional[List[str]] = None,
    out_format: str = "fbx",
    bake_animation: Optional[bool] = None,
    export_with_geometry: bool = True,
    animate_in_place: bool = True,
    wait: bool = False,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    try:
        tid = (input_task_id or "").strip()
        if not tid:
            return ToolResult(ok=False, error="需要 input_task_id（绑骨任务）")
        if animations and animation:
            return ToolResult(ok=False, error="animation 与 animations 只能二选一")
        if not animation and not animations:
            return ToolResult(ok=False, error="需要 animation 或 animations")
        body: Dict[str, Any] = {
            "input": tid,
            "out_format": (out_format or "fbx").strip().lower(),
            "export_with_geometry": bool(export_with_geometry),
            "animate_in_place": bool(animate_in_place),
        }
        if animations:
            body["animations"] = list(animations)
        else:
            body["animation"] = animation.strip()
        if bake_animation is not None:
            body["bake_animation"] = bool(bake_animation)
        return _create_and_maybe_wait(
            "retarget", body, wait=wait, wait_timeout=wait_timeout
        )
    except Exception as e:
        return _err(e)


@tool(
    name="tripo_list_animations",
    description="列出 Tripo 文档中的预设动画 ID（静态列表，供 tripo_retarget 使用）。",
    parameters=obj_schema({}),
    category="tripo",
    main_thread=False,
)
def tripo_list_animations() -> ToolResult:
    return ToolResult(
        ok=True,
        data=ANIMATION_PRESETS,
        message="已列出常用预设；v1.0 biped 另有 90+ 个 preset:biped:*，详见官方文档。",
    )


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@tool(
    name="tripo_upload_file",
    description="上传本地图片或模型到 Tripo，返回 file_token 供后续 input 使用。",
    parameters=obj_schema(
        {"path": {"type": "string", "description": "本地文件绝对路径"}},
        required=["path"],
    ),
    category="tripo",
    main_thread=False,
)
def tripo_upload_file(path: str) -> ToolResult:
    try:
        token = _client().upload_file(path)
        return ToolResult(
            ok=True,
            data={"file_token": token, "path": path},
            message=f"已上传，file_token={token}",
        )
    except Exception as e:
        return _err(e)


@tool(
    name="tripo_get_task",
    description="查询 Tripo 任务状态与结果摘要（统一 GET /tasks/{id}）。",
    parameters=obj_schema(
        {"task_id": {"type": "string"}},
        required=["task_id"],
    ),
    category="tripo",
    main_thread=False,
)
def tripo_get_task(task_id: str) -> ToolResult:
    try:
        task = _client().get_task(task_id)
        return ToolResult(
            ok=True,
            data=summarize_task(task),
            message=f"status={task.get('status')} progress={task.get('progress')}",
        )
    except Exception as e:
        return _err(e)


@tool(
    name="tripo_wait_task",
    description=(
        "轮询等待 Tripo 任务至终态。成功后可 tripo_import_to_maya / tripo_download。"
        "超时用 timeout（秒）；也接受 wait_timeout 别名。"
    ),
    parameters=obj_schema(
        {
            "task_id": {"type": "string"},
            "timeout": {
                "type": "number",
                "description": "秒；默认用配置 tripo.wait_timeout",
            },
            "wait_timeout": {
                "type": "number",
                "description": "timeout 的别名（与其它 tripo_* 工具参数名一致）",
            },
            "poll_interval": {"type": "number"},
        },
        required=["task_id"],
    ),
    category="tripo",
    main_thread=False,
)
def tripo_wait_task(
    task_id: str,
    timeout: Optional[float] = None,
    wait_timeout: Optional[float] = None,
    poll_interval: Optional[float] = None,
) -> ToolResult:
    try:
        tid = (task_id or "").strip()
        client = _client()
        # Accept wait_timeout alias (LLM often mirrors other tripo_* tools)
        effective_timeout = timeout if timeout is not None else wait_timeout
        report_tool_progress(
            task_id=tid, status="waiting", progress=0, message="等待 Tripo 任务…"
        )
        task = client.wait(
            tid,
            timeout=effective_timeout,
            poll_interval=poll_interval,
            on_progress=_wait_progress("task", tid),
        )
        return ToolResult(
            ok=True,
            data={"task_id": tid, "task": summarize_task(task)},
            message=f"Tripo 任务已完成：{tid}",
        )
    except Exception as e:
        return _err(e)


@tool(
    name="tripo_list_tasks",
    description="批量查询 Tripo 任务（POST /tasks/list）。可选传入官方文档支持的过滤字段。",
    parameters=obj_schema(
        {
            "body": {
                "type": "object",
                "description": "请求体 JSON（按官方文档）",
            },
        },
    ),
    category="tripo",
    main_thread=False,
)
def tripo_list_tasks(body: Optional[Dict[str, Any]] = None) -> ToolResult:
    try:
        data = _client().list_tasks(body or {})
        return ToolResult(ok=True, data=data, message="已查询任务列表")
    except Exception as e:
        return _err(e)


@tool(
    name="tripo_download",
    description=(
        "下载已成功任务的模型或图片到本地。可传 task_id（自动选 URL）或直接 url。"
        "prefer_format 默认 fbx（模型）。"
    ),
    parameters=obj_schema(
        {
            "task_id": {"type": "string"},
            "url": {"type": "string"},
            "prefer_format": {"type": "string", "default": "fbx"},
            "as_image": {
                "type": "boolean",
                "description": "按图片 URL 选取（generated_image_url 等）",
            },
            "filename": {"type": "string"},
            "output_dir": {"type": "string"},
        },
    ),
    category="tripo",
    main_thread=False,
)
def tripo_download(
    task_id: str = "",
    url: str = "",
    prefer_format: str = "fbx",
    as_image: bool = False,
    filename: str = "",
    output_dir: str = "",
) -> ToolResult:
    try:
        client = _client()
        fmt = (prefer_format or "fbx").strip().lower()
        download_url = (url or "").strip()
        tid = (task_id or "").strip() or "asset"
        if not download_url:
            if not task_id:
                return ToolResult(ok=False, error="需要 url 或 task_id")
            task = client.get_task(task_id)
            if str(task.get("status") or "").lower() != "success":
                return ToolResult(
                    ok=False,
                    error=f"任务尚未成功（status={task.get('status')}）",
                    data=summarize_task(task),
                )
            tid = str(task.get("task_id") or task.get("id") or tid)
            if as_image:
                imgs = pick_image_urls(task)
                if not imgs:
                    return ToolResult(ok=False, error="任务结果中没有图片 URL")
                download_url = imgs[0]
                fmt = "png"
            else:
                fmt, download_url = pick_model_url(
                    task, prefer=[fmt, "fbx", "glb", "obj"]
                )

        out_dir = Path(output_dir) if output_dir else download_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        name = (filename or "").strip() or f"tripo_{tid}.{fmt}"
        if "." not in Path(name).name:
            name = f"{name}.{fmt}"
        dest = out_dir / name
        client.download(download_url, dest)
        return ToolResult(
            ok=True,
            data={"path": str(dest), "format": fmt, "task_id": tid},
            message=f"已下载: {dest}",
        )
    except Exception as e:
        return _err(e)


def _ns_pattern(namespace: str) -> str:
    ns = (namespace or "").strip()
    return f"{ns}:*" if ns else "*"


def _uniform_scale_of_node(node: str) -> float:
    import maya.cmds as cmds

    from maya_agent.tools.skin_weights import uniform_scale_from_matrix16

    m = cmds.xform(node, query=True, worldSpace=True, matrix=True) or []
    return uniform_scale_from_matrix16([float(x) for x in m])


def _collect_import_diagnostics(
    namespace: str,
    *,
    set_playback_range: bool = True,
) -> Dict[str, Any]:
    """Inventory + scale warning after Tripo FBX import (Maya main thread)."""
    import maya.cmds as cmds

    pat = _ns_pattern(namespace)
    joints = list(cmds.ls(pat, type="joint", long=True) or [])
    meshes = []
    for tf in cmds.ls(pat, type="transform", long=True) or []:
        shapes = (
            cmds.listRelatives(
                tf, shapes=True, type="mesh", noIntermediate=True, fullPath=True
            )
            or []
        )
        if shapes:
            meshes.append(tf)

    armature = ""
    for cand in ("Armature", "armature", "Root", "root"):
        hits = cmds.ls(f"{namespace}:{cand}" if namespace else cand, long=True) or []
        if hits:
            armature = hits[0]
            break
    if not armature:
        for j in joints:
            parents = cmds.listRelatives(j, parent=True, fullPath=True) or []
            if not parents or not cmds.ls(parents[0], type="joint"):
                # prefer non-joint parent named Armature-like
                if parents and "Armature" in parents[0]:
                    armature = parents[0]
                    break

    scale_nodes: List[Dict[str, Any]] = []
    scale_warning = False
    check_nodes = list(meshes)
    if armature:
        check_nodes.append(armature)
    for n in check_nodes[:40]:
        try:
            ws = _uniform_scale_of_node(n)
            loc = cmds.getAttr(f"{n}.scale")[0]
            local_u = (abs(float(loc[0])) + abs(float(loc[1])) + abs(float(loc[2]))) / 3.0
            entry = {
                "node": n,
                "world_scale": round(ws, 6),
                "local_scale_avg": round(local_u, 6),
            }
            scale_nodes.append(entry)
            if abs(ws - 1.0) > 0.05 or abs(local_u - 1.0) > 0.05:
                scale_warning = True
        except Exception:
            continue

    # Animation frame range from joint keys
    t_min: Optional[float] = None
    t_max: Optional[float] = None
    for j in joints[:80]:
        for a in list(_ROT_ATTRS) + list(_TRANS_ATTRS):
            try:
                times = cmds.keyframe(j, attribute=a, query=True, timeChange=True) or []
            except Exception:
                times = []
            for t in times:
                tf = float(t)
                t_min = tf if t_min is None else min(t_min, tf)
                t_max = tf if t_max is None else max(t_max, tf)

    frame_range: Optional[Dict[str, float]] = None
    if t_min is not None and t_max is not None:
        frame_range = {"min": t_min, "max": t_max}
        if set_playback_range:
            try:
                cmds.playbackOptions(
                    minTime=t_min, maxTime=t_max, animationStartTime=t_min, animationEndTime=t_max
                )
            except Exception:
                pass

    return {
        "namespace": namespace,
        "joints": joints,
        "joint_count": len(joints),
        "meshes": meshes,
        "mesh_count": len(meshes),
        "armature": armature,
        "frame_range": frame_range,
        "scale_report": {"nodes": scale_nodes, "scale_warning": scale_warning},
        "scale_warning": scale_warning,
    }


def _enrich_import_result(
    result: ToolResult,
    namespace: str,
    *,
    set_playback_range: bool = True,
) -> ToolResult:
    if not result.ok:
        return result
    try:
        diag = _collect_import_diagnostics(
            namespace, set_playback_range=set_playback_range
        )
    except Exception as e:
        log.exception("tripo import diagnostics failed")
        data = dict(result.data or {}) if isinstance(result.data, dict) else {"imported": result.data}
        data["diagnostics_error"] = str(e)
        return ToolResult(ok=True, data=data, message=result.message)

    data = dict(result.data or {}) if isinstance(result.data, dict) else {"imported": result.data}
    data.update(diag)
    msg = result.message or "已导入"
    if diag.get("scale_warning"):
        msg += (
            "；⚠ 检测到非单位尺度（常见 Armature/网格 scale≈100）。"
            "传回原分件请用 tripo_apply_to_meshes，"
            "迁动画请用 tripo_apply_animation；禁止手写矩阵/盲同步 bindPreMatrix。"
        )
    if diag.get("frame_range"):
        fr = diag["frame_range"]
        msg += f"；动画范围 {fr['min']}–{fr['max']}"
    return ToolResult(ok=True, data=data, message=msg)


@tool(
    name="tripo_import_to_maya",
    description=(
        "将 Tripo 成功任务的模型下载并导入当前 Maya 场景（优先 FBX）。"
        "若输出非 FBX，会自动先 convert→FBX 再导入。"
        "复用 Meshy 的 FBX PBR 重建逻辑。返回 joints/meshes/armature/"
        "frame_range/scale_report；非单位尺度时给出警告。"
        "prepare_normals=true 时对新网格 unlock+软边（默认关闭）。"
        "可传 task_id 或已下载 file_path。"
    ),
    parameters=obj_schema(
        {
            "task_id": {"type": "string"},
            "file_path": {"type": "string"},
            "prefer_format": {"type": "string", "default": "fbx"},
            "namespace": {"type": "string", "default": "tripo"},
            "output_dir": {"type": "string"},
            "rebuild_pbr": {"type": "boolean", "default": True},
            "prepare_normals": {
                "type": "boolean",
                "default": False,
                "description": "导入后对新网格解锁顶点法线并软边（默认 false）",
            },
            "normal_soften_angle": {
                "type": "number",
                "default": 30,
                "description": "prepare_normals 时的软边角度（度）",
            },
            "auto_convert_fbx": {
                "type": "boolean",
                "default": True,
                "description": "非 FBX 时自动 convert 为 FBX",
            },
            "set_playback_range": {
                "type": "boolean",
                "default": True,
                "description": "若有关节动画，写入时间滑块范围",
            },
        },
    ),
    category="tripo",
    main_thread=False,
)
def tripo_import_to_maya(
    task_id: str = "",
    file_path: str = "",
    prefer_format: str = "fbx",
    namespace: str = "tripo",
    output_dir: str = "",
    rebuild_pbr: bool = True,
    prepare_normals: bool = False,
    normal_soften_angle: float = 30.0,
    auto_convert_fbx: bool = True,
    set_playback_range: bool = True,
) -> ToolResult:
    try:
        from maya_agent.tools.meshy import _import_path_into_maya

        local = (file_path or "").strip()
        tid = (task_id or "").strip()
        if not local:
            if not tid:
                return ToolResult(ok=False, error="需要 task_id 或 file_path")
            dl = tripo_download(
                task_id=tid,
                prefer_format=prefer_format or "fbx",
                output_dir=output_dir,
            )
            if not dl.ok:
                return dl
            local = str((dl.data or {}).get("path") or "")
            fmt = str((dl.data or {}).get("format") or "").lower()
            if not local:
                return ToolResult(ok=False, error="下载成功但未返回路径")
            if fmt not in ("fbx",) and auto_convert_fbx:
                conv = tripo_convert(
                    format="FBX",
                    input_task_id=tid,
                    wait=True,
                )
                if not conv.ok:
                    return conv
                conv_tid = str((conv.data or {}).get("task_id") or "")
                if conv_tid:
                    dl2 = tripo_download(
                        task_id=conv_tid,
                        prefer_format="fbx",
                        output_dir=output_dir,
                    )
                    if dl2.ok:
                        local = str((dl2.data or {}).get("path") or local)

        ns = (namespace or "").strip() or "tripo"

        def _do() -> ToolResult:
            imported = _import_path_into_maya(
                local,
                namespace=ns,
                rebuild_pbr=bool(rebuild_pbr),
                prepare_normals=bool(prepare_normals),
                normal_soften_angle=float(normal_soften_angle),
            )
            return _enrich_import_result(
                imported, ns, set_playback_range=bool(set_playback_range)
            )

        return run_on_main_thread(_do)
    except Exception as e:
        return _err(e)


@tool(
    name="tripo_balance",
    description="查询 Tripo 账户余额（balance / frozen）。配置 API Key 后可用来测试连接。",
    parameters=obj_schema({}),
    category="tripo",
    main_thread=False,
)
def tripo_balance() -> ToolResult:
    try:
        data = _client().balance()
        return ToolResult(ok=True, data=data, message="已获取 Tripo 余额")
    except Exception as e:
        return _err(e)


@tool(
    name="tripo_usage",
    description="查询 Tripo 账户用量历史（GET /account/usage）。",
    parameters=obj_schema({}),
    category="tripo",
    main_thread=False,
)
def tripo_usage() -> ToolResult:
    try:
        data = _client().usage()
        return ToolResult(ok=True, data=data, message="已获取 Tripo 用量")
    except Exception as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Safe apply: weights + animation (avoid Agent hand-rolled matrix scripts)
# ---------------------------------------------------------------------------


def _try_restore_bind_pose(namespace: str = "") -> Dict[str, Any]:
    import maya.cmds as cmds

    ns = (namespace or "").strip()
    poses: List[str] = []
    if ns:
        poses = list(cmds.ls(f"{ns}:*", type="dagPose") or [])
    if not poses:
        poses = list(cmds.ls(type="dagPose") or [])
    for p in poses:
        try:
            cmds.dagPose(p, restore=True)
            return {"restored": p}
        except Exception:
            continue
    return {"restored": None}


def _resolve_meshes_under(root_or_list: Any) -> List[str]:
    """Expand a group / list into mesh transforms."""
    import maya.cmds as cmds

    names: List[str] = []
    if isinstance(root_or_list, str):
        raw = [root_or_list]
    else:
        raw = list(root_or_list or [])
    for n in raw:
        n = (n or "").strip()
        if not n or not cmds.objExists(n):
            continue
        shapes = (
            cmds.listRelatives(
                n, shapes=True, type="mesh", noIntermediate=True, fullPath=True
            )
            or []
        )
        if shapes:
            names.append(cmds.ls(n, long=True)[0])
            continue
        for tf in cmds.listRelatives(n, allDescendents=True, type="transform", fullPath=True) or []:
            sh = (
                cmds.listRelatives(
                    tf, shapes=True, type="mesh", noIntermediate=True, fullPath=True
                )
                or []
            )
            if sh:
                names.append(tf)
    # unique preserve order
    seen = set()
    out: List[str] = []
    for m in names:
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def _namespace_of_node(node: str) -> str:
    leaf = (node or "").split("|")[-1]
    if ":" in leaf:
        return leaf.rsplit(":", 1)[0]
    return ""


@tool(
    name="tripo_apply_to_meshes",
    description=(
        "把 Tripo 导入的合并蒙皮体权重安全传到原分件："
        "尽量恢复 bindPose → align_skinned_rig → transfer_skin_weights。"
        "尺度不匹配时自动跳过 bindPreMatrix sync（防炸模）。"
        "对齐后保持，勿移回骨架。不要用手写脚本代替本工具。"
    ),
    parameters=obj_schema(
        {
            "source_mesh": {
                "type": "string",
                "description": "Tripo 导入的已蒙皮合并网格",
            },
            "target_meshes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "原分件网格列表；也可传父组名（自动展开）",
            },
            "align": {"type": "boolean", "default": True},
            "align_root": {"type": "string", "default": ""},
            "match": {
                "type": "string",
                "enum": ["feet", "center"],
                "default": "feet",
            },
            "uniform_scale": {"type": "boolean", "default": True},
            "max_influences": {"type": "integer", "default": 4},
        },
        required=["source_mesh", "target_meshes"],
    ),
    category="tripo",
    destructive=True,
    main_thread=True,
)
def tripo_apply_to_meshes(
    source_mesh: str,
    target_meshes: Optional[List[str]] = None,
    align: bool = True,
    align_root: str = "",
    match: str = "feet",
    uniform_scale: bool = True,
    max_influences: int = 4,
) -> ToolResult:
    try:
        from maya_agent.tools.skin_weights import transfer_skin_weights
        from maya_agent.utils.maya_compat import in_maya

        if not in_maya():
            return ToolResult(ok=False, error="未在 Maya 中运行")
        if not (source_mesh or "").strip():
            return ToolResult(ok=False, error="需要 source_mesh")
        targets = _resolve_meshes_under(target_meshes or [])
        if not targets:
            return ToolResult(ok=False, error="target_meshes 为空或未解析到网格")

        ns = _namespace_of_node(source_mesh)
        bind_info = _try_restore_bind_pose(ns)
        xfer = transfer_skin_weights(
            source=source_mesh,
            destinations=targets,
            align=bool(align),
            align_root=align_root or "",
            match=match or "feet",
            uniform_scale=bool(uniform_scale),
            auto_bind=True,
            max_influences=int(max_influences),
            sync_bind_prematrix=True,
        )
        data: Dict[str, Any] = dict(xfer.data or {}) if isinstance(xfer.data, dict) else {}
        data["bind_pose"] = bind_info
        data["target_count"] = len(targets)
        msg = xfer.message or ""
        if bind_info.get("restored"):
            msg = f"已恢复 bindPose={bind_info['restored']}；" + msg
        return ToolResult(
            ok=xfer.ok,
            data=data,
            message=msg,
            error=xfer.error or "",
        )
    except Exception as e:
        return _err(e)


@tool(
    name="tripo_apply_animation",
    description=(
        "把源命名空间（如 tripo_anim retarget 导入）的动画安全拷到目标命名空间（如 tripo_rig）。"
        "按关节短名匹配；默认 mode=rotations_only（不拷肢体 translate，避免 Hip 常量炸链）。"
        "rotations_and_root_translate 仅额外拷 Root/Hip/Armature 的 translate。"
        "用 keyframe+setKeyframe，禁止手写 xform -m / worldMatrix。"
    ),
    parameters=obj_schema(
        {
            "source_namespace": {"type": "string"},
            "target_namespace": {"type": "string"},
            "mode": {
                "type": "string",
                "enum": ["rotations_only", "rotations_and_root_translate"],
                "default": "rotations_only",
            },
            "root_joint_names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "视为根骨短名；默认 Root/Hip/Armature 等",
            },
            "hide_source": {
                "type": "boolean",
                "default": True,
                "description": "拷完后隐藏源命名空间下网格与 Armature",
            },
            "set_playback_range": {"type": "boolean", "default": True},
            "clear_target_keys": {
                "type": "boolean",
                "default": True,
                "description": "写入前清除目标关节上已有 TR 关键帧",
            },
        },
        required=["source_namespace", "target_namespace"],
    ),
    category="tripo",
    destructive=True,
    main_thread=True,
)
def tripo_apply_animation(
    source_namespace: str,
    target_namespace: str,
    mode: str = "rotations_only",
    root_joint_names: Optional[List[str]] = None,
    hide_source: bool = True,
    set_playback_range: bool = True,
    clear_target_keys: bool = True,
) -> ToolResult:
    try:
        import maya.cmds as cmds
        from maya_agent.utils.maya_compat import in_maya

        if not in_maya():
            return ToolResult(ok=False, error="未在 Maya 中运行")
        src_ns = (source_namespace or "").strip().rstrip(":")
        dst_ns = (target_namespace or "").strip().rstrip(":")
        if not src_ns or not dst_ns:
            return ToolResult(ok=False, error="需要 source_namespace 与 target_namespace")
        if src_ns == dst_ns:
            return ToolResult(ok=False, error="源与目标命名空间不能相同")

        src_joints = list(cmds.ls(f"{src_ns}:*", type="joint", long=True) or [])
        dst_joints = list(cmds.ls(f"{dst_ns}:*", type="joint", long=True) or [])
        if not src_joints:
            return ToolResult(ok=False, error=f"源命名空间无关节: {src_ns}")
        if not dst_joints:
            return ToolResult(ok=False, error=f"目标命名空间无关节: {dst_ns}")

        src_by = {short_joint_name(j): j for j in src_joints}
        dst_by = {short_joint_name(j): j for j in dst_joints}
        common = sorted(set(src_by) & set(dst_by))
        missing_src = sorted(set(dst_by) - set(src_by))
        missing_dst = sorted(set(src_by) - set(dst_by))

        roots = list(root_joint_names) if root_joint_names else None
        n_j = 0
        n_k = 0
        t_min: Optional[float] = None
        t_max: Optional[float] = None
        attrs_all = list(_ROT_ATTRS) + list(_TRANS_ATTRS)

        for name in common:
            s = src_by[name]
            d = dst_by[name]
            try:
                cmds.setAttr(f"{d}.rotateOrder", cmds.getAttr(f"{s}.rotateOrder"))
            except Exception:
                pass
            if clear_target_keys:
                try:
                    cmds.cutKey(d, attribute=attrs_all, clear=True)
                except Exception:
                    pass
            attrs = animation_attrs_for_mode(mode, name, root_shorts=roots)
            got = False
            for a in attrs:
                try:
                    times = cmds.keyframe(s, attribute=a, query=True, timeChange=True) or []
                    vals = cmds.keyframe(s, attribute=a, query=True, valueChange=True) or []
                except Exception:
                    continue
                if not times or not vals or len(times) != len(vals):
                    continue
                for t, v in zip(times, vals):
                    cmds.setKeyframe(d, attribute=a, time=float(t), value=float(v))
                    n_k += 1
                    tf = float(t)
                    t_min = tf if t_min is None else min(t_min, tf)
                    t_max = tf if t_max is None else max(t_max, tf)
                got = True
            if got:
                n_j += 1

        frame_range = None
        if t_min is not None and t_max is not None:
            frame_range = {"min": t_min, "max": t_max}
            if set_playback_range:
                try:
                    cmds.playbackOptions(
                        minTime=t_min,
                        maxTime=t_max,
                        animationStartTime=t_min,
                        animationEndTime=t_max,
                    )
                except Exception:
                    pass

        if hide_source:
            for tf in cmds.ls(f"{src_ns}:*", type="transform", long=True) or []:
                try:
                    if cmds.attributeQuery("visibility", node=tf, exists=True):
                        cmds.setAttr(f"{tf}.visibility", 0)
                except Exception:
                    pass

        data = {
            "mode": mode,
            "source_namespace": src_ns,
            "target_namespace": dst_ns,
            "joints_copied": n_j,
            "keyframes_written": n_k,
            "common_joints": len(common),
            "missing_on_source": missing_src[:20],
            "missing_on_target": missing_dst[:20],
            "frame_range": frame_range,
            "hide_source": bool(hide_source),
        }
        return ToolResult(
            ok=True,
            data=data,
            message=(
                f"动画已应用 {src_ns} → {dst_ns}：关节 {n_j}，关键帧 {n_k}，"
                f"mode={mode}"
                + (
                    f"，范围 {frame_range['min']}–{frame_range['max']}"
                    if frame_range
                    else ""
                )
            ),
        )
    except Exception as e:
        return _err(e)


def _backup_and_resize_file_textures(
    max_size: int,
    temp_dir: Path,
) -> tuple:
    """
    Temporarily point file nodes at resized copies.
    Returns (backups: List[(node, orig_path)], resized_paths: List[str]).
    """
    import maya.cmds as cmds

    backups: List[tuple] = []
    resized_paths: List[str] = []
    if max_size <= 0:
        return backups, resized_paths

    try:
        from PIL import Image
    except Exception:
        return backups, resized_paths

    temp_dir.mkdir(parents=True, exist_ok=True)
    for node in cmds.ls(type="file") or []:
        try:
            path = cmds.getAttr(f"{node}.fileTextureName") or ""
        except Exception:
            continue
        path = str(path).strip()
        if not path or not Path(path).is_file():
            continue
        try:
            with Image.open(path) as im:
                w, h = im.size
                if max(w, h) <= max_size:
                    continue
                im2 = im.copy()
                resample = getattr(
                    getattr(Image, "Resampling", Image), "LANCZOS", Image.LANCZOS
                )
                im2.thumbnail((max_size, max_size), resample)
                dest = temp_dir / f"{Path(path).stem}_{max_size}{Path(path).suffix}"
                # TGA/others: convert to PNG for safer embed
                if dest.suffix.lower() not in (".png", ".jpg", ".jpeg"):
                    dest = dest.with_suffix(".png")
                    if im2.mode not in ("RGB", "RGBA"):
                        im2 = im2.convert("RGBA")
                im2.save(str(dest))
            backups.append((node, path))
            resized_paths.append(str(dest))
            cmds.setAttr(f"{node}.fileTextureName", str(dest), type="string")
        except Exception as e:
            log.warning("resize texture failed %s: %s", path, e)
    return backups, resized_paths


def _restore_file_textures(backups: Sequence[tuple]) -> None:
    import maya.cmds as cmds

    for node, path in backups:
        try:
            if cmds.objExists(node):
                cmds.setAttr(f"{node}.fileTextureName", path, type="string")
        except Exception:
            pass


@tool(
    name="tripo_prepare_rig_export",
    description=(
        "为 Tripo 绑骨准备本地 FBX：从根节点/网格列表收集 mesh，"
        "可选合并（仅处理副本，不破坏原分件）、临时缩小贴图、"
        "export_fbx(embed_textures=true) 到临时目录，最后还原贴图路径。"
        "多网格角色送 tripo_rig_check 前应先调用本工具。"
    ),
    parameters=obj_schema(
        {
            "root": {
                "type": "string",
                "description": "角色根组（如 Jineks_Model）；与 meshes 二选一或并用",
            },
            "meshes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "显式网格列表",
            },
            "combine": {
                "type": "boolean",
                "default": True,
                "description": "多网格时合并副本再导出（原分件保留）",
            },
            "max_texture_size": {
                "type": "integer",
                "default": 1024,
                "description": "临时缩贴图边长上限；0=不缩",
            },
            "output_path": {
                "type": "string",
                "description": "输出 FBX 路径；空则写入 agent temp",
            },
            "combined_name": {
                "type": "string",
                "default": "tripo_rig_export_merged",
            },
        },
    ),
    category="tripo",
    destructive=True,
    main_thread=True,
)
def tripo_prepare_rig_export(
    root: str = "",
    meshes: Optional[List[str]] = None,
    combine: bool = True,
    max_texture_size: int = 1024,
    output_path: str = "",
    combined_name: str = "tripo_rig_export_merged",
) -> ToolResult:
    try:
        import maya.cmds as cmds
        from maya_agent.tools.export import export_fbx
        from maya_agent.tools.modeling import combine_meshes
        from maya_agent.utils.maya_compat import in_maya
        from maya_agent.utils.paths import agent_temp_subdir

        if not in_maya():
            return ToolResult(ok=False, error="未在 Maya 中运行")

        collected: List[str] = []
        if meshes:
            collected.extend(_resolve_meshes_under(meshes))
        if (root or "").strip():
            collected.extend(_resolve_meshes_under(root.strip()))
        # unique
        seen = set()
        mesh_list: List[str] = []
        for m in collected:
            if m not in seen:
                seen.add(m)
                mesh_list.append(m)
        if not mesh_list:
            return ToolResult(ok=False, error="未找到可导出的网格（检查 root / meshes）")

        temp_root = agent_temp_subdir("tripo_exports")
        tex_tmp = temp_root / "tex_resized"
        backups, resized = _backup_and_resize_file_textures(int(max_texture_size or 0), tex_tmp)

        export_targets = mesh_list
        cleanup: List[str] = []
        try:
            if combine and len(mesh_list) > 1:
                dups = cmds.duplicate(mesh_list, returnRootsOnly=True) or []
                cleanup.extend([d for d in dups if d])
                cmb = combine_meshes(
                    names=list(dups),
                    new_name=(combined_name or "tripo_rig_export_merged").strip()
                    or "tripo_rig_export_merged",
                    merge_vertices=False,
                    delete_history=True,
                )
                if not cmb.ok:
                    return ToolResult(
                        ok=False,
                        error=cmb.error or "合并失败",
                        data={"mesh_count": len(mesh_list)},
                    )
                combined_node = str((cmb.data or {}).get("name") or "")
                if not combined_node:
                    return ToolResult(ok=False, error="合并未返回节点名")
                export_targets = [combined_node]
                cleanup.append(combined_node)

            out = (output_path or "").strip()
            if not out:
                out = str(temp_root / "tripo_rig_input.fbx")
            if not out.lower().endswith(".fbx"):
                out += ".fbx"

            cmds.select(export_targets, replace=True)
            exp = export_fbx(
                file_path=out,
                selection_only=True,
                export_animation=False,
                export_skins=False,
                embed_textures=True,
            )
            if not exp.ok:
                return ToolResult(
                    ok=False,
                    error=exp.error or "FBX 导出失败",
                    data={"targets": export_targets},
                )

            meta = dict(exp.data or {}) if isinstance(exp.data, dict) else {}
            path = str(meta.get("path") or out)
            size_mb = 0.0
            try:
                size_mb = Path(path).stat().st_size / (1024.0 * 1024.0)
            except Exception:
                pass
            faces = 0
            try:
                for t in export_targets:
                    if cmds.objExists(t):
                        faces += int(cmds.polyEvaluate(t, face=True) or 0)
            except Exception:
                pass

            return ToolResult(
                ok=True,
                data={
                    "path": path,
                    "mesh_count_input": len(mesh_list),
                    "combined": bool(combine and len(mesh_list) > 1),
                    "faces": faces,
                    "size_mb": round(size_mb, 3),
                    "textures_resized": len(resized),
                    "max_texture_size": int(max_texture_size or 0),
                },
                message=(
                    f"已导出 Tripo 绑骨用 FBX: {path} "
                    f"（输入网格 {len(mesh_list)}，面数≈{faces}，{size_mb:.2f} MB）。"
                    "下一步：tripo_rig_check(model_path=...) → tripo_rig。"
                ),
            )
        finally:
            _restore_file_textures(backups)
            for n in reversed(cleanup):
                try:
                    if n and cmds.objExists(n):
                        cmds.delete(n)
                except Exception:
                    pass
    except Exception as e:
        return _err(e)
