"""Agent tools for Local Runtime generative backends."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from maya_agent.core.tool_progress import report_tool_progress
from maya_agent.local_models.availability import (
    backend_ready,
    image_to_3d_ready,
    list_backend_status,
    local_enabled,
    text_to_3d_ready,
)
from maya_agent.local_models.client import (
    LocalRuntimeError,
    get_task,
    runtime_status,
    start_runtime,
    submit_task,
    wait_task,
)
from maya_agent.tools.registry import ToolResult, obj_schema, tool
from maya_agent.utils.logger import get_logger
from maya_agent.utils.maya_compat import in_maya, run_on_main_thread
from maya_agent.utils.paths import models_root

log = get_logger("maya_agent.tools.local_gen")


def _err(e: BaseException) -> ToolResult:
    log.exception("local tool failed")
    return ToolResult(ok=False, error=str(e))


def _ensure_runtime() -> Optional[str]:
    if not local_enabled():
        return "本地模型已在设置中禁用（local.enabled=false）"
    st = runtime_status()
    if st.get("online"):
        return None
    if not st.get("installed"):
        return (
            "Local Runtime 未安装。请运行项目根目录 install_local_runtime.bat，"
            "或在「模型 → 本地模型」中安装。权重需另行手动下载。"
        )
    started = start_runtime(wait_online=25.0)
    if not started.get("ok"):
        return started.get("error") or "无法启动 Local Runtime"
    return None


def _submit_and_wait(
    kind: str,
    params: Dict[str, Any],
    *,
    wait: bool = True,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    gate = _ensure_runtime()
    if gate:
        return ToolResult(ok=False, error=gate)
    try:
        created = submit_task(kind, params)
        task_id = str(created.get("id") or "")
        if not task_id:
            return ToolResult(ok=False, error="Runtime 未返回 task id", data=created)
        if not wait:
            return ToolResult(
                ok=True,
                message=f"任务已提交 {task_id}，请 local_wait_task 等待",
                data={"task_id": task_id, **created},
            )

        def _prog(ev: Dict[str, Any]) -> None:
            report_tool_progress(
                progress=ev.get("progress") or 0,
                status=str(ev.get("status") or ""),
                message=str(ev.get("message") or ""),
            )

        done = wait_task(task_id, timeout=wait_timeout, on_progress=_prog)
        status = str(done.get("status") or "").upper()
        result = done.get("result") if isinstance(done.get("result"), dict) else {}
        if status != "SUCCEEDED" or not result.get("ok", True):
            return ToolResult(
                ok=False,
                error=done.get("error")
                or result.get("error")
                or f"任务失败: {status}",
                data=done,
            )
        return ToolResult(
            ok=True,
            message=result.get("message") or "完成",
            data={
                "task_id": task_id,
                "artifacts": result.get("artifacts") or [],
                "result": result.get("data") or result,
            },
        )
    except LocalRuntimeError as e:
        return ToolResult(ok=False, error=str(e))
    except Exception as e:
        return _err(e)


def _import_path(path: str, namespace: str = "") -> Dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        return {"ok": False, "error": f"文件不存在: {path}"}

    def _do() -> Dict[str, Any]:
        import maya.cmds as cmds

        before = set(cmds.ls(assemblies=True) or [])
        ext = p.suffix.lower()
        try:
            if ext in (".fbx", ".obj", ".glb", ".gltf", ".abc", ".dae", ".ma", ".mb"):
                typemap = {
                    ".fbx": "FBX",
                    ".obj": "OBJ",
                    ".glb": "GLTF",
                    ".gltf": "GLTF",
                    ".abc": "Alembic",
                    ".dae": "DAE_FBX",
                    ".ma": "mayaAscii",
                    ".mb": "mayaBinary",
                }
                kwargs = {"i": True, "ignoreVersion": True, "mergeNamespacesOnClash": False}
                if namespace:
                    kwargs["namespace"] = namespace
                # GLB may need plugin
                if ext in (".glb", ".gltf"):
                    try:
                        if not cmds.pluginInfo("fbxmaya", query=True, loaded=True):
                            pass
                    except Exception:
                        pass
                cmds.file(str(p), **kwargs)
            elif ext == ".bvh":
                # Best-effort: Maya has limited BVH; try as motion import via mel if available
                try:
                    import maya.mel as mel

                    mel.eval(f'file -import -type "BVH" "{str(p).replace(chr(92), "/")}"')
                except Exception:
                    return {
                        "ok": False,
                        "error": (
                            "当前 Maya 无法直接导入 BVH。文件已生成："
                            f"{path}。请用动画工具或手动重定向。"
                        ),
                        "path": path,
                    }
            else:
                cmds.file(str(p), i=True, ignoreVersion=True)
        except Exception as e:
            return {"ok": False, "error": str(e), "path": path}
        after = set(cmds.ls(assemblies=True) or [])
        created = sorted(after - before)
        return {"ok": True, "path": path, "created": created}

    if not in_maya():
        return {"ok": False, "error": "未在 Maya 中运行", "path": path}
    return run_on_main_thread(_do) or {"ok": False, "error": "导入失败"}


def _maybe_import(data: Dict[str, Any], import_to_maya: bool) -> Dict[str, Any]:
    if not import_to_maya:
        return data
    arts = data.get("artifacts") or []
    if not arts and isinstance(data.get("result"), dict):
        arts = data["result"].get("artifacts") or []
    imported = []
    for a in arts:
        path = a.get("path") if isinstance(a, dict) else None
        if not path:
            continue
        imported.append(_import_path(path))
    data = dict(data)
    data["imported"] = imported
    return data


def _place_layout(layout: Dict[str, Any]) -> Dict[str, Any]:
    """Create placeholder geometry for ATISS layout objects."""

    def _do() -> Dict[str, Any]:
        import maya.cmds as cmds

        created: List[str] = []
        objects = layout.get("objects") or []
        grp = cmds.group(empty=True, name="local_scene_layout_#")
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            name = str(obj.get("class") or obj.get("id") or "prop")
            size = obj.get("size") or [0.6, 0.6, 0.6]
            tr = obj.get("translate") or [0, 0, 0]
            w, h, d = float(size[0]), float(size[1]), float(size[2])
            node = cmds.polyCube(w=w, h=h, d=d, name=f"{name}_#")[0]
            cmds.xform(
                node,
                ws=True,
                t=(float(tr[0]), float(tr[1]), float(tr[2])),
            )
            ry = float(obj.get("rotate_y") or 0)
            if ry:
                cmds.rotate(0, ry, 0, node, r=True, os=True)
            cmds.parent(node, grp)
            created.append(node)
        return {"ok": True, "group": grp, "created": created, "count": len(created)}

    if not in_maya():
        return {"ok": False, "error": "未在 Maya 中运行"}
    return run_on_main_thread(_do) or {"ok": False, "error": "摆放失败"}


@tool(
    name="local_runtime_status",
    description=(
        "查询本地 Local Runtime 与白名单模型下载状态。"
        "若某后端未下载，请提示用户前往「模型 → 本地模型」手动下载；"
        "不要尝试自动下载，也不要假装可用。"
    ),
    parameters=obj_schema({}),
    category="local",
    main_thread=False,
    local_gated=True,
)
def local_runtime_status() -> ToolResult:
    try:
        st = runtime_status()
        backends = list_backend_status()
        return ToolResult(
            ok=True,
            message="本地模型状态",
            data={
                "runtime": st,
                "models_dir": str(models_root()),
                "backends": backends,
                "gates": {
                    "image_to_3d": image_to_3d_ready(),
                    "text_to_3d": text_to_3d_ready(),
                    "auto_rig": backend_ready("unirig"),
                    "text_to_motion": backend_ready("mdm"),
                    "scene_layout": backend_ready("atiss"),
                },
            },
        )
    except Exception as e:
        return _err(e)


@tool(
    name="local_image_to_3d",
    description=(
        "本地图生3D（TripoSR 或 Hunyuan3D，取决于已下载后端）。"
        "需要用户已手动下载对应权重；未下载时本工具不会出现。"
    ),
    parameters=obj_schema(
        {
            "image_path": {"type": "string", "description": "输入图片绝对路径"},
            "backend": {
                "type": "string",
                "description": "triposr | hunyuan3d2；默认自动选择",
            },
            "wait": {"type": "boolean", "default": True},
            "wait_timeout": {"type": "number"},
            "import_to_maya": {"type": "boolean", "default": True},
        },
        required=["image_path"],
    ),
    category="local",
    main_thread=False,
    local_gated=True,
)
def local_image_to_3d(
    image_path: str,
    backend: str = "",
    wait: bool = True,
    wait_timeout: Optional[float] = None,
    import_to_maya: bool = True,
) -> ToolResult:
    params: Dict[str, Any] = {"image_path": image_path}
    if backend:
        params["backend"] = backend
    result = _submit_and_wait(
        "image_to_3d", params, wait=wait, wait_timeout=wait_timeout
    )
    if result.ok and wait and import_to_maya and isinstance(result.data, dict):
        result.data = _maybe_import(result.data, True)
    return result


@tool(
    name="local_text_to_3d",
    description=(
        "本地文生3D。优先 Hunyuan3D；若仅有 TripoSR+SD-Turbo 则走文生图再重建。"
        "权重须用户手动下载。"
    ),
    parameters=obj_schema(
        {
            "prompt": {"type": "string"},
            "backend": {"type": "string", "description": "hunyuan3d2 | triposr"},
            "wait": {"type": "boolean", "default": True},
            "wait_timeout": {"type": "number"},
            "import_to_maya": {"type": "boolean", "default": True},
        },
        required=["prompt"],
    ),
    category="local",
    main_thread=False,
    local_gated=True,
)
def local_text_to_3d(
    prompt: str,
    backend: str = "",
    wait: bool = True,
    wait_timeout: Optional[float] = None,
    import_to_maya: bool = True,
) -> ToolResult:
    params: Dict[str, Any] = {"prompt": prompt}
    if backend:
        params["backend"] = backend
    result = _submit_and_wait(
        "text_to_3d", params, wait=wait, wait_timeout=wait_timeout
    )
    if result.ok and wait and import_to_maya and isinstance(result.data, dict):
        result.data = _maybe_import(result.data, True)
    return result


@tool(
    name="local_auto_rig",
    description="本地 UniRig 自动绑骨（需已下载 unirig）。输入 mesh 文件路径。",
    parameters=obj_schema(
        {
            "mesh_path": {"type": "string"},
            "wait": {"type": "boolean", "default": True},
            "wait_timeout": {"type": "number"},
            "import_to_maya": {"type": "boolean", "default": True},
        },
        required=["mesh_path"],
    ),
    category="local",
    main_thread=False,
    local_gated=True,
)
def local_auto_rig(
    mesh_path: str,
    wait: bool = True,
    wait_timeout: Optional[float] = None,
    import_to_maya: bool = True,
) -> ToolResult:
    result = _submit_and_wait(
        "auto_rig",
        {"mesh_path": mesh_path},
        wait=wait,
        wait_timeout=wait_timeout,
    )
    if result.ok and wait and import_to_maya and isinstance(result.data, dict):
        result.data = _maybe_import(result.data, True)
    return result


@tool(
    name="local_text_to_motion",
    description="本地 MDM 文本生成动作（BVH）。需已下载 mdm。",
    parameters=obj_schema(
        {
            "prompt": {"type": "string"},
            "frames": {"type": "integer", "default": 120},
            "wait": {"type": "boolean", "default": True},
            "wait_timeout": {"type": "number"},
            "import_to_maya": {
                "type": "boolean",
                "default": True,
                "description": "尝试导入 BVH（Maya 支持有限）",
            },
        },
        required=["prompt"],
    ),
    category="local",
    main_thread=False,
    local_gated=True,
)
def local_text_to_motion(
    prompt: str,
    frames: int = 120,
    wait: bool = True,
    wait_timeout: Optional[float] = None,
    import_to_maya: bool = True,
) -> ToolResult:
    result = _submit_and_wait(
        "text_to_motion",
        {"prompt": prompt, "frames": int(frames)},
        wait=wait,
        wait_timeout=wait_timeout,
    )
    if result.ok and wait and import_to_maya and isinstance(result.data, dict):
        result.data = _maybe_import(result.data, True)
    return result


@tool(
    name="local_scene_layout",
    description=(
        "本地 ATISS 室内场景布局。返回摆放清单并在 Maya 中创建占位立方体。"
        "generate_assets=true 时，仅当已下载图/文生3D 后端才会尝试为物体生成网格（否则仍用占位）。"
    ),
    parameters=obj_schema(
        {
            "prompt": {"type": "string", "description": "场景描述"},
            "room_type": {"type": "string", "default": "livingroom"},
            "width": {"type": "number", "default": 6},
            "depth": {"type": "number", "default": 5},
            "place_placeholders": {"type": "boolean", "default": True},
            "generate_assets": {"type": "boolean", "default": False},
            "wait": {"type": "boolean", "default": True},
            "wait_timeout": {"type": "number"},
        },
        required=["prompt"],
    ),
    category="local",
    main_thread=False,
    local_gated=True,
)
def local_scene_layout(
    prompt: str,
    room_type: str = "livingroom",
    width: float = 6.0,
    depth: float = 5.0,
    place_placeholders: bool = True,
    generate_assets: bool = False,
    wait: bool = True,
    wait_timeout: Optional[float] = None,
) -> ToolResult:
    result = _submit_and_wait(
        "scene_layout",
        {
            "prompt": prompt,
            "room_type": room_type,
            "width": width,
            "depth": depth,
        },
        wait=wait,
        wait_timeout=wait_timeout,
    )
    if not result.ok or not wait:
        return result
    data = result.data if isinstance(result.data, dict) else {}
    layout = {}
    inner = data.get("result") if isinstance(data.get("result"), dict) else {}
    if isinstance(inner, dict) and inner.get("objects"):
        layout = inner
    elif isinstance(data.get("result"), dict):
        # result may be full backend payload
        layout = data.get("result") or {}
    # Also check artifacts json
    for a in data.get("artifacts") or []:
        if isinstance(a, dict) and str(a.get("path") or "").endswith(".json"):
            try:
                layout = json.loads(Path(a["path"]).read_text(encoding="utf-8"))
            except Exception:
                pass
    placed = None
    if place_placeholders and layout.get("objects"):
        placed = _place_layout(layout)
    asset_note = None
    if generate_assets:
        if not image_to_3d_ready() and not text_to_3d_ready():
            asset_note = (
                "generate_assets 已请求，但未下载图/文生3D 后端；"
                "已仅使用占位几何。请用户下载 triposr 或 hunyuan3d2。"
            )
        else:
            asset_note = (
                "已下载 3D 后端：可为单个物体另调 local_text_to_3d / local_image_to_3d 替换占位。"
            )
    data = dict(data)
    data["layout"] = layout
    data["placed"] = placed
    if asset_note:
        data["asset_note"] = asset_note
    return ToolResult(ok=True, message=result.message, data=data)


@tool(
    name="local_wait_task",
    description="等待 Local Runtime 任务完成。",
    parameters=obj_schema(
        {
            "task_id": {"type": "string"},
            "wait_timeout": {"type": "number"},
        },
        required=["task_id"],
    ),
    category="local",
    main_thread=False,
    local_gated=True,
)
def local_wait_task(
    task_id: str, wait_timeout: Optional[float] = None
) -> ToolResult:
    try:
        gate = _ensure_runtime()
        if gate:
            return ToolResult(ok=False, error=gate)

        def _prog(ev: Dict[str, Any]) -> None:
            report_tool_progress(
                progress=ev.get("progress") or 0,
                status=str(ev.get("status") or ""),
                message=str(ev.get("message") or ""),
            )

        done = wait_task(task_id, timeout=wait_timeout, on_progress=_prog)
        ok = str(done.get("status") or "").upper() == "SUCCEEDED"
        return ToolResult(
            ok=ok,
            message="完成" if ok else (done.get("error") or done.get("status") or ""),
            data=done,
            error="" if ok else (done.get("error") or "failed"),
        )
    except Exception as e:
        return _err(e)


@tool(
    name="local_import_result",
    description="将本地生成的网格/BVH 文件导入当前 Maya 场景。",
    parameters=obj_schema(
        {
            "path": {"type": "string"},
            "namespace": {"type": "string", "default": ""},
        },
        required=["path"],
    ),
    category="local",
    main_thread=True,
    local_gated=True,
)
def local_import_result(path: str, namespace: str = "") -> ToolResult:
    info = _import_path(path, namespace=namespace)
    if not info.get("ok"):
        return ToolResult(ok=False, error=info.get("error") or "导入失败", data=info)
    return ToolResult(ok=True, message="已导入", data=info)
