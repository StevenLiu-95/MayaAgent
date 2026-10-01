"""Scene query, selection, hierarchy, cleanup tools."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from maya_agent.tools.registry import ToolResult, obj_schema, tool
from maya_agent.tools._maya import cmds as _cmds, in_maya


def _scene_bbox() -> Optional[Dict[str, Any]]:
    c = _cmds()
    meshes = c.ls(type="mesh", long=True) or []
    if not meshes:
        return None
    transforms: List[str] = []
    for m in meshes:
        parents = c.listRelatives(m, parent=True, fullPath=True) or []
        transforms.append(parents[0] if parents else m)
    transforms = list(dict.fromkeys(transforms))
    try:
        bb = c.exactWorldBoundingBox(transforms)
    except Exception:
        return None
    size = [float(bb[3] - bb[0]), float(bb[4] - bb[1]), float(bb[5] - bb[2])]
    center = [
        0.5 * (bb[0] + bb[3]),
        0.5 * (bb[1] + bb[4]),
        0.5 * (bb[2] + bb[5]),
    ]
    return {
        "min": [float(bb[0]), float(bb[1]), float(bb[2])],
        "max": [float(bb[3]), float(bb[4]), float(bb[5])],
        "center": center,
        "size": size,
        "diagonal": float(math.sqrt(sum(s * s for s in size))),
        "mesh_count": len(meshes),
    }


def _camera_clip_summary() -> List[Dict[str, Any]]:
    c = _cmds()
    shapes = c.ls(type="camera", long=True) or []
    out: List[Dict[str, Any]] = []
    for shape in shapes:
        parents = c.listRelatives(shape, parent=True, fullPath=True) or []
        cam = parents[0] if parents else shape
        short = cam.split("|")[-1]
        # Skip default startup cameras' shape-only noise; still include them
        entry: Dict[str, Any] = {"camera": short, "shape": shape.split("|")[-1]}
        try:
            entry["position"] = [float(x) for x in c.xform(cam, q=True, ws=True, t=True)]
        except Exception:
            pass
        for attr, key in (
            ("nearClipPlane", "near_clip"),
            ("farClipPlane", "far_clip"),
            ("focalLength", "focal_length"),
            ("orthographic", "orthographic"),
            ("orthographicWidth", "orthographic_width"),
        ):
            try:
                if c.attributeQuery(attr, node=shape, exists=True):
                    val = c.getAttr(f"{shape}.{attr}")
                    entry[key] = bool(val) if attr == "orthographic" else float(val)
            except Exception:
                pass
        out.append(entry)
    return out


def _material_distribution(limit: int = 40) -> List[Dict[str, Any]]:
    c = _cmds()
    sgs = c.ls(type="shadingEngine") or []
    rows: List[Dict[str, Any]] = []
    for sg in sgs:
        if sg in ("initialShadingGroup", "initialParticleSE"):
            continue
        try:
            members = c.sets(sg, q=True) or []
        except Exception:
            members = []
        if not members:
            continue
        shaders = c.listConnections(f"{sg}.surfaceShader") or []
        rows.append(
            {
                "shading_group": sg,
                "shader": shaders[0] if shaders else "",
                "object_count": len(members),
            }
        )
    rows.sort(key=lambda r: r["object_count"], reverse=True)
    return rows[:limit]


def _clip_coverage_hints(
    bbox: Optional[Dict[str, Any]], cameras: List[Dict[str, Any]]
) -> List[str]:
    if not bbox:
        return []
    hints: List[str] = []
    center = bbox["center"]
    diag = float(bbox.get("diagonal") or 0)
    for cam in cameras:
        far = cam.get("far_clip")
        pos = cam.get("position")
        if far is None or not pos:
            continue
        dist = math.sqrt(
            (pos[0] - center[0]) ** 2
            + (pos[1] - center[1]) ** 2
            + (pos[2] - center[2]) ** 2
        )
        if dist + diag * 0.5 > float(far) * 0.95:
            hints.append(
                f"{cam.get('camera')}: 场景可能超出 farClip"
                f"（距中心≈{dist:.0f}，对角≈{diag:.0f}，far≈{far:.0f}）"
            )
    return hints


@tool(
    name="get_scene_info",
    description=(
        "获取场景体检摘要：文件/单位、对象统计、场景 bbox、"
        "各相机 near/far/焦距/位置、材质→对象数量分布，以及裁剪面覆盖提示。"
    ),
    parameters=obj_schema({}),
    category="scene",
)
def get_scene_info() -> ToolResult:
    if not in_maya():
        return ToolResult(ok=False, error="未在 Maya 中运行")
    c = _cmds()
    selection = c.ls(selection=True, long=True) or []
    meshes = c.ls(type="mesh", long=True) or []
    transforms = c.ls(type="transform", long=True) or []
    joints = c.ls(type="joint", long=True) or []
    cameras = c.ls(type="camera", long=True) or []
    lights = c.ls(type="light", long=True) or []
    bbox = _scene_bbox()
    cam_info = _camera_clip_summary()
    mat_dist = _material_distribution()
    clip_hints = _clip_coverage_hints(bbox, cam_info)
    data = {
        "file": (c.file(query=True, sceneName=True) or "(untitled)").replace("\\", "/"),
        "maya_version": c.about(version=True),
        "units": c.currentUnit(query=True, linear=True),
        "time_unit": c.currentUnit(query=True, time=True),
        "selection": selection,
        "counts": {
            "transforms": len(transforms),
            "meshes": len(meshes),
            "joints": len(joints),
            "cameras": len(cameras),
            "lights": len(lights),
        },
        "scene_bbox": bbox,
        "cameras": cam_info,
        "materials": mat_dist,
        "clip_warnings": clip_hints,
    }
    msg = "场景信息已获取"
    if clip_hints:
        msg = f"{msg} ⚠ " + "；".join(clip_hints[:3])
    return ToolResult(ok=True, data=data, message=msg)

@tool(
    name="list_selection",
    description="列出当前选择的物体（可按类型过滤）。",
    parameters=obj_schema(
        {
            "type_filter": {
                "type": "string",
                "description": "可选 Maya 类型，如 transform/mesh/joint",
            },
            "long_names": {"type": "boolean", "default": True},
        }
    ),
    category="scene",
)
def list_selection(type_filter: str = "", long_names: bool = True) -> ToolResult:
    c = _cmds()
    kwargs: Dict[str, Any] = {"selection": True, "long": long_names}
    if type_filter:
        kwargs["type"] = type_filter
    sel = c.ls(**kwargs) or []
    return ToolResult(ok=True, data=sel, message=f"选中 {len(sel)} 个对象")

@tool(
    name="select_objects",
    description="按名称选择物体；可追加或替换选择。",
    parameters=obj_schema(
        {
            "names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "对象名称列表",
            },
            "add": {"type": "boolean", "default": False},
            "replace": {"type": "boolean", "default": True},
        },
        required=["names"],
    ),
    category="scene",
)
def select_objects(names: List[str], add: bool = False, replace: bool = True) -> ToolResult:
    c = _cmds()
    existing = [n for n in names if c.objExists(n)]
    missing = [n for n in names if not c.objExists(n)]
    if not existing:
        return ToolResult(ok=False, error=f"对象不存在: {names}")
    c.select(existing, add=add, replace=replace and not add)
    return ToolResult(
        ok=True,
        data={"selected": existing, "missing": missing},
        message=f"已选择 {len(existing)} 个对象",
    )

@tool(
    name="rename_object",
    description="重命名对象。",
    parameters=obj_schema(
        {
            "old_name": {"type": "string"},
            "new_name": {"type": "string"},
        },
        required=["old_name", "new_name"],
    ),
    category="scene",
)
def rename_object(old_name: str, new_name: str = "") -> ToolResult:
    c = _cmds()
    if not new_name:
        return ToolResult(ok=False, error="new_name 不能为空")
    if not c.objExists(old_name):
        return ToolResult(ok=False, error=f"不存在: {old_name}")
    result = c.rename(old_name, new_name)
    return ToolResult(ok=True, data=result, message=f"已重命名为 {result}")

@tool(
    name="batch_rename",
    description="批量重命名：前缀/后缀/序号替换。对当前选择或指定列表生效。",
    parameters=obj_schema(
        {
            "names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "为空则使用当前选择",
            },
            "prefix": {"type": "string", "default": ""},
            "suffix": {"type": "string", "default": ""},
            "replace_from": {"type": "string", "default": ""},
            "replace_to": {"type": "string", "default": ""},
            "start_number": {"type": "integer", "default": 1},
            "use_number": {"type": "boolean", "default": False},
            "padding": {"type": "integer", "default": 2},
        }
    ),
    category="scene",
)
def batch_rename(
    names: Optional[List[str]] = None,
    prefix: str = "",
    suffix: str = "",
    replace_from: str = "",
    replace_to: str = "",
    start_number: int = 1,
    use_number: bool = False,
    padding: int = 2,
) -> ToolResult:
    c = _cmds()
    targets = names or (c.ls(selection=True) or [])
    if not targets:
        return ToolResult(ok=False, error="无对象可重命名")
    renamed = []
    num = start_number
    for name in targets:
        short = name.split("|")[-1]
        base = short
        if replace_from:
            base = base.replace(replace_from, replace_to)
        if use_number:
            base = f"{prefix}{str(num).zfill(padding)}{suffix}"
            num += 1
        else:
            base = f"{prefix}{base}{suffix}"
        new = c.rename(name, base)
        renamed.append({"from": name, "to": new})
    return ToolResult(ok=True, data=renamed, message=f"已重命名 {len(renamed)} 个")

@tool(
    name="create_group",
    description="将当前选择或指定对象打组。",
    parameters=obj_schema(
        {
            "name": {"type": "string", "default": "grp_asset"},
            "names": {"type": "array", "items": {"type": "string"}, "default": []},
        }
    ),
    category="scene",
)
def create_group(name: str = "grp_asset", names: Optional[List[str]] = None) -> ToolResult:
    c = _cmds()
    if names:
        c.select(names, replace=True)
    if not c.ls(selection=True):
        return ToolResult(ok=False, error="没有可打组的对象")
    grp = c.group(name=name)
    return ToolResult(ok=True, data=grp, message=f"已创建组 {grp}")

@tool(
    name="delete_objects",
    description="删除指定对象（危险操作）。",
    parameters=obj_schema(
        {"names": {"type": "array", "items": {"type": "string"}}},
        required=["names"],
    ),
    category="scene",
    destructive=True,
)
def delete_objects(names: List[str]) -> ToolResult:
    c = _cmds()
    existing = [n for n in names if c.objExists(n)]
    if not existing:
        return ToolResult(ok=False, error="对象不存在")
    c.delete(existing)
    return ToolResult(ok=True, data=existing, message=f"已删除 {len(existing)} 个对象")

@tool(
    name="parent_objects",
    description="设置父子层级关系。",
    parameters=obj_schema(
        {
            "children": {"type": "array", "items": {"type": "string"}},
            "parent": {"type": "string"},
            "world": {
                "type": "boolean",
                "default": False,
                "description": "为 True 时取消父子关系放到世界空间",
            },
        },
        required=["children"],
    ),
    category="scene",
)
def parent_objects(
    children: List[str], parent: str = "", world: bool = False
) -> ToolResult:
    c = _cmds()
    if world:
        result = c.parent(children, world=True)
    else:
        if not parent or not c.objExists(parent):
            return ToolResult(ok=False, error="父对象无效")
        result = c.parent(children, parent)
    return ToolResult(ok=True, data=result, message="层级已更新")

@tool(
    name="duplicate_objects",
    description="复制对象。",
    parameters=obj_schema(
        {
            "names": {"type": "array", "items": {"type": "string"}, "default": []},
            "smart_transform": {"type": "boolean", "default": False},
            "input_connections": {"type": "boolean", "default": False},
        }
    ),
    category="scene",
)
def duplicate_objects(
    names: Optional[List[str]] = None,
    smart_transform: bool = False,
    input_connections: bool = False,
) -> ToolResult:
    c = _cmds()
    targets = names or (c.ls(selection=True) or [])
    if not targets:
        return ToolResult(ok=False, error="无对象可复制")
    result = c.duplicate(
        targets, smartTransform=smart_transform, inputConnections=input_connections
    )
    return ToolResult(ok=True, data=result, message=f"已复制: {result}")

@tool(
    name="clean_scene",
    description="清理场景：删除未知节点、空组、未使用的导入项（可选）。",
    parameters=obj_schema(
        {
            "delete_unknown": {"type": "boolean", "default": True},
            "delete_empty_groups": {"type": "boolean", "default": False},
            "optimize": {"type": "boolean", "default": True},
        }
    ),
    category="scene",
    destructive=True,
)
def clean_scene(
    delete_unknown: bool = True,
    delete_empty_groups: bool = False,
    optimize: bool = True,
) -> ToolResult:
    c = _cmds()
    removed = []
    if delete_unknown:
        unknown = c.ls(type="unknown") or []
        if unknown:
            c.delete(unknown)
            removed.extend(unknown)
    if delete_empty_groups:
        for t in c.ls(type="transform") or []:
            children = c.listRelatives(t, children=True) or []
            shapes = c.listRelatives(t, shapes=True) or []
            if not children and not shapes:
                try:
                    c.delete(t)
                    removed.append(t)
                except Exception:
                    pass
    if optimize:
        try:
            c.DgTimer(off=True)  # no-op guard
        except Exception:
            pass
        try:
            from maya_agent.utils.maya_compat import mel

            mel().eval('cleanUpScene 3;')
        except Exception:
            pass
    return ToolResult(ok=True, data={"removed": removed}, message="场景清理完成")

@tool(
    name="set_frame_range",
    description="设置时间轴帧范围与当前帧。",
    parameters=obj_schema(
        {
            "start": {"type": "number"},
            "end": {"type": "number"},
            "current": {"type": "number"},
        }
    ),
    category="scene",
)
def set_frame_range(
    start: Optional[float] = None,
    end: Optional[float] = None,
    current: Optional[float] = None,
) -> ToolResult:
    c = _cmds()
    if start is not None:
        c.playbackOptions(minTime=start, animationStartTime=start)
    if end is not None:
        c.playbackOptions(maxTime=end, animationEndTime=end)
    if current is not None:
        c.currentTime(current)
    data = {
        "min": c.playbackOptions(query=True, minTime=True),
        "max": c.playbackOptions(query=True, maxTime=True),
        "current": c.currentTime(query=True),
    }
    return ToolResult(ok=True, data=data, message="帧范围已更新")
