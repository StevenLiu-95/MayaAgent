"""Meshy AI tools — text/image to 3D, remesh, rig, download & import into Maya."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from maya_agent.tools.meshy_client import (
    KIND_PATHS,
    MeshyClient,
    MeshyError,
    drop_none,
    download_dir,
    meshy_cfg,
    pick_model_url,
    resolve_image_input,
    resolve_model_input,
    summarize_task,
)
from maya_agent.core.tool_progress import report_tool_progress
from maya_agent.tools.registry import ToolResult, obj_schema, tool
from maya_agent.utils.logger import get_logger
from maya_agent.utils.maya_compat import ensure_plugin, in_maya, run_on_main_thread

log = get_logger("maya_agent.meshy_tools")

_KIND_ENUM = sorted(KIND_PATHS.keys())


def _client() -> MeshyClient:
    return MeshyClient()


def _err(exc: Exception) -> ToolResult:
    if isinstance(exc, MeshyError):
        data = summarize_task(exc.payload) if isinstance(exc.payload, dict) else exc.payload
        return ToolResult(ok=False, error=str(exc), data=data)
    log.exception("meshy tool failed")
    return ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}")


def _wait_progress(kind: str, task_id: str):
    def _on(info: Dict[str, Any]) -> None:
        status = str(info.get("status") or "")
        progress = info.get("progress")
        pct = ""
        if progress is not None:
            try:
                pct = f" {int(progress)}%"
            except (TypeError, ValueError):
                pct = f" {progress}"
        report_tool_progress(
            kind=kind,
            task_id=task_id,
            status=status,
            progress=progress,
            message=f"Meshy {kind} {status}{pct}".strip(),
        )

    return _on


def _create_and_maybe_wait(
    kind: str,
    body: Dict[str, Any],
    *,
    wait: bool = False,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    client = _client()
    task_id = client.create(kind, drop_none(body))
    if not wait:
        return ToolResult(
            ok=True,
            data={"kind": kind, "task_id": task_id, "status": "CREATED"},
            message=(
                f"已创建 Meshy 任务 {kind}：{task_id}。"
                f"请调用 meshy_wait_task(kind={kind!r}, task_id=...) 等待完成，"
                "再用 meshy_import_to_maya 导入 Maya。"
            ),
        )
    report_tool_progress(
        kind=kind,
        task_id=task_id,
        status="PENDING",
        progress=0,
        message=f"Meshy {kind} 已创建，等待中…",
    )
    task = client.wait(
        kind, task_id, timeout=wait_timeout, on_progress=_wait_progress(kind, task_id)
    )
    return ToolResult(
        ok=True,
        data={"kind": kind, "task_id": task_id, "task": summarize_task(task)},
        message=f"Meshy 任务已完成：{task_id}",
    )


def _formats_or_default(target_formats: Optional[List[str]]) -> List[str]:
    if target_formats:
        return list(target_formats)
    return list(meshy_cfg().get("default_formats") or ["fbx", "glb"])


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


@tool(
    name="meshy_text_to_3d",
    description=(
        "Meshy 文生 3D（两步：preview 几何 → refine 贴图）。"
        "preview 需 prompt；refine 需 preview_task_id（可加 texture_prompt）。"
        "默认只返回 task_id；设 wait=true 则轮询至完成。"
    ),
    parameters=obj_schema(
        {
            "mode": {
                "type": "string",
                "enum": ["preview", "refine"],
                "description": "preview=几何预览；refine=基于预览贴图",
            },
            "prompt": {"type": "string", "description": "preview 模式必填，最多 800 字"},
            "preview_task_id": {
                "type": "string",
                "description": "refine 模式必填：已成功的 preview 任务 id",
            },
            "texture_prompt": {"type": "string"},
            "texture_image_url": {"type": "string"},
            "texture_image_path": {"type": "string", "description": "本地贴图引导图路径"},
            "ai_model": {
                "type": "string",
                "description": "如 latest / meshy-7.1 / meshy-6 / meshy-t2",
            },
            "model_type": {
                "type": "string",
                "enum": ["standard", "smart-topology", "lowpoly"],
            },
            "topology": {"type": "string", "enum": ["quad", "triangle"]},
            "target_polycount": {"type": "integer"},
            "should_remesh": {"type": "boolean"},
            "enable_pbr": {"type": "boolean"},
            "pose_mode": {"type": "string", "enum": ["a-pose", "t-pose", ""]},
            "geometry_resolution": {
                "type": "string",
                "enum": ["standard", "2k", "4k"],
            },
            "target_formats": {
                "type": "array",
                "items": {"type": "string"},
                "description": "如 [\"fbx\",\"glb\"]；省略用配置默认",
            },
            "wait": {"type": "boolean", "default": False},
            "wait_timeout": {"type": "number"},
        },
        required=["mode"],
    ),
    category="meshy",
    main_thread=False,
)
def meshy_text_to_3d(
    mode: str,
    prompt: str = "",
    preview_task_id: str = "",
    texture_prompt: str = "",
    texture_image_url: str = "",
    texture_image_path: str = "",
    ai_model: str = "",
    model_type: str = "",
    topology: str = "",
    target_polycount: Optional[int] = None,
    should_remesh: Optional[bool] = None,
    enable_pbr: Optional[bool] = None,
    pose_mode: str = "",
    geometry_resolution: str = "",
    target_formats: Optional[List[str]] = None,
    wait: bool = False,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    try:
        mode = (mode or "").strip().lower()
        if mode not in ("preview", "refine"):
            return ToolResult(ok=False, error="mode 必须是 preview 或 refine")
        body: Dict[str, Any] = {"mode": mode}
        if mode == "preview":
            if not (prompt or "").strip():
                return ToolResult(ok=False, error="preview 模式需要 prompt")
            body["prompt"] = prompt.strip()
        else:
            if not (preview_task_id or "").strip():
                return ToolResult(ok=False, error="refine 模式需要 preview_task_id")
            body["preview_task_id"] = preview_task_id.strip()
            if texture_prompt:
                body["texture_prompt"] = texture_prompt
            if texture_image_path or texture_image_url:
                body["texture_image_url"] = resolve_image_input(
                    image_url=texture_image_url, image_path=texture_image_path
                )
        if ai_model:
            body["ai_model"] = ai_model
        if model_type:
            body["model_type"] = model_type
        if topology:
            body["topology"] = topology
        if target_polycount is not None:
            body["target_polycount"] = int(target_polycount)
        if should_remesh is not None:
            body["should_remesh"] = bool(should_remesh)
        if enable_pbr is not None:
            body["enable_pbr"] = bool(enable_pbr)
        if pose_mode:
            body["pose_mode"] = pose_mode
        if geometry_resolution:
            body["geometry_resolution"] = geometry_resolution
        body["target_formats"] = _formats_or_default(target_formats)
        return _create_and_maybe_wait(
            "text-to-3d", body, wait=wait, wait_timeout=wait_timeout
        )
    except Exception as e:
        return _err(e)


@tool(
    name="meshy_image_to_3d",
    description=(
        "Meshy 图生 3D。提供公网 image_url，或本地 image_path（转 data URI）。"
        "也可 use_latest_chat_image=true 使用对话中刚附带并已落盘的图片；"
        "或传 input_task_id。默认返回 task_id；wait=true 则等到完成。"
    ),
    parameters=obj_schema(
        {
            "image_url": {"type": "string"},
            "image_path": {"type": "string"},
            "use_latest_chat_image": {
                "type": "boolean",
                "default": False,
                "description": "为 true 时自动使用最近一张对话附图的本地路径",
            },
            "input_task_id": {"type": "string"},
            "ai_model": {"type": "string"},
            "model_type": {
                "type": "string",
                "enum": ["standard", "smart-topology", "lowpoly"],
            },
            "topology": {"type": "string", "enum": ["quad", "triangle"]},
            "target_polycount": {"type": "integer"},
            "should_remesh": {"type": "boolean"},
            "should_texture": {"type": "boolean"},
            "enable_pbr": {"type": "boolean"},
            "texture_prompt": {"type": "string"},
            "pose_mode": {"type": "string", "enum": ["a-pose", "t-pose", ""]},
            "geometry_resolution": {
                "type": "string",
                "enum": ["standard", "2k", "4k"],
            },
            "target_formats": {
                "type": "array",
                "items": {"type": "string"},
            },
            "wait": {"type": "boolean", "default": False},
            "wait_timeout": {"type": "number"},
        },
    ),
    category="meshy",
    main_thread=False,
)
def meshy_image_to_3d(
    image_url: str = "",
    image_path: str = "",
    use_latest_chat_image: bool = False,
    input_task_id: str = "",
    ai_model: str = "",
    model_type: str = "",
    topology: str = "",
    target_polycount: Optional[int] = None,
    should_remesh: Optional[bool] = None,
    should_texture: Optional[bool] = None,
    enable_pbr: Optional[bool] = None,
    texture_prompt: str = "",
    pose_mode: str = "",
    geometry_resolution: str = "",
    target_formats: Optional[List[str]] = None,
    wait: bool = False,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    try:
        body: Dict[str, Any] = {}
        if use_latest_chat_image and not image_path and not image_url and not input_task_id:
            from maya_agent.tools.fsutil import latest_chat_image_paths

            paths = latest_chat_image_paths(limit=1)
            if not paths:
                return ToolResult(
                    ok=False,
                    error=(
                        "没有可用的对话附图。请用户在输入框附带图片后发送，"
                        "或改用 image_path / image_url，也可先 list_chat_images。"
                    ),
                )
            image_path = paths[0]
        if (input_task_id or "").strip():
            body["input_task_id"] = input_task_id.strip()
        elif image_url or image_path:
            body["image_url"] = resolve_image_input(
                image_url=image_url, image_path=image_path
            )
        else:
            return ToolResult(
                ok=False,
                error="需要 image_url、image_path、use_latest_chat_image 或 input_task_id 之一",
            )
        if ai_model:
            body["ai_model"] = ai_model
        if model_type:
            body["model_type"] = model_type
        if topology:
            body["topology"] = topology
        if target_polycount is not None:
            body["target_polycount"] = int(target_polycount)
        if should_remesh is not None:
            body["should_remesh"] = bool(should_remesh)
        if should_texture is not None:
            body["should_texture"] = bool(should_texture)
        if enable_pbr is not None:
            body["enable_pbr"] = bool(enable_pbr)
        if texture_prompt:
            body["texture_prompt"] = texture_prompt
        if pose_mode:
            body["pose_mode"] = pose_mode
        if geometry_resolution:
            body["geometry_resolution"] = geometry_resolution
        body["target_formats"] = _formats_or_default(target_formats)
        return _create_and_maybe_wait(
            "image-to-3d", body, wait=wait, wait_timeout=wait_timeout
        )
    except Exception as e:
        return _err(e)


@tool(
    name="meshy_multi_image_to_3d",
    description=(
        "Meshy 多视图图生 3D（最多 4 张）。image_urls 为公网 URL 列表，"
        "或 image_paths 为本地路径列表；也可 use_latest_chat_images=true "
        "使用最近对话附图。默认返回 task_id。"
    ),
    parameters=obj_schema(
        {
            "image_urls": {"type": "array", "items": {"type": "string"}},
            "image_paths": {"type": "array", "items": {"type": "string"}},
            "use_latest_chat_images": {
                "type": "boolean",
                "default": False,
                "description": "为 true 时使用最近最多 4 张对话附图",
            },
            "ai_model": {"type": "string"},
            "topology": {"type": "string", "enum": ["quad", "triangle"]},
            "target_polycount": {"type": "integer"},
            "should_remesh": {"type": "boolean"},
            "should_texture": {"type": "boolean"},
            "enable_pbr": {"type": "boolean"},
            "pose_mode": {"type": "string", "enum": ["a-pose", "t-pose", ""]},
            "target_formats": {
                "type": "array",
                "items": {"type": "string"},
            },
            "wait": {"type": "boolean", "default": False},
            "wait_timeout": {"type": "number"},
        },
    ),
    category="meshy",
    main_thread=False,
)
def meshy_multi_image_to_3d(
    image_urls: Optional[List[str]] = None,
    image_paths: Optional[List[str]] = None,
    use_latest_chat_images: bool = False,
    ai_model: str = "",
    topology: str = "",
    target_polycount: Optional[int] = None,
    should_remesh: Optional[bool] = None,
    should_texture: Optional[bool] = None,
    enable_pbr: Optional[bool] = None,
    pose_mode: str = "",
    target_formats: Optional[List[str]] = None,
    wait: bool = False,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    try:
        urls: List[str] = []
        paths = list(image_paths or [])
        if use_latest_chat_images and not paths and not image_urls:
            from maya_agent.tools.fsutil import latest_chat_image_paths

            paths = latest_chat_image_paths(limit=4)
            if not paths:
                return ToolResult(
                    ok=False,
                    error="没有可用的对话附图。请先附带图片发送，或提供 image_paths/image_urls。",
                )
        for u in image_urls or []:
            if u:
                urls.append(resolve_image_input(image_url=str(u)))
        for p in paths:
            if p:
                urls.append(resolve_image_input(image_path=str(p)))
        if not urls:
            return ToolResult(ok=False, error="需要至少一张 image_urls / image_paths / 对话附图")
        if len(urls) > 4:
            return ToolResult(ok=False, error="最多 4 张参考图")
        body: Dict[str, Any] = {"image_urls": urls}
        if ai_model:
            body["ai_model"] = ai_model
        if topology:
            body["topology"] = topology
        if target_polycount is not None:
            body["target_polycount"] = int(target_polycount)
        if should_remesh is not None:
            body["should_remesh"] = bool(should_remesh)
        if should_texture is not None:
            body["should_texture"] = bool(should_texture)
        if enable_pbr is not None:
            body["enable_pbr"] = bool(enable_pbr)
        if pose_mode:
            body["pose_mode"] = pose_mode
        body["target_formats"] = _formats_or_default(target_formats)
        return _create_and_maybe_wait(
            "multi-image-to-3d", body, wait=wait, wait_timeout=wait_timeout
        )
    except Exception as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Post-process
# ---------------------------------------------------------------------------


@tool(
    name="meshy_retexture",
    description=(
        "Meshy 重贴图。用 input_task_id（已成功的 3D 任务）或 model_url/model_path，"
        "加 text_style_prompt 或 image_style_url/path。"
    ),
    parameters=obj_schema(
        {
            "input_task_id": {"type": "string"},
            "model_url": {"type": "string"},
            "model_path": {"type": "string"},
            "text_style_prompt": {"type": "string"},
            "image_style_url": {"type": "string"},
            "image_style_path": {"type": "string"},
            "enable_pbr": {"type": "boolean"},
            "ai_model": {"type": "string"},
            "target_formats": {
                "type": "array",
                "items": {"type": "string"},
            },
            "wait": {"type": "boolean", "default": False},
            "wait_timeout": {"type": "number"},
        },
    ),
    category="meshy",
    main_thread=False,
)
def meshy_retexture(
    input_task_id: str = "",
    model_url: str = "",
    model_path: str = "",
    text_style_prompt: str = "",
    image_style_url: str = "",
    image_style_path: str = "",
    enable_pbr: Optional[bool] = None,
    ai_model: str = "",
    target_formats: Optional[List[str]] = None,
    wait: bool = False,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    try:
        body: Dict[str, Any] = {}
        if (input_task_id or "").strip():
            body["input_task_id"] = input_task_id.strip()
        elif model_url or model_path:
            body["model_url"] = resolve_model_input(
                model_url=model_url, model_path=model_path
            )
        else:
            return ToolResult(
                ok=False, error="需要 input_task_id 或 model_url/model_path"
            )
        if text_style_prompt:
            body["text_style_prompt"] = text_style_prompt
        if image_style_url or image_style_path:
            body["image_style_url"] = resolve_image_input(
                image_url=image_style_url, image_path=image_style_path
            )
        if not body.get("text_style_prompt") and not body.get("image_style_url"):
            return ToolResult(
                ok=False, error="需要 text_style_prompt 或 image_style_url/path"
            )
        if enable_pbr is not None:
            body["enable_pbr"] = bool(enable_pbr)
        if ai_model:
            body["ai_model"] = ai_model
        body["target_formats"] = _formats_or_default(target_formats)
        return _create_and_maybe_wait(
            "retexture", body, wait=wait, wait_timeout=wait_timeout
        )
    except Exception as e:
        return _err(e)


@tool(
    name="meshy_remesh",
    description=(
        "Meshy Remesh：重拓扑/降面并导出格式。input_task_id 或 model_url/path。"
        "游戏资产常用 topology=quad + target_polycount。"
    ),
    parameters=obj_schema(
        {
            "input_task_id": {"type": "string"},
            "model_url": {"type": "string"},
            "model_path": {"type": "string"},
            "topology": {"type": "string", "enum": ["quad", "triangle"]},
            "target_polycount": {"type": "integer"},
            "decimation_mode": {
                "type": "integer",
                "enum": [1, 2, 3, 4],
                "description": "自适应减面档位；设置后忽略 target_polycount",
            },
            "target_formats": {
                "type": "array",
                "items": {"type": "string"},
            },
            "wait": {"type": "boolean", "default": False},
            "wait_timeout": {"type": "number"},
        },
    ),
    category="meshy",
    main_thread=False,
)
def meshy_remesh(
    input_task_id: str = "",
    model_url: str = "",
    model_path: str = "",
    topology: str = "quad",
    target_polycount: Optional[int] = None,
    decimation_mode: Optional[int] = None,
    target_formats: Optional[List[str]] = None,
    wait: bool = False,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    try:
        body: Dict[str, Any] = {}
        if (input_task_id or "").strip():
            body["input_task_id"] = input_task_id.strip()
        elif model_url or model_path:
            body["model_url"] = resolve_model_input(
                model_url=model_url, model_path=model_path
            )
        else:
            return ToolResult(
                ok=False, error="需要 input_task_id 或 model_url/model_path"
            )
        if topology:
            body["topology"] = topology
        if target_polycount is not None:
            body["target_polycount"] = int(target_polycount)
        if decimation_mode is not None:
            body["decimation_mode"] = int(decimation_mode)
        body["target_formats"] = _formats_or_default(target_formats)
        return _create_and_maybe_wait(
            "remesh", body, wait=wait, wait_timeout=wait_timeout
        )
    except Exception as e:
        return _err(e)


@tool(
    name="meshy_convert",
    description="Meshy 格式转换。input_task_id 或 model_url/path + target_formats（必填）。",
    parameters=obj_schema(
        {
            "target_formats": {
                "type": "array",
                "items": {"type": "string"},
                "description": "如 [\"fbx\",\"obj\",\"glb\"]",
            },
            "input_task_id": {"type": "string"},
            "model_url": {"type": "string"},
            "model_path": {"type": "string"},
            "wait": {"type": "boolean", "default": False},
            "wait_timeout": {"type": "number"},
        },
        required=["target_formats"],
    ),
    category="meshy",
    main_thread=False,
)
def meshy_convert(
    target_formats: List[str],
    input_task_id: str = "",
    model_url: str = "",
    model_path: str = "",
    wait: bool = False,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    try:
        if not target_formats:
            return ToolResult(ok=False, error="target_formats 不能为空")
        body: Dict[str, Any] = {"target_formats": list(target_formats)}
        if (input_task_id or "").strip():
            body["input_task_id"] = input_task_id.strip()
        elif model_url or model_path:
            body["model_url"] = resolve_model_input(
                model_url=model_url, model_path=model_path
            )
        else:
            return ToolResult(
                ok=False, error="需要 input_task_id 或 model_url/model_path"
            )
        return _create_and_maybe_wait(
            "convert", body, wait=wait, wait_timeout=wait_timeout
        )
    except Exception as e:
        return _err(e)


@tool(
    name="meshy_resize",
    description=(
        "Meshy 缩放模型到真实尺寸（米）。resize_height / resize_longest_side / auto_size 三选一。"
    ),
    parameters=obj_schema(
        {
            "input_task_id": {"type": "string"},
            "model_url": {"type": "string"},
            "model_path": {"type": "string"},
            "resize_height": {"type": "number"},
            "resize_longest_side": {"type": "number"},
            "auto_size": {"type": "boolean"},
            "origin_at": {"type": "string", "enum": ["bottom", "center"]},
            "wait": {"type": "boolean", "default": False},
            "wait_timeout": {"type": "number"},
        },
    ),
    category="meshy",
    main_thread=False,
)
def meshy_resize(
    input_task_id: str = "",
    model_url: str = "",
    model_path: str = "",
    resize_height: Optional[float] = None,
    resize_longest_side: Optional[float] = None,
    auto_size: Optional[bool] = None,
    origin_at: str = "",
    wait: bool = False,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    try:
        body: Dict[str, Any] = {}
        if (input_task_id or "").strip():
            body["input_task_id"] = input_task_id.strip()
        elif model_url or model_path:
            body["model_url"] = resolve_model_input(
                model_url=model_url, model_path=model_path
            )
        else:
            return ToolResult(
                ok=False, error="需要 input_task_id 或 model_url/model_path"
            )
        if resize_height is not None:
            body["resize_height"] = float(resize_height)
        if resize_longest_side is not None:
            body["resize_longest_side"] = float(resize_longest_side)
        if auto_size is not None:
            body["auto_size"] = bool(auto_size)
        if origin_at:
            body["origin_at"] = origin_at
        if not any(k in body for k in ("resize_height", "resize_longest_side", "auto_size")):
            return ToolResult(
                ok=False,
                error="需要 resize_height、resize_longest_side 或 auto_size 之一",
            )
        return _create_and_maybe_wait(
            "resize", body, wait=wait, wait_timeout=wait_timeout
        )
    except Exception as e:
        return _err(e)


@tool(
    name="meshy_uv_unwrap",
    description="Meshy UV 展开。input_task_id 或 model_url/path。",
    parameters=obj_schema(
        {
            "input_task_id": {"type": "string"},
            "model_url": {"type": "string"},
            "model_path": {"type": "string"},
            "wait": {"type": "boolean", "default": False},
            "wait_timeout": {"type": "number"},
        },
    ),
    category="meshy",
    main_thread=False,
)
def meshy_uv_unwrap(
    input_task_id: str = "",
    model_url: str = "",
    model_path: str = "",
    wait: bool = False,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    try:
        body: Dict[str, Any] = {}
        if (input_task_id or "").strip():
            body["input_task_id"] = input_task_id.strip()
        elif model_url or model_path:
            body["model_url"] = resolve_model_input(
                model_url=model_url, model_path=model_path
            )
        else:
            return ToolResult(
                ok=False, error="需要 input_task_id 或 model_url/model_path"
            )
        return _create_and_maybe_wait(
            "uv-unwrap", body, wait=wait, wait_timeout=wait_timeout
        )
    except Exception as e:
        return _err(e)


@tool(
    name="meshy_rig",
    description=(
        "Meshy 自动绑骨（清晰人形/四足，需有贴图）。input_task_id 或 GLB model_url/path。"
        "面数>30万需先 remesh。animation_type: biped|quadruped。"
    ),
    parameters=obj_schema(
        {
            "input_task_id": {"type": "string"},
            "model_url": {"type": "string"},
            "model_path": {"type": "string"},
            "height_meters": {"type": "number", "default": 1.7},
            "animation_type": {
                "type": "string",
                "enum": ["biped", "quadruped"],
            },
            "wait": {"type": "boolean", "default": False},
            "wait_timeout": {"type": "number"},
        },
    ),
    category="meshy",
    main_thread=False,
)
def meshy_rig(
    input_task_id: str = "",
    model_url: str = "",
    model_path: str = "",
    height_meters: float = 1.7,
    animation_type: str = "",
    wait: bool = False,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    try:
        body: Dict[str, Any] = {"height_meters": float(height_meters or 1.7)}
        if (input_task_id or "").strip():
            body["input_task_id"] = input_task_id.strip()
        elif model_url or model_path:
            body["model_url"] = resolve_model_input(
                model_url=model_url, model_path=model_path
            )
        else:
            return ToolResult(
                ok=False, error="需要 input_task_id 或 model_url/model_path"
            )
        if animation_type:
            body["animation_type"] = animation_type
        return _create_and_maybe_wait(
            "rigging", body, wait=wait, wait_timeout=wait_timeout
        )
    except Exception as e:
        return _err(e)


@tool(
    name="meshy_animate",
    description=(
        "Meshy 给已绑骨角色套动画库动作。需 rig_task_id，以及 action_id 或 action_ids。"
        "可用 meshy_list_animations 查看动作库。"
    ),
    parameters=obj_schema(
        {
            "rig_task_id": {"type": "string"},
            "action_id": {"type": "integer"},
            "action_ids": {"type": "array", "items": {"type": "integer"}},
            "wait": {"type": "boolean", "default": False},
            "wait_timeout": {"type": "number"},
        },
        required=["rig_task_id"],
    ),
    category="meshy",
    main_thread=False,
)
def meshy_animate(
    rig_task_id: str,
    action_id: Optional[int] = None,
    action_ids: Optional[List[int]] = None,
    wait: bool = False,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    try:
        body: Dict[str, Any] = {"rig_task_id": (rig_task_id or "").strip()}
        if not body["rig_task_id"]:
            return ToolResult(ok=False, error="rig_task_id 不能为空")
        if action_ids:
            body["action_ids"] = [int(x) for x in action_ids]
        elif action_id is not None:
            body["action_id"] = int(action_id)
        else:
            return ToolResult(ok=False, error="需要 action_id 或 action_ids")
        return _create_and_maybe_wait(
            "animations", body, wait=wait, wait_timeout=wait_timeout
        )
    except Exception as e:
        return _err(e)


@tool(
    name="meshy_list_animations",
    description="列出 Meshy 动画库（供 meshy_animate 的 action_id 使用）。",
    parameters=obj_schema({}),
    category="meshy",
    main_thread=False,
)
def meshy_list_animations() -> ToolResult:
    try:
        data = _client().list_animations()
        return ToolResult(ok=True, data=data, message="已获取 Meshy 动画库")
    except Exception as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Task lifecycle / download / import
# ---------------------------------------------------------------------------


@tool(
    name="meshy_get_task",
    description=(
        "查询 Meshy 任务状态与结果 URL。"
        f"kind 可选: {', '.join(_KIND_ENUM)}。"
    ),
    parameters=obj_schema(
        {
            "kind": {"type": "string", "enum": _KIND_ENUM},
            "task_id": {"type": "string"},
        },
        required=["kind", "task_id"],
    ),
    category="meshy",
    main_thread=False,
)
def meshy_get_task(kind: str, task_id: str) -> ToolResult:
    try:
        task, _ = _client().get(kind, task_id)
        summary = summarize_task(task)
        status = summary.get("status")
        return ToolResult(
            ok=True,
            data={"kind": kind, "task": summary},
            message=f"任务 {task_id} 状态={status} progress={summary.get('progress')}",
        )
    except Exception as e:
        return _err(e)


@tool(
    name="meshy_wait_task",
    description=(
        "轮询 Meshy 任务直至 SUCCEEDED/FAILED（在工作线程执行，不卡 Maya 主线程）。"
        "成功后返回 model_urls 等，可再 meshy_import_to_maya。"
    ),
    parameters=obj_schema(
        {
            "kind": {"type": "string", "enum": _KIND_ENUM},
            "task_id": {"type": "string"},
            "timeout": {
                "type": "number",
                "description": "秒；默认用配置 meshy.wait_timeout",
            },
            "poll_interval": {"type": "number"},
        },
        required=["kind", "task_id"],
    ),
    category="meshy",
    main_thread=False,
)
def meshy_wait_task(
    kind: str,
    task_id: str,
    timeout: Optional[float] = None,
    poll_interval: Optional[float] = None,
) -> ToolResult:
    try:
        report_tool_progress(
            kind=kind,
            task_id=task_id,
            status="PENDING",
            progress=0,
            message=f"Meshy {kind} 等待中…",
        )
        task = _client().wait(
            kind,
            task_id,
            timeout=timeout,
            poll_interval=poll_interval,
            on_progress=_wait_progress(kind, task_id),
        )
        return ToolResult(
            ok=True,
            data={"kind": kind, "task_id": task_id, "task": summarize_task(task)},
            message=f"Meshy 任务已成功：{task_id}",
        )
    except Exception as e:
        return _err(e)


@tool(
    name="meshy_download_model",
    description=(
        "下载已成功任务的模型文件到本地。可传 task 查询参数，或直接 model_url。"
        "prefer_format 默认 fbx。"
    ),
    parameters=obj_schema(
        {
            "kind": {"type": "string", "enum": _KIND_ENUM},
            "task_id": {"type": "string"},
            "model_url": {"type": "string", "description": "若已有签名 URL 可直接下载"},
            "prefer_format": {
                "type": "string",
                "description": "fbx/glb/obj 等",
            },
            "filename": {"type": "string"},
            "output_dir": {"type": "string"},
        },
    ),
    category="meshy",
    main_thread=False,
)
def meshy_download_model(
    kind: str = "",
    task_id: str = "",
    model_url: str = "",
    prefer_format: str = "fbx",
    filename: str = "",
    output_dir: str = "",
) -> ToolResult:
    try:
        client = _client()
        fmt = (prefer_format or "fbx").strip().lower()
        url = (model_url or "").strip()
        tid = (task_id or "").strip() or "model"
        if not url:
            if not kind or not task_id:
                return ToolResult(
                    ok=False, error="需要 model_url，或同时提供 kind + task_id"
                )
            task, _ = client.get(kind, task_id)
            if str(task.get("status")) != "SUCCEEDED":
                return ToolResult(
                    ok=False,
                    error=f"任务尚未成功（status={task.get('status')}）",
                    data=summarize_task(task),
                )
            fmt, url = pick_model_url(task, prefer=[fmt, "fbx", "glb", "obj"])
            tid = str(task.get("id") or tid)

        out_dir = Path(output_dir) if output_dir else download_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        name = (filename or "").strip() or f"meshy_{tid}.{fmt}"
        if "." not in name:
            name = f"{name}.{fmt}"
        dest = out_dir / name
        client.download(url, dest)
        return ToolResult(
            ok=True,
            data={"path": str(dest), "format": fmt, "task_id": tid},
            message=f"已下载: {dest}",
        )
    except Exception as e:
        return _err(e)


def _safe_delete_nodes(nodes: List[str]) -> None:
    import maya.cmds as cmds

    for n in nodes:
        if not n or not cmds.objExists(n):
            continue
        try:
            cmds.delete(n)
        except Exception:
            pass


def _file_texture_path(file_node: str) -> str:
    import maya.cmds as cmds

    for attr in ("computedFileTextureNamePattern", "fileTextureName"):
        try:
            val = cmds.getAttr(f"{file_node}.{attr}")
            if val:
                return str(val)
        except Exception:
            continue
    return ""


def _classify_meshy_map(file_node: str, path: str = "") -> Optional[str]:
    """Classify a file node as base_color / metallic / roughness / normal."""
    name = (file_node or "").lower()
    path_l = (path or _file_texture_path(file_node) or "").lower().replace("\\", "/")
    blob = f"{name} {path_l}"
    if any(k in blob for k in ("metallic", "metalness", "_metal")):
        return "metallic"
    if any(k in blob for k in ("roughness", "rough")):
        return "roughness"
    if any(k in blob for k in ("normal", "nrm", "nor_")):
        return "normal"
    if any(
        k in blob
        for k in ("base_color", "basecolor", "albedo", "diffuse", "base colour")
    ):
        return "base_color"
    # Meshy default: texture_0.png (no suffix) = base color
    leaf = path_l.rsplit("/", 1)[-1]
    if leaf.startswith("texture_") and leaf.endswith((".png", ".jpg", ".jpeg", ".tga", ".tif", ".tiff")):
        stem = leaf.rsplit(".", 1)[0]
        if "_" not in stem[len("texture_") :]:  # texture_0, texture_1
            return "base_color"
    return None


def _collect_file_nodes_from_shader(shader: str) -> List[str]:
    import maya.cmds as cmds

    found: List[str] = []
    seen = set()
    hist = cmds.listHistory(shader, pruneDagObjects=True) or []
    for n in hist:
        if n in seen or not cmds.objExists(n):
            continue
        seen.add(n)
        try:
            if cmds.nodeType(n) == "file":
                found.append(n)
        except Exception:
            continue
    return found


def _meshes_using_shader(shader: str) -> List[str]:
    """Return mesh shape long names shaded by this shader."""
    import maya.cmds as cmds

    sgs = cmds.listConnections(shader, type="shadingEngine") or []
    meshes: List[str] = []
    for sg in sgs:
        try:
            members = cmds.sets(sg, query=True) or []
        except Exception:
            members = []
        for m in members:
            if not cmds.objExists(m):
                continue
            # Face assign like Mesh.f[0:10] → Mesh
            dag = m.split(".")[0]
            shapes = []
            if cmds.nodeType(dag) == "mesh":
                shapes = [dag]
            else:
                shapes = cmds.listRelatives(dag, shapes=True, type="mesh", fullPath=True) or []
            for s in shapes:
                long_name = cmds.ls(s, long=True) or [s]
                meshes.extend(long_name)
    # unique preserve order
    out: List[str] = []
    seen = set()
    for m in meshes:
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def _shader_has_pbr_slots(shader: str) -> bool:
    import maya.cmds as cmds

    if not shader or not cmds.objExists(shader):
        return False
    for attr in ("baseColor", "metalness", "specularRoughness"):
        if not cmds.attributeQuery(attr, node=shader, exists=True):
            return False
    return True


def _force_connect(src: str, dst: str) -> None:
    import maya.cmds as cmds

    try:
        if cmds.isConnected(src, dst):
            return
    except Exception:
        pass
    incoming = cmds.listConnections(dst, s=True, d=False, p=True) or []
    for plug in incoming:
        try:
            cmds.disconnectAttr(plug, dst)
        except Exception:
            pass
    cmds.connectAttr(src, dst, force=True)


def _ensure_place2d(file_node: str) -> str:
    import maya.cmds as cmds

    existing = cmds.listConnections(f"{file_node}.uvCoord", s=True, d=False) or []
    if existing:
        return existing[0]
    place = cmds.shadingNode("place2dTexture", asUtility=True, name=f"{file_node}_place")
    for attr in (
        "coverage",
        "translateFrame",
        "rotateFrame",
        "mirrorU",
        "mirrorV",
        "stagger",
        "wrapU",
        "wrapV",
        "repeatUV",
        "offset",
        "rotateUV",
        "noiseUV",
        "vertexUvOne",
        "vertexUvTwo",
        "vertexUvThree",
        "vertexCameraOne",
    ):
        if cmds.attributeQuery(attr, node=place, exists=True) and cmds.attributeQuery(
            attr, node=file_node, exists=True
        ):
            try:
                cmds.connectAttr(f"{place}.{attr}", f"{file_node}.{attr}", force=True)
            except Exception:
                pass
    cmds.connectAttr(f"{place}.outUV", f"{file_node}.uvCoord", force=True)
    try:
        cmds.connectAttr(f"{place}.outUvFilterSize", f"{file_node}.uvFilterSize", force=True)
    except Exception:
        pass
    return place


def _configure_file_node(file_node: str, *, colorspace: str, data_map: bool) -> None:
    """Force OCIO/color-space and sampling so PBR maps keep authored values."""
    import maya.cmds as cmds

    _ensure_place2d(file_node)
    try:
        cmds.setAttr(f"{file_node}.ignoreColorSpaceFileRules", 1)
    except Exception:
        pass
    try:
        cmds.setAttr(f"{file_node}.colorSpace", colorspace, type="string")
    except Exception:
        pass
    # Meshy grayscale maps store data in RGB; PNG alpha is typically opaque 1.0.
    # Never use alphaIsLuminance=1 as a substitute for reading outColorR.
    try:
        cmds.setAttr(f"{file_node}.alphaIsLuminance", 0)
    except Exception:
        pass
    try:
        cmds.setAttr(f"{file_node}.alphaGain", 1.0)
        cmds.setAttr(f"{file_node}.alphaOffset", 0.0)
    except Exception:
        pass
    if data_map:
        try:
            cmds.setAttr(f"{file_node}.filterType", 0)  # Off — keep texel values
        except Exception:
            pass
        try:
            cmds.setAttr(f"{file_node}.defaultColor", 0.0, 0.0, 0.0, type="double3")
        except Exception:
            pass


def _connect_scalar_map(file_node: str, dest_plug: str) -> str:
    """
    Wire Meshy metallic/roughness maps.

    Meshy ships these as grayscale PNG (PIL mode ``L``). Maya expands them to
    RGB; the authored value lives in ``outColorR``. ``outAlpha`` is usually
    opaque 1.0 — connecting it makes metalness/roughness stuck at 1.
    """
    _configure_file_node(file_node, colorspace="Raw", data_map=True)
    src = f"{file_node}.outColorR"
    _force_connect(src, dest_plug)
    return src


def _connect_normal_map(file_node: str, shader: str) -> str:
    """
    Wire Meshy tangent-space normal map (RGB).

    Verified against Test06 / Test07 sessions:
    - ``aiNormalMap`` → viewport shows black holes / checker (VP2 does not eval it)
    - ``bump2d.bumpValue`` only accepts float; ``outAlpha`` drops XY → blotches
    - ``file.outColor → standardSurface.normalCamera`` keeps full RGB and works
      in both Viewport 2.0 and Arnold for these assets
    - Normal map MUST be Raw (FBX import leaves sRGB → tile blotches)
    """
    _configure_file_node(file_node, colorspace="Raw", data_map=True)
    dest = f"{shader}.normalCamera"
    _force_connect(f"{file_node}.outColor", dest)
    return file_node


def _enable_viewport_textures() -> None:
    import maya.cmds as cmds

    for panel in cmds.getPanel(type="modelPanel") or []:
        try:
            cmds.modelEditor(panel, edit=True, displayTextures=True)
        except Exception:
            pass


def _rebuild_one_meshy_material(
    old_shader: str,
    maps: Dict[str, str],
    meshes: List[str],
) -> Optional[Dict[str, Any]]:
    """Replace Phong-style Meshy FBX material with standardSurface PBR."""
    import maya.cmds as cmds

    if not maps.get("base_color") and not (maps.get("metallic") or maps.get("roughness")):
        return None

    available = set(cmds.listNodeTypes("shader") or [])
    shader_type = "standardSurface" if "standardSurface" in available else "lambert"
    if shader_type == "lambert":
        return None

    base_name = (old_shader or "meshy_mat").split(":")[-1]
    base_name = base_name.replace("MaterialFBXASC046", "meshy_mat_")
    if not base_name.startswith("meshy_"):
        base_name = f"meshy_{base_name}"
    shader = cmds.shadingNode(shader_type, asShader=True, name=f"{base_name}_PBR")
    sg_name = f"{shader}SG"
    if cmds.objExists(sg_name):
        sg_name = f"{shader}_SG"
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=sg_name)
    cmds.connectAttr(f"{shader}.outColor", f"{sg}.surfaceShader", force=True)

    wired: Dict[str, Any] = {"shader": shader, "shading_group": sg, "type": shader_type}

    try:
        cmds.setAttr(f"{shader}.base", 1.0)
    except Exception:
        pass
    try:
        cmds.setAttr(f"{shader}.specular", 1.0)
    except Exception:
        pass

    base = maps.get("base_color")
    if base and cmds.objExists(base):
        _configure_file_node(base, colorspace="sRGB", data_map=False)
        _force_connect(f"{base}.outColor", f"{shader}.baseColor")
        wired["base_color"] = base
        wired["base_color_plug"] = f"{base}.outColor"

    metal = maps.get("metallic")
    if metal and cmds.objExists(metal) and cmds.attributeQuery("metalness", node=shader, exists=True):
        wired["metallic_plug"] = _connect_scalar_map(metal, f"{shader}.metalness")
        wired["metallic"] = metal

    rough = maps.get("roughness")
    if rough and cmds.objExists(rough) and cmds.attributeQuery(
        "specularRoughness", node=shader, exists=True
    ):
        wired["roughness_plug"] = _connect_scalar_map(rough, f"{shader}.specularRoughness")
        wired["roughness"] = rough

    normal = maps.get("normal")
    if normal and cmds.objExists(normal) and cmds.attributeQuery(
        "normalCamera", node=shader, exists=True
    ):
        wired["normal_node"] = _connect_normal_map(normal, shader)
        wired["normal"] = normal

    # Assign meshes to new SG
    assigned = []
    for mesh in meshes:
        if not cmds.objExists(mesh):
            continue
        try:
            cmds.sets(mesh, edit=True, forceElement=sg)
            assigned.append(mesh)
        except Exception:
            # try parent transform
            try:
                parent = (cmds.listRelatives(mesh, parent=True, fullPath=True) or [None])[0]
                if parent:
                    cmds.sets(parent, edit=True, forceElement=sg)
                    assigned.append(parent)
            except Exception:
                pass
    wired["assigned"] = assigned

    keep_files = {v for v in maps.values() if v}
    old_sg = cmds.listConnections(old_shader, type="shadingEngine") or []
    junk = []
    for n in cmds.listHistory(old_shader, pruneDagObjects=True) or []:
        if n in keep_files or n == old_shader:
            continue
        try:
            nt = cmds.nodeType(n)
        except Exception:
            continue
        if nt in ("bump2d", "setRange", "aiNormalMap", "aiRange"):
            junk.append(n)
    junk.append(old_shader)
    junk.extend(old_sg)
    _safe_delete_nodes(junk)
    return wired


def _create_file_node_for_path(path: str, name: str) -> str:
    import maya.cmds as cmds

    node = cmds.shadingNode("file", asTexture=True, isColorManaged=True, name=name)
    cmds.setAttr(f"{node}.fileTextureName", str(path).replace("\\", "/"), type="string")
    _ensure_place2d(node)
    return node


def _maps_from_fbm_dir(fbm_dir: Path) -> Dict[str, str]:
    """Create file nodes for Meshy texture_0*.png sitting next to the FBX."""
    import maya.cmds as cmds

    maps: Dict[str, str] = {}
    if not fbm_dir.is_dir():
        return maps
    files = sorted(fbm_dir.iterdir(), key=lambda p: p.name.lower())
    for p in files:
        if p.suffix.lower() not in {".png", ".jpg", ".jpeg", ".tga", ".tif", ".tiff"}:
            continue
        role = _classify_meshy_map("", str(p))
        if not role or role in maps:
            continue
        existing = None
        for fn in cmds.ls(type="file") or []:
            if _file_texture_path(fn).replace("\\", "/").lower() == str(p).replace("\\", "/").lower():
                existing = fn
                break
        maps[role] = existing or _create_file_node_for_path(p, f"meshy_{role}")
    return maps


def _rebuild_meshy_pbr_materials(
    *,
    before_meshes: Optional[set] = None,
    before_shaders: Optional[set] = None,
    fbx_path: str = "",
) -> Dict[str, Any]:
    """
    After FBX import, Maya often demotes Meshy PBR to Phong with wrong map wiring.
    Detect Meshy texture sets and rebuild as standardSurface.
    """
    import maya.cmds as cmds

    before_meshes = before_meshes or set()
    before_shaders = before_shaders or set()
    after_meshes = set(cmds.ls(type="mesh", long=True) or [])
    new_meshes = after_meshes - before_meshes
    if not new_meshes:
        # Fallback: all meshes that look Meshy-shaded
        new_meshes = after_meshes

    # Candidate shaders: newly created, or assigned to new meshes, and not already PBR-complete
    candidates: List[str] = []
    seen = set()

    after_shaders = set(cmds.ls(materials=True) or [])
    for sh in after_shaders - before_shaders:
        if sh not in seen:
            seen.add(sh)
            candidates.append(sh)

    for mesh in new_meshes:
        sgs = cmds.listConnections(mesh, type="shadingEngine") or []
        for sg in sgs:
            shaders = cmds.listConnections(f"{sg}.surfaceShader") or []
            for sh in shaders:
                if sh not in seen:
                    seen.add(sh)
                    candidates.append(sh)

    rebuilt: List[Dict[str, Any]] = []
    skipped: List[str] = []

    for shader in candidates:
        if not cmds.objExists(shader):
            continue
        try:
            stype = cmds.nodeType(shader)
        except Exception:
            continue
        # Skip default / already good PBR
        if shader in ("lambert1", "standardSurface1", "particleCloud1", "shaderGlow1"):
            continue

        files = _collect_file_nodes_from_shader(shader)
        maps: Dict[str, str] = {}
        for fnode in files:
            role = _classify_meshy_map(fnode)
            if role and role not in maps:
                maps[role] = fnode

        # Fill missing roles from the same .fbm folder (sibling textures)
        fbm_roots = set()
        for fnode in files:
            path = _file_texture_path(fnode).replace("\\", "/")
            low = path.lower()
            idx = low.find(".fbm")
            if idx >= 0:
                fbm_roots.add(path[: idx + 4])
        if fbm_roots and len(maps) < 4:
            for fnode in cmds.ls(type="file") or []:
                path = _file_texture_path(fnode).replace("\\", "/")
                if not any(path.startswith(root) or path.lower().startswith(root.lower()) for root in fbm_roots):
                    continue
                role = _classify_meshy_map(fnode, path)
                if role and role not in maps:
                    maps[role] = fnode

        if len(maps) < 2 and fbx_path:
            fbm = Path(fbx_path).with_suffix(".fbm")
            extra = _maps_from_fbm_dir(fbm)
            for role, node in extra.items():
                maps.setdefault(role, node)

        is_legacy = stype in ("phong", "phongE", "blinn", "lambert")
        already_pbr = _shader_has_pbr_slots(shader)
        needs = False
        if maps and is_legacy:
            needs = True
        elif maps and already_pbr:
            try:
                metal_src = cmds.listConnections(
                    f"{shader}.metalness", source=True, plugs=True
                ) or []
            except Exception:
                metal_src = []
            try:
                rough_src = cmds.listConnections(
                    f"{shader}.specularRoughness", source=True, plugs=True
                ) or []
            except Exception:
                rough_src = []
            try:
                nrm_src_nodes = (
                    cmds.listConnections(f"{shader}.normalCamera", source=True) or []
                )
                nrm_types = [
                    cmds.nodeType(n) for n in nrm_src_nodes if cmds.objExists(n)
                ]
            except Exception:
                nrm_types = []
            # Stuck at 1.0 when wired through opaque PNG alpha
            if maps.get("metallic") and (
                not metal_src or any(".outAlpha" in s for s in metal_src)
            ):
                needs = True
            if maps.get("roughness") and (
                not rough_src or any(".outAlpha" in s for s in rough_src)
            ):
                needs = True
            # Meshy normals must be file.outColor → normalCamera (Raw).
            # bump2d/aiNormalMap both produced blotches in Test06/07.
            if maps.get("normal") and (
                not nrm_types
                or any(t in ("bump2d", "aiNormalMap") for t in nrm_types)
            ):
                needs = True
            # FBX often leaves data maps in sRGB
            for role in ("metallic", "roughness", "normal"):
                fnode = maps.get(role)
                if not fnode or not cmds.objExists(fnode):
                    continue
                try:
                    cs = (cmds.getAttr(f"{fnode}.colorSpace") or "").lower()
                except Exception:
                    cs = ""
                if cs and cs not in ("raw", "utility - raw", "scene-linear rec.709-srgb"):
                    if "raw" not in cs:
                        needs = True
        if not needs:
            skipped.append(shader)
            continue

        meshes = _meshes_using_shader(shader)
        if new_meshes:
            meshes = [m for m in meshes if m in new_meshes] or meshes
        if not meshes:
            skipped.append(shader)
            continue

        try:
            info = _rebuild_one_meshy_material(shader, maps, meshes)
        except Exception:
            log.exception("rebuild PBR failed for %s", shader)
            info = None
        if info:
            rebuilt.append(info)

    _enable_viewport_textures()
    return {
        "rebuilt": rebuilt,
        "skipped": skipped,
        "new_mesh_count": len(new_meshes),
    }


def _import_path_into_maya(
    path: str,
    namespace: str = "",
    *,
    rebuild_pbr: bool = True,
) -> ToolResult:
    if not in_maya():
        return ToolResult(ok=False, error="未在 Maya 中运行，无法导入")
    import maya.cmds as cmds

    p = Path(path)
    if not p.is_file():
        return ToolResult(ok=False, error=f"文件不存在: {path}")
    suffix = p.suffix.lower()
    kwargs: Dict[str, Any] = {
        "i": True,
        "ignoreVersion": True,
        "mergeNamespacesOnClash": False,
        "rpr": "meshy",
    }
    if namespace:
        kwargs["namespace"] = namespace

    before_meshes = set(cmds.ls(type="mesh", long=True) or [])
    before_shaders = set(cmds.ls(materials=True) or [])

    if suffix == ".fbx":
        if not ensure_plugin("fbxmaya"):
            return ToolResult(ok=False, error="无法加载 fbxmaya 插件")
        kwargs.update({"type": "FBX", "options": "fbx"})
        try:
            import maya.mel as mel

            for cmd in (
                'FBXImportMode -v add',
                'FBXImportMergeAnimationLayers -v false',
                'FBXImportLights -v false',
                'FBXImportCameras -v false',
                'FBXImportGenerateLog -v false',
            ):
                try:
                    mel.eval(cmd)
                except Exception:
                    pass
        except Exception:
            pass
        nodes = cmds.file(str(p), **kwargs)
        data: Dict[str, Any] = {"imported": nodes, "path": str(p)}
        msg = f"已导入 FBX: {p}"
        if rebuild_pbr:
            try:
                pbr = _rebuild_meshy_pbr_materials(
                    before_meshes=before_meshes,
                    before_shaders=before_shaders,
                    fbx_path=str(p),
                )
                data["pbr"] = pbr
                n = len(pbr.get("rebuilt") or [])
                if n:
                    names = [r.get("shader") for r in pbr["rebuilt"] if r.get("shader")]
                    msg += f"；已自动重建 PBR（standardSurface）×{n}: {', '.join(names)}"
                else:
                    msg += "；未检测到需重建的 Meshy Phong 材质"
            except Exception as e:
                log.exception("PBR rebuild after FBX import failed")
                data["pbr_error"] = str(e)
                msg += f"；PBR 重建失败（几何已导入）: {e}"
        return ToolResult(ok=True, data=data, message=msg)

    if suffix == ".obj":
        ensure_plugin("objExport")
        kwargs.update({"type": "OBJ", "options": "mo=1"})
        nodes = cmds.file(str(p), **kwargs)
        return ToolResult(ok=True, data=nodes, message=f"已导入 OBJ: {p}")

    if suffix in (".glb", ".gltf"):
        # Maya 通常无原生 glTF；提示用户先 convert/remesh 到 fbx
        return ToolResult(
            ok=False,
            error=(
                f"Maya 无法直接导入 {suffix}。请先用 meshy_convert / meshy_remesh "
                "将 target_formats 设为 [\"fbx\"] 后再导入，或改用 prefer_format=fbx。"
            ),
            data={"path": str(p)},
        )

    # Generic attempt
    try:
        nodes = cmds.file(str(p), **kwargs)
        return ToolResult(ok=True, data=nodes, message=f"已尝试导入: {p}")
    except Exception as e:
        return ToolResult(ok=False, error=f"导入失败: {e}", data={"path": str(p)})


@tool(
    name="meshy_import_to_maya",
    description=(
        "将 Meshy 成功任务的模型下载并导入当前 Maya 场景（优先 FBX）。"
        "FBX 导入后默认自动把 Phong 降级材质重建为 standardSurface PBR："
        "baseColor=sRGB；metallic/roughness（灰度 L）用 outColorR→metalness/specularRoughness；"
        "法线用 file.outColor→normalCamera（Raw；不用 bump2d/aiNormalMap）。"
        "可传 kind+task_id，或已下载的 file_path。下载在工作线程，导入走主线程。"
    ),
    parameters=obj_schema(
        {
            "kind": {"type": "string", "enum": _KIND_ENUM},
            "task_id": {"type": "string"},
            "file_path": {"type": "string", "description": "已有本地文件则直接导入"},
            "prefer_format": {"type": "string", "default": "fbx"},
            "namespace": {"type": "string"},
            "output_dir": {"type": "string"},
            "rebuild_pbr": {
                "type": "boolean",
                "default": True,
                "description": "FBX 导入后是否自动重建 standardSurface PBR（默认 true）",
            },
        },
    ),
    category="meshy",
    main_thread=False,
)
def meshy_import_to_maya(
    kind: str = "",
    task_id: str = "",
    file_path: str = "",
    prefer_format: str = "fbx",
    namespace: str = "",
    output_dir: str = "",
    rebuild_pbr: bool = True,
) -> ToolResult:
    try:
        local = (file_path or "").strip()
        if not local:
            dl = meshy_download_model(
                kind=kind,
                task_id=task_id,
                prefer_format=prefer_format or "fbx",
                output_dir=output_dir,
            )
            if not dl.ok:
                return dl
            local = str((dl.data or {}).get("path") or "")
            if not local:
                return ToolResult(ok=False, error="下载成功但未返回路径")

        return run_on_main_thread(
            lambda: _import_path_into_maya(
                local, namespace=namespace, rebuild_pbr=bool(rebuild_pbr)
            )
        )
    except Exception as e:
        return _err(e)


@tool(
    name="meshy_balance",
    description="查询 Meshy 账户积分余额。配置 API Key 后可用来测试连接。",
    parameters=obj_schema({}),
    category="meshy",
    main_thread=False,
)
def meshy_balance() -> ToolResult:
    try:
        data = _client().balance()
        return ToolResult(ok=True, data=data, message="已获取 Meshy 余额")
    except Exception as e:
        return _err(e)
