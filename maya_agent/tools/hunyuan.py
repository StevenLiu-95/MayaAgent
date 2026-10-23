"""Maya Agent tools wrapping Tencent Hunyuan 3D (ai3d) API."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from maya_agent.core.tool_progress import report_tool_progress
from maya_agent.tools.hunyuan_client import (
    JOB_KINDS,
    MOTION_PRESETS,
    PROFILE_TEMPLATES,
    HunyuanClient,
    HunyuanError,
    download_dir,
    drop_none,
    estimate_status_progress,
    normalize_job_progress,
    pick_result_url,
    resolve_image_fields,
    resolve_profile_image,
    summarize_task,
)
from maya_agent.tools.registry import ToolResult, obj_schema, tool
from maya_agent.utils.logger import get_logger
from maya_agent.utils.maya_compat import run_on_main_thread

log = get_logger("maya_agent.hunyuan_tools")

_KIND_ENUM = sorted(JOB_KINDS)

_FILE3D_NOTE = (
    "3D 输入只接受公网 file_url，或 input_job_id+input_job_kind 串联上一任务 "
    "ResultFile3Ds.Url；不支持本地 FBX/GLB 直传。"
)


def _client() -> HunyuanClient:
    return HunyuanClient()


def _err(exc: Exception) -> ToolResult:
    if isinstance(exc, HunyuanError):
        return ToolResult(
            ok=False,
            error=str(exc),
            data={"error_code": getattr(exc, "error_code", ""), "payload": exc.payload},
        )
    log.exception("hunyuan tool failed")
    return ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}")


def _wait_progress(kind: str, job_id: str):
    def _on(info: Dict[str, Any]) -> None:
        status = str(info.get("status") or "")
        progress = normalize_job_progress(info.get("progress"))
        if progress is None:
            progress = estimate_status_progress(status)
        pct = f" {progress}%" if progress is not None else ""
        report_tool_progress(
            kind=kind,
            task_id=job_id,
            status=status,
            progress=progress,
            message=f"混元 {kind} {status}{pct}".strip(),
        )

    return _on


def _create_and_maybe_wait(
    kind: str,
    action: str,
    body: Dict[str, Any],
    *,
    wait: bool = False,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    client = _client()
    job_id = client.submit(action, drop_none(body))
    if not wait:
        return ToolResult(
            ok=True,
            data={"kind": kind, "job_id": job_id, "status": "CREATED"},
            message=(
                f"已创建混元任务 {kind}：{job_id}。"
                f"请调用 hunyuan_wait_job(kind={kind!r}, job_id=...) 等待完成，"
                "再用 hunyuan_import_to_maya 导入 Maya。"
            ),
        )
    # Hunyuan has no real Progress field — start at WAIT estimate, not 0%.
    report_tool_progress(
        kind=kind,
        task_id=job_id,
        status="WAIT",
        progress=estimate_status_progress("WAIT"),
        message=f"混元 {kind} 已创建，等待中…",
    )
    task = client.wait(
        kind,
        job_id,
        timeout=wait_timeout,
        on_progress=_wait_progress(kind, job_id),
    )
    report_tool_progress(
        kind=kind,
        task_id=job_id,
        status="DONE",
        progress=100,
        message=f"混元 {kind} 已完成",
    )
    return ToolResult(
        ok=True,
        data={"kind": kind, "job_id": job_id, "task": summarize_task(task)},
        message=f"混元任务已完成：{job_id}",
    )


def _pro_common_params() -> Dict[str, Any]:
    return {
        "model": {
            "type": "string",
            "description": "生成模型版本：3.0 / 3.1（3.1 时 LowPoly 不可用）",
        },
        "enable_pbr": {"type": "boolean", "default": False},
        "face_count": {
            "type": "integer",
            "description": "面数 3000–1500000；LowPoly 时不生效",
        },
        "generate_type": {
            "type": "string",
            "enum": ["Normal", "LowPoly", "Geometry", "Sketch"],
        },
        "polygon_type": {
            "type": "string",
            "enum": ["triangle", "quadrilateral"],
            "description": "仅 LowPoly 生效",
        },
        "result_format": {
            "type": "string",
            "description": "额外格式：STL / USDZ / FBX（默认仍含 obj/glb）",
        },
        "wait": {"type": "boolean", "default": False},
        "wait_timeout": {"type": "number"},
    }


def _apply_pro_options(
    body: Dict[str, Any],
    *,
    model: str = "",
    enable_pbr: Optional[bool] = None,
    face_count: Optional[int] = None,
    generate_type: str = "",
    polygon_type: str = "",
    result_format: str = "",
) -> None:
    if model:
        body["Model"] = model
    if enable_pbr is not None:
        body["EnablePBR"] = bool(enable_pbr)
    if face_count is not None:
        body["FaceCount"] = int(face_count)
    if generate_type:
        body["GenerateType"] = generate_type
    if polygon_type:
        body["PolygonType"] = polygon_type
    if result_format:
        body["ResultFormat"] = result_format.upper()


def _file3d_params(*, prefer_note: str = "") -> Dict[str, Any]:
    return {
        "file_url": {
            "type": "string",
            "description": "公网 3D 文件 URL（http/https）" + prefer_note,
        },
        "file_type": {
            "type": "string",
            "description": "FBX / GLB / OBJ 等；省略则从 URL 猜测",
        },
        "input_job_id": {
            "type": "string",
            "description": "上一任务 JobId，取其 ResultFile3Ds.Url",
        },
        "input_job_kind": {
            "type": "string",
            "enum": _KIND_ENUM,
            "description": "上一任务类型（与 input_job_id 联用）",
        },
    }


# ---------------------------------------------------------------------------
# Generation — Pro
# ---------------------------------------------------------------------------


@tool(
    name="hunyuan_text_to_3d_pro",
    description=(
        "混元生3D专业版·文生3D（SubmitHunyuanTo3DProJob）。"
        "默认只返回 job_id；wait=true 则轮询至 DONE。"
        "完成后 hunyuan_import_to_maya(kind='pro', job_id=...)。"
    ),
    parameters=obj_schema(
        {
            "prompt": {"type": "string", "description": "中文正向提示词，最多 1024 字"},
            **_pro_common_params(),
        },
        required=["prompt"],
    ),
    category="hunyuan",
    main_thread=False,
)
def hunyuan_text_to_3d_pro(
    prompt: str,
    model: str = "",
    enable_pbr: Optional[bool] = None,
    face_count: Optional[int] = None,
    generate_type: str = "",
    polygon_type: str = "",
    result_format: str = "",
    wait: bool = False,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    try:
        body: Dict[str, Any] = {"Prompt": (prompt or "").strip()}
        if not body["Prompt"]:
            return ToolResult(ok=False, error="prompt 不能为空")
        _apply_pro_options(
            body,
            model=model,
            enable_pbr=enable_pbr,
            face_count=face_count,
            generate_type=generate_type,
            polygon_type=polygon_type,
            result_format=result_format,
        )
        return _create_and_maybe_wait(
            "pro",
            "SubmitHunyuanTo3DProJob",
            body,
            wait=wait,
            wait_timeout=wait_timeout,
        )
    except Exception as e:
        return _err(e)


@tool(
    name="hunyuan_image_to_3d_pro",
    description=(
        "混元生3D专业版·图生3D。本地图用 image_path（转 ImageBase64）；"
        "或 image_url。不可与 prompt 同时用于普通模式（Sketch 除外）。"
        + _FILE3D_NOTE
    ),
    parameters=obj_schema(
        {
            "image_url": {"type": "string"},
            "image_path": {"type": "string", "description": "本地图片路径"},
            "prompt": {
                "type": "string",
                "description": "仅 GenerateType=Sketch 时可与图同传",
            },
            **_pro_common_params(),
        },
    ),
    category="hunyuan",
    main_thread=False,
)
def hunyuan_image_to_3d_pro(
    image_url: str = "",
    image_path: str = "",
    prompt: str = "",
    model: str = "",
    enable_pbr: Optional[bool] = None,
    face_count: Optional[int] = None,
    generate_type: str = "",
    polygon_type: str = "",
    result_format: str = "",
    wait: bool = False,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    try:
        body: Dict[str, Any] = {}
        body.update(
            resolve_image_fields(image_url=image_url, image_path=image_path)
        )
        gt = (generate_type or "").strip()
        if prompt:
            body["Prompt"] = prompt.strip()
            if not gt:
                # Prompt + image together requires Sketch mode per API
                gt = "Sketch"
        _apply_pro_options(
            body,
            model=model,
            enable_pbr=enable_pbr,
            face_count=face_count,
            generate_type=gt,
            polygon_type=polygon_type,
            result_format=result_format,
        )
        return _create_and_maybe_wait(
            "pro",
            "SubmitHunyuanTo3DProJob",
            body,
            wait=wait,
            wait_timeout=wait_timeout,
        )
    except Exception as e:
        return _err(e)


@tool(
    name="hunyuan_multiview_to_3d_pro",
    description=(
        "混元生3D专业版·多视角图生3D（MultiViewImages）。"
        "views 为对象数组：view_type + image_url 或 image_path。"
        "视角：left/right/back；3.1 另支持 top/bottom/left_front/right_front。"
    ),
    parameters=obj_schema(
        {
            "views": {
                "type": "array",
                "items": {"type": "object"},
                "description": '如 [{"view_type":"left","image_path":"..."}, ...]',
            },
            **_pro_common_params(),
        },
        required=["views"],
    ),
    category="hunyuan",
    main_thread=False,
)
def hunyuan_multiview_to_3d_pro(
    views: Optional[List[Dict[str, Any]]] = None,
    model: str = "",
    enable_pbr: Optional[bool] = None,
    face_count: Optional[int] = None,
    generate_type: str = "",
    polygon_type: str = "",
    result_format: str = "",
    wait: bool = False,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    try:
        raw = list(views or [])
        if not raw:
            return ToolResult(ok=False, error="views 不能为空")
        multi: List[Dict[str, Any]] = []
        for v in raw:
            if not isinstance(v, dict):
                continue
            vt = str(v.get("view_type") or v.get("ViewType") or "").strip()
            if not vt:
                return ToolResult(ok=False, error="每个 view 需要 view_type")
            item: Dict[str, Any] = {"ViewType": vt}
            path = str(v.get("image_path") or v.get("ViewImagePath") or "").strip()
            url = str(
                v.get("image_url")
                or v.get("ViewImageUrl")
                or v.get("url")
                or ""
            ).strip()
            if path:
                fields = resolve_image_fields(image_path=path)
                if "ImageBase64" in fields:
                    item["ViewImageBase64"] = fields["ImageBase64"]
                elif "ImageUrl" in fields:
                    item["ViewImageUrl"] = fields["ImageUrl"]
            elif url:
                fields = resolve_image_fields(image_url=url)
                if "ImageBase64" in fields:
                    item["ViewImageBase64"] = fields["ImageBase64"]
                else:
                    item["ViewImageUrl"] = fields.get("ImageUrl") or url
            else:
                return ToolResult(
                    ok=False, error=f"视角 {vt} 需要 image_url 或 image_path"
                )
            multi.append(item)
        if not multi:
            return ToolResult(ok=False, error="未能解析任何有效视角")
        body: Dict[str, Any] = {"MultiViewImages": multi}
        _apply_pro_options(
            body,
            model=model or "3.1",
            enable_pbr=enable_pbr,
            face_count=face_count,
            generate_type=generate_type,
            polygon_type=polygon_type,
            result_format=result_format,
        )
        return _create_and_maybe_wait(
            "pro",
            "SubmitHunyuanTo3DProJob",
            body,
            wait=wait,
            wait_timeout=wait_timeout,
        )
    except Exception as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Generation — Rapid
# ---------------------------------------------------------------------------


@tool(
    name="hunyuan_text_to_3d_rapid",
    description=(
        "混元生3D极速版·文生3D（SubmitHunyuanTo3DRapidJob）。"
        "prompt 最多 200 字。完成后 hunyuan_import_to_maya(kind='rapid', ...)。"
    ),
    parameters=obj_schema(
        {
            "prompt": {"type": "string"},
            "enable_pbr": {"type": "boolean"},
            "enable_geometry": {
                "type": "boolean",
                "description": "白模（无纹理）；开启后默认 GLB",
            },
            "result_format": {
                "type": "string",
                "description": "OBJ/GLB/STL/USDZ/FBX/MP4",
            },
            "wait": {"type": "boolean", "default": False},
            "wait_timeout": {"type": "number"},
        },
        required=["prompt"],
    ),
    category="hunyuan",
    main_thread=False,
)
def hunyuan_text_to_3d_rapid(
    prompt: str,
    enable_pbr: Optional[bool] = None,
    enable_geometry: Optional[bool] = None,
    result_format: str = "",
    wait: bool = False,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    try:
        body: Dict[str, Any] = {"Prompt": (prompt or "").strip()}
        if not body["Prompt"]:
            return ToolResult(ok=False, error="prompt 不能为空")
        if enable_pbr is not None:
            body["EnablePBR"] = bool(enable_pbr)
        if enable_geometry is not None:
            body["EnableGeometry"] = bool(enable_geometry)
        if result_format:
            body["ResultFormat"] = result_format.upper()
        return _create_and_maybe_wait(
            "rapid",
            "SubmitHunyuanTo3DRapidJob",
            body,
            wait=wait,
            wait_timeout=wait_timeout,
        )
    except Exception as e:
        return _err(e)


@tool(
    name="hunyuan_image_to_3d_rapid",
    description="混元生3D极速版·图生3D。本地图 image_path → ImageBase64，或 image_url。",
    parameters=obj_schema(
        {
            "image_url": {"type": "string"},
            "image_path": {"type": "string"},
            "enable_pbr": {"type": "boolean"},
            "enable_geometry": {"type": "boolean"},
            "result_format": {"type": "string"},
            "wait": {"type": "boolean", "default": False},
            "wait_timeout": {"type": "number"},
        },
    ),
    category="hunyuan",
    main_thread=False,
)
def hunyuan_image_to_3d_rapid(
    image_url: str = "",
    image_path: str = "",
    enable_pbr: Optional[bool] = None,
    enable_geometry: Optional[bool] = None,
    result_format: str = "",
    wait: bool = False,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    try:
        body: Dict[str, Any] = resolve_image_fields(
            image_url=image_url, image_path=image_path
        )
        if enable_pbr is not None:
            body["EnablePBR"] = bool(enable_pbr)
        if enable_geometry is not None:
            body["EnableGeometry"] = bool(enable_geometry)
        if result_format:
            body["ResultFormat"] = result_format.upper()
        return _create_and_maybe_wait(
            "rapid",
            "SubmitHunyuanTo3DRapidJob",
            body,
            wait=wait,
            wait_timeout=wait_timeout,
        )
    except Exception as e:
        return _err(e)


@tool(
    name="hunyuan_profile_to_3d",
    description=(
        "混元 3D 人物生成（SubmitProfileTo3DJob）。"
        "需头像 image_url/image_path + template（见 hunyuan_list_profile_templates）。"
    ),
    parameters=obj_schema(
        {
            "image_url": {"type": "string"},
            "image_path": {"type": "string"},
            "template": {
                "type": "string",
                "description": "如 basketball / pingpong / guitar",
            },
            "wait": {"type": "boolean", "default": False},
            "wait_timeout": {"type": "number"},
        },
    ),
    category="hunyuan",
    main_thread=False,
)
def hunyuan_profile_to_3d(
    image_url: str = "",
    image_path: str = "",
    template: str = "",
    wait: bool = False,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    try:
        body: Dict[str, Any] = {
            "Profile": resolve_profile_image(
                image_url=image_url, image_path=image_path
            )
        }
        if template:
            body["Template"] = template.strip()
        return _create_and_maybe_wait(
            "profile",
            "SubmitProfileTo3DJob",
            body,
            wait=wait,
            wait_timeout=wait_timeout,
        )
    except Exception as e:
        return _err(e)


@tool(
    name="hunyuan_list_profile_templates",
    description="列出混元人物生成 Template 预设 ID。",
    parameters=obj_schema({}),
    category="hunyuan",
    main_thread=False,
)
def hunyuan_list_profile_templates() -> ToolResult:
    return ToolResult(
        ok=True,
        data={"templates": list(PROFILE_TEMPLATES)},
        message=f"共 {len(PROFILE_TEMPLATES)} 个模板",
    )


# ---------------------------------------------------------------------------
# Post-process
# ---------------------------------------------------------------------------


@tool(
    name="hunyuan_texture",
    description=(
        "混元纹理生成（SubmitTextureTo3DJob）。源模型 Type 为 OBJ/GLB。"
        + _FILE3D_NOTE
    ),
    parameters=obj_schema(
        {
            **_file3d_params(),
            "prompt": {"type": "string"},
            "image_url": {"type": "string", "description": "纹理参考图 URL"},
            "image_path": {"type": "string", "description": "纹理参考图本地路径"},
            "model": {"type": "string", "description": "3.0 / 3.1"},
            "enable_pbr": {"type": "boolean"},
            "enable_keep_uv": {"type": "boolean"},
            "texture_size": {"type": "integer", "description": "720–4096"},
            "wait": {"type": "boolean", "default": False},
            "wait_timeout": {"type": "number"},
        },
    ),
    category="hunyuan",
    main_thread=False,
)
def hunyuan_texture(
    file_url: str = "",
    file_type: str = "",
    input_job_id: str = "",
    input_job_kind: str = "",
    prompt: str = "",
    image_url: str = "",
    image_path: str = "",
    model: str = "",
    enable_pbr: Optional[bool] = None,
    enable_keep_uv: Optional[bool] = None,
    texture_size: Optional[int] = None,
    wait: bool = False,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    try:
        client = _client()
        f3d = client.resolve_file3d(
            file_url=file_url,
            file_type=file_type or "GLB",
            input_job_id=input_job_id,
            input_job_kind=input_job_kind,
            prefer_types=["glb", "obj"],
        )
        body: Dict[str, Any] = {"File3D": f3d}
        if prompt:
            body["Prompt"] = prompt.strip()
        if image_url or image_path:
            body["Image"] = resolve_profile_image(
                image_url=image_url, image_path=image_path
            )
        if model:
            body["Model"] = model
        if enable_pbr is not None:
            body["EnablePBR"] = bool(enable_pbr)
        if enable_keep_uv is not None:
            body["EnableKeepUV"] = bool(enable_keep_uv)
        if texture_size is not None:
            body["TextureSize"] = int(texture_size)
        return _create_and_maybe_wait(
            "texture",
            "SubmitTextureTo3DJob",
            body,
            wait=wait,
            wait_timeout=wait_timeout,
        )
    except Exception as e:
        return _err(e)


@tool(
    name="hunyuan_reduce_face",
    description=("混元智能拓扑/减面（SubmitReduceFaceJob）。源 OBJ/GLB。" + _FILE3D_NOTE),
    parameters=obj_schema(
        {
            **_file3d_params(),
            "polygon_type": {
                "type": "string",
                "enum": ["triangle", "quadrilateral"],
            },
            "face_level": {
                "type": "string",
                "enum": ["high", "medium", "low"],
            },
            "wait": {"type": "boolean", "default": False},
            "wait_timeout": {"type": "number"},
        },
    ),
    category="hunyuan",
    main_thread=False,
)
def hunyuan_reduce_face(
    file_url: str = "",
    file_type: str = "",
    input_job_id: str = "",
    input_job_kind: str = "",
    polygon_type: str = "",
    face_level: str = "",
    wait: bool = False,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    try:
        client = _client()
        f3d = client.resolve_file3d(
            file_url=file_url,
            file_type=file_type or "GLB",
            input_job_id=input_job_id,
            input_job_kind=input_job_kind,
            prefer_types=["glb", "obj"],
        )
        body: Dict[str, Any] = {"File3D": f3d}
        if polygon_type:
            body["PolygonType"] = polygon_type
        if face_level:
            body["FaceLevel"] = face_level
        return _create_and_maybe_wait(
            "reduce_face",
            "SubmitReduceFaceJob",
            body,
            wait=wait,
            wait_timeout=wait_timeout,
        )
    except Exception as e:
        return _err(e)


@tool(
    name="hunyuan_part",
    description=(
        "混元组件生成（SubmitHunyuan3DPartJob）。输入 File 仅支持 FBX。"
        + _FILE3D_NOTE
    ),
    parameters=obj_schema(
        {
            **_file3d_params(prefer_note="；优先 FBX"),
            "model": {"type": "string", "description": "默认 1.5"},
            "enable_staged_generation": {"type": "boolean"},
            "part_segmentation_info": {"type": "string"},
            "wait": {"type": "boolean", "default": False},
            "wait_timeout": {"type": "number"},
        },
    ),
    category="hunyuan",
    main_thread=False,
)
def hunyuan_part(
    file_url: str = "",
    file_type: str = "",
    input_job_id: str = "",
    input_job_kind: str = "",
    model: str = "",
    enable_staged_generation: Optional[bool] = None,
    part_segmentation_info: str = "",
    wait: bool = False,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    try:
        client = _client()
        f3d = client.resolve_file3d(
            file_url=file_url,
            file_type=file_type or "FBX",
            input_job_id=input_job_id,
            input_job_kind=input_job_kind,
            prefer_types=["fbx"],
            as_input_file=True,
        )
        body: Dict[str, Any] = {"File": f3d}
        if model:
            body["Model"] = model
        if enable_staged_generation is not None:
            body["EnableStagedGeneration"] = bool(enable_staged_generation)
        if part_segmentation_info:
            body["PartSegmentationInfo"] = part_segmentation_info
        return _create_and_maybe_wait(
            "part",
            "SubmitHunyuan3DPartJob",
            body,
            wait=wait,
            wait_timeout=wait_timeout,
        )
    except Exception as e:
        return _err(e)


@tool(
    name="hunyuan_uv",
    description=("混元 UV 展开（SubmitHunyuanTo3DUVJob）。支持 FBX/OBJ/GLB。" + _FILE3D_NOTE),
    parameters=obj_schema(
        {
            **_file3d_params(),
            "wait": {"type": "boolean", "default": False},
            "wait_timeout": {"type": "number"},
        },
    ),
    category="hunyuan",
    main_thread=False,
)
def hunyuan_uv(
    file_url: str = "",
    file_type: str = "",
    input_job_id: str = "",
    input_job_kind: str = "",
    wait: bool = False,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    try:
        client = _client()
        f3d = client.resolve_file3d(
            file_url=file_url,
            file_type=file_type,
            input_job_id=input_job_id,
            input_job_kind=input_job_kind,
            prefer_types=["fbx", "glb", "obj"],
            as_input_file=True,
        )
        return _create_and_maybe_wait(
            "uv",
            "SubmitHunyuanTo3DUVJob",
            {"File": f3d},
            wait=wait,
            wait_timeout=wait_timeout,
        )
    except Exception as e:
        return _err(e)


@tool(
    name="hunyuan_auto_rig",
    description=(
        "混元自动绑骨蒙皮（SubmitAutoRiggingJob）。输入 FBX/GLB 公网 Url。"
        "可选 MotionType 预设动作（hunyuan_list_motions）。"
        + _FILE3D_NOTE
    ),
    parameters=obj_schema(
        {
            **_file3d_params(prefer_note="；FBX 或 GLB"),
            "motion_type": {
                "type": "integer",
                "description": "预设动作 ID 1–48，见 hunyuan_list_motions",
            },
            "wait": {"type": "boolean", "default": False},
            "wait_timeout": {"type": "number"},
        },
    ),
    category="hunyuan",
    main_thread=False,
)
def hunyuan_auto_rig(
    file_url: str = "",
    file_type: str = "",
    input_job_id: str = "",
    input_job_kind: str = "",
    motion_type: Optional[int] = None,
    wait: bool = False,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    try:
        client = _client()
        f3d = client.resolve_file3d(
            file_url=file_url,
            file_type=file_type or "FBX",
            input_job_id=input_job_id,
            input_job_kind=input_job_kind,
            prefer_types=["fbx", "glb"],
            as_input_file=True,
        )
        body: Dict[str, Any] = {"File3D": f3d}
        if motion_type is not None:
            body["MotionType"] = int(motion_type)
        return _create_and_maybe_wait(
            "auto_rig",
            "SubmitAutoRiggingJob",
            body,
            wait=wait,
            wait_timeout=wait_timeout,
        )
    except Exception as e:
        return _err(e)


@tool(
    name="hunyuan_list_motions",
    description="列出混元绑骨 MotionType 预设（静态表，供 hunyuan_auto_rig）。",
    parameters=obj_schema({}),
    category="hunyuan",
    main_thread=False,
)
def hunyuan_list_motions() -> ToolResult:
    return ToolResult(
        ok=True,
        data={"motions": list(MOTION_PRESETS)},
        message=f"共 {len(MOTION_PRESETS)} 个预设动作",
    )


@tool(
    name="hunyuan_motion",
    description=(
        "混元文生动作（SubmitHunyuanTo3DMotionJob）。"
        "prompt 必填；可选 RetargetFile（混元动画模板模型公网 Url / 上游 Job）。"
        + _FILE3D_NOTE
    ),
    parameters=obj_schema(
        {
            "prompt": {"type": "string", "description": "动作描述，最多 128 字"},
            "model": {"type": "string", "description": "默认 HY-Motion-1.0"},
            "duration": {"type": "integer", "description": "1–12 秒"},
            "enable_mesh": {"type": "boolean"},
            "enable_rewrite": {"type": "boolean"},
            "enable_duration_est": {"type": "boolean"},
            **_file3d_params(prefer_note=" → RetargetFile"),
            "wait": {"type": "boolean", "default": False},
            "wait_timeout": {"type": "number"},
        },
        required=["prompt"],
    ),
    category="hunyuan",
    main_thread=False,
)
def hunyuan_motion(
    prompt: str,
    model: str = "",
    duration: Optional[int] = None,
    enable_mesh: Optional[bool] = None,
    enable_rewrite: Optional[bool] = None,
    enable_duration_est: Optional[bool] = None,
    file_url: str = "",
    file_type: str = "",
    input_job_id: str = "",
    input_job_kind: str = "",
    wait: bool = False,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    try:
        body: Dict[str, Any] = {"Prompt": (prompt or "").strip()}
        if not body["Prompt"]:
            return ToolResult(ok=False, error="prompt 不能为空")
        if model:
            body["Model"] = model
        if duration is not None:
            body["Duration"] = int(duration)
        if enable_mesh is not None:
            body["EnableMesh"] = bool(enable_mesh)
        if enable_rewrite is not None:
            body["EnableRewrite"] = bool(enable_rewrite)
        if enable_duration_est is not None:
            body["EnableDurationEst"] = bool(enable_duration_est)
        if file_url or input_job_id:
            client = _client()
            body["RetargetFile"] = client.resolve_file3d(
                file_url=file_url,
                file_type=file_type,
                input_job_id=input_job_id,
                input_job_kind=input_job_kind,
                prefer_types=["fbx", "glb"],
                as_input_file=True,
            )
        return _create_and_maybe_wait(
            "motion",
            "SubmitHunyuanTo3DMotionJob",
            body,
            wait=wait,
            wait_timeout=wait_timeout,
        )
    except Exception as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Jobs / convert / download / import
# ---------------------------------------------------------------------------


@tool(
    name="hunyuan_get_job",
    description="查询混元任务状态与 ResultFile3Ds。必须提供 kind（pro/rapid/texture/...）。",
    parameters=obj_schema(
        {
            "kind": {"type": "string", "enum": _KIND_ENUM},
            "job_id": {"type": "string"},
        },
        required=["kind", "job_id"],
    ),
    category="hunyuan",
    main_thread=False,
)
def hunyuan_get_job(kind: str, job_id: str) -> ToolResult:
    try:
        task = _client().get_job(kind, job_id)
        return ToolResult(
            ok=True,
            data={"kind": kind, "job_id": job_id, "task": summarize_task(task)},
            message=f"status={task.get('Status')}",
        )
    except Exception as e:
        return _err(e)


@tool(
    name="hunyuan_wait_job",
    description=(
        "轮询等待混元任务至 DONE/FAIL。成功后可 hunyuan_import_to_maya / hunyuan_download。"
    ),
    parameters=obj_schema(
        {
            "kind": {"type": "string", "enum": _KIND_ENUM},
            "job_id": {"type": "string"},
            "timeout": {"type": "number"},
            "wait_timeout": {"type": "number", "description": "timeout 别名"},
        },
        required=["kind", "job_id"],
    ),
    category="hunyuan",
    main_thread=False,
)
def hunyuan_wait_job(
    kind: str,
    job_id: str,
    timeout: Optional[float] = None,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    try:
        limit = timeout if timeout is not None else wait_timeout
        report_tool_progress(
            kind=kind,
            task_id=job_id,
            status="WAIT",
            progress=estimate_status_progress("WAIT"),
            message=f"混元 {kind} 等待中…",
        )
        task = _client().wait(
            kind,
            job_id,
            timeout=limit,
            on_progress=_wait_progress(kind, job_id),
        )
        report_tool_progress(
            kind=kind,
            task_id=job_id,
            status="DONE",
            progress=100,
            message=f"混元 {kind} 已完成",
        )
        return ToolResult(
            ok=True,
            data={"kind": kind, "job_id": job_id, "task": summarize_task(task)},
            message=f"混元任务已完成：{job_id}",
        )
    except Exception as e:
        return _err(e)


@tool(
    name="hunyuan_convert",
    description=(
        "混元同步格式转换（Convert3DFormat）。"
        "File3D 为公网 Url 字符串；Format：STL/USDZ/FBX/MP4/GIF。"
        "也可传 input_job_id 取结果 Url 再转换。"
    ),
    parameters=obj_schema(
        {
            "format": {"type": "string", "description": "STL / USDZ / FBX / MP4 / GIF"},
            "file_url": {"type": "string"},
            "input_job_id": {"type": "string"},
            "input_job_kind": {"type": "string", "enum": _KIND_ENUM},
        },
        required=["format"],
    ),
    category="hunyuan",
    main_thread=False,
)
def hunyuan_convert(
    format: str,
    file_url: str = "",
    input_job_id: str = "",
    input_job_kind: str = "",
) -> ToolResult:
    try:
        client = _client()
        url = (file_url or "").strip()
        if not url and input_job_id:
            f3d = client.resolve_file3d(
                input_job_id=input_job_id,
                input_job_kind=input_job_kind,
                prefer_types=["fbx", "glb", "obj"],
            )
            url = f3d["Url"]
        if not url:
            return ToolResult(ok=False, error="需要 file_url 或 input_job_id+input_job_kind")
        data = client.convert(url, format)
        return ToolResult(
            ok=True,
            data=summarize_task(data),
            message=f"已转换: {data.get('ResultFile3D') or ''}",
        )
    except Exception as e:
        return _err(e)


def _ext_from_url_or_type(url: str, typ: str) -> str:
    typ_l = (typ or "").lower().strip(".")
    if typ_l and typ_l not in ("bin", "zip"):
        return typ_l
    path = urlparse(url).path.lower()
    for ext in ("fbx", "glb", "obj", "stl", "usdz", "zip", "mp4", "gif", "png"):
        if path.endswith("." + ext):
            return ext
    return typ_l or "bin"


@tool(
    name="hunyuan_download",
    description=(
        "下载已成功混元任务的模型到本地。需 kind+job_id，或直接 url。"
        "prefer_format 默认 fbx。"
    ),
    parameters=obj_schema(
        {
            "kind": {"type": "string", "enum": _KIND_ENUM},
            "job_id": {"type": "string"},
            "url": {"type": "string"},
            "prefer_format": {"type": "string", "default": "fbx"},
            "filename": {"type": "string"},
            "output_dir": {"type": "string"},
        },
    ),
    category="hunyuan",
    main_thread=False,
)
def hunyuan_download(
    kind: str = "",
    job_id: str = "",
    url: str = "",
    prefer_format: str = "fbx",
    filename: str = "",
    output_dir: str = "",
) -> ToolResult:
    try:
        client = _client()
        fmt = (prefer_format or "fbx").strip().lower()
        download_url = (url or "").strip()
        tid = (job_id or "").strip() or "asset"
        k = (kind or "").strip().lower()
        if not download_url:
            if not job_id or not k:
                return ToolResult(ok=False, error="需要 url，或 kind+job_id")
            task = client.get_job(k, job_id)
            status = str(task.get("Status") or "").upper()
            if status != "DONE":
                return ToolResult(
                    ok=False,
                    error=f"任务尚未成功（status={status}）",
                    data=summarize_task(task),
                )
            typ, download_url = pick_result_url(
                task, prefer=[fmt, "fbx", "glb", "obj"]
            )
            fmt = typ or fmt
        else:
            fmt = _ext_from_url_or_type(download_url, fmt)

        out_dir = Path(output_dir) if output_dir else download_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        name = (filename or "").strip() or f"hunyuan_{tid}.{fmt}"
        if "." not in Path(name).name:
            name = f"{name}.{fmt}"
        dest = out_dir / name
        client.download(download_url, dest)
        return ToolResult(
            ok=True,
            data={
                "path": str(dest),
                "format": fmt,
                "job_id": tid,
                "kind": k,
                "url": download_url,
            },
            message=f"已下载: {dest}",
        )
    except Exception as e:
        return _err(e)


@tool(
    name="hunyuan_import_to_maya",
    description=(
        "将混元成功任务的模型下载并导入当前 Maya 场景（优先 FBX）。"
        "非 FBX 时可 auto_convert_fbx=true 先 Convert3DFormat。"
        "复用 Meshy 的 FBX PBR 重建逻辑。可传 kind+job_id 或 file_path。"
    ),
    parameters=obj_schema(
        {
            "kind": {"type": "string", "enum": _KIND_ENUM},
            "job_id": {"type": "string"},
            "file_path": {"type": "string"},
            "prefer_format": {"type": "string", "default": "fbx"},
            "namespace": {"type": "string", "default": "hunyuan"},
            "output_dir": {"type": "string"},
            "rebuild_pbr": {"type": "boolean", "default": True},
            "auto_convert_fbx": {
                "type": "boolean",
                "default": True,
                "description": "下载结果非 FBX 时尝试 Convert3DFormat→FBX",
            },
        },
    ),
    category="hunyuan",
    main_thread=False,
)
def hunyuan_import_to_maya(
    kind: str = "",
    job_id: str = "",
    file_path: str = "",
    prefer_format: str = "fbx",
    namespace: str = "hunyuan",
    output_dir: str = "",
    rebuild_pbr: bool = True,
    auto_convert_fbx: bool = True,
) -> ToolResult:
    try:
        from maya_agent.tools.meshy import _import_path_into_maya

        local = (file_path or "").strip()
        tid = (job_id or "").strip()
        k = (kind or "").strip().lower()
        fmt = (prefer_format or "fbx").strip().lower()

        if not local:
            if not tid or not k:
                return ToolResult(ok=False, error="需要 kind+job_id 或 file_path")
            dl = hunyuan_download(
                kind=k,
                job_id=tid,
                prefer_format=fmt,
                output_dir=output_dir,
            )
            if not dl.ok:
                return dl
            local = str((dl.data or {}).get("path") or "")
            got_fmt = str((dl.data or {}).get("format") or "").lower()
            src_url = str((dl.data or {}).get("url") or "")
            if not local:
                return ToolResult(ok=False, error="下载成功但未返回路径")
            if got_fmt not in ("fbx",) and auto_convert_fbx and src_url:
                conv = hunyuan_convert(format="FBX", file_url=src_url)
                if conv.ok:
                    new_url = str(
                        ((conv.data or {}) if isinstance(conv.data, dict) else {}).get(
                            "ResultFile3D"
                        )
                        or ""
                    )
                    if new_url:
                        dl2 = hunyuan_download(
                            url=new_url,
                            prefer_format="fbx",
                            filename=f"hunyuan_{tid}_conv.fbx",
                            output_dir=output_dir,
                        )
                        if dl2.ok:
                            local = str((dl2.data or {}).get("path") or local)

        ns = (namespace or "").strip() or "hunyuan"

        def _do() -> ToolResult:
            return _import_path_into_maya(
                local, namespace=ns, rebuild_pbr=bool(rebuild_pbr)
            )

        return run_on_main_thread(_do)
    except Exception as e:
        return _err(e)


@tool(
    name="hunyuan_test_connection",
    description=(
        "测试混元 SecretId/SecretKey 是否有效（签名探测）。"
        "配置密钥后可用来验证连接；混元无余额查询接口。"
    ),
    parameters=obj_schema({}),
    category="hunyuan",
    main_thread=False,
)
def hunyuan_test_connection() -> ToolResult:
    try:
        data = _client().test_connection()
        return ToolResult(ok=True, data=data, message=data.get("message") or "连接成功")
    except Exception as e:
        return _err(e)
