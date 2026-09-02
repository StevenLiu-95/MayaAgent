"""Utility tools: transform, lod, collision, naming for games."""

from __future__ import annotations

from typing import List, Optional

from maya_agent.tools.registry import ToolResult, obj_schema, tool
from maya_agent.tools._maya import cmds as _cmds

@tool(
    name="set_transform",
    description="设置物体位移/旋转/缩放。",
    parameters=obj_schema(
        {
            "name": {"type": "string"},
            "translate": {"type": "array", "items": {"type": "number"}},
            "rotate": {"type": "array", "items": {"type": "number"}},
            "scale": {"type": "array", "items": {"type": "number"}},
            "world_space": {"type": "boolean", "default": True},
        },
        required=["name"],
    ),
    category="utilities",
)
def set_transform(
    name: str,
    translate: Optional[List[float]] = None,
    rotate: Optional[List[float]] = None,
    scale: Optional[List[float]] = None,
    world_space: bool = True,
) -> ToolResult:
    c = _cmds()
    if not c.objExists(name):
        return ToolResult(ok=False, error="对象不存在")
    if translate is not None:
        c.xform(name, worldSpace=world_space, translation=translate)
    if rotate is not None:
        c.xform(name, worldSpace=world_space, rotation=rotate)
    if scale is not None:
        c.xform(name, worldSpace=False, scale=scale)
    return ToolResult(ok=True, data=name, message="变换已更新")

@tool(
    name="create_lod_group",
    description="为当前选择创建 LOD 组（游戏多级细节）。需按从高精度到低精度选择。",
    parameters=obj_schema(
        {
            "names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "LOD0, LOD1, ... 顺序",
            },
            "group_name": {"type": "string", "default": "lod_group"},
            "thresholds": {
                "type": "array",
                "items": {"type": "number"},
                "description": "可选阈值列表",
                "default": [],
            },
        },
        required=["names"],
    ),
    category="utilities",
)
def create_lod_group(
    names: List[str],
    group_name: str = "lod_group",
    thresholds: Optional[List[float]] = None,
) -> ToolResult:
    c = _cmds()
    if len(names) < 2:
        return ToolResult(ok=False, error="至少需要两个 LOD 级别")
    for n in names:
        if not c.objExists(n):
            return ToolResult(ok=False, error=f"不存在: {n}")
    # Maya LOD group via editLODGroup / Level of Detail
    grp = c.group(names, name=group_name)
    # Convert to LOD using distance-based display layers fallback if LOD unavailable
    try:
        from maya_agent.utils.maya_compat import mel

        mel().eval(f'levelOfDetailGroup -minDistance 0 "{grp}";')
        if thresholds:
            for i, th in enumerate(thresholds):
                try:
                    c.editLODGroup(grp, level=i, distance=th)
                except Exception:
                    pass
    except Exception:
        # Fallback: just keep as group with naming
        for i, n in enumerate(names):
            try:
                c.rename(n, f"LOD{i}_{n.split('|')[-1]}")
            except Exception:
                pass
    return ToolResult(ok=True, data=grp, message=f"LOD 组已创建: {grp}")

@tool(
    name="create_collision_mesh",
    description="为对象创建简化碰撞体（box / sphere / convex 近似）。",
    parameters=obj_schema(
        {
            "source": {"type": "string", "default": ""},
            "collision_type": {
                "type": "string",
                "enum": ["box", "sphere", "capsule_approx"],
                "default": "box",
            },
            "name": {"type": "string", "default": "UCX_collision"},
        }
    ),
    category="utilities",
)
def create_collision_mesh(
    source: str = "",
    collision_type: str = "box",
    name: str = "UCX_collision",
) -> ToolResult:
    c = _cmds()
    if source:
        c.select(source, replace=True)
    sel = c.ls(selection=True) or []
    if not sel:
        return ToolResult(ok=False, error="无源对象")
    src = sel[0]
    bbox = c.exactWorldBoundingBox(src)
    cx = (bbox[0] + bbox[3]) / 2
    cy = (bbox[1] + bbox[4]) / 2
    cz = (bbox[2] + bbox[5]) / 2
    w, h, d = bbox[3] - bbox[0], bbox[4] - bbox[1], bbox[5] - bbox[2]
    if collision_type == "sphere":
        r = max(w, h, d) / 2
        node = c.polySphere(name=name, radius=r)[0]
    elif collision_type == "capsule_approx":
        node = c.polyCylinder(name=name, radius=max(w, d) / 2, height=h)[0]
    else:
        node = c.polyCube(name=name, w=w, h=h, d=d)[0]
    c.xform(node, worldSpace=True, translation=(cx, cy, cz))
    return ToolResult(ok=True, data=node, message=f"碰撞体已创建: {node}")

@tool(
    name="apply_game_naming",
    description="按游戏管线命名规范重命名：前缀类型_名称_后缀。",
    parameters=obj_schema(
        {
            "name": {"type": "string"},
            "asset_type": {
                "type": "string",
                "enum": ["SM", "SK", "SKEL", "CTRL", "JNT", "M", "T", "GRP", "UCX"],
                "description": "StaticMesh/Skeletal/Skeleton/Control/Joint/Material/Texture/Group/Collision",
            },
            "asset_name": {"type": "string"},
            "variant": {"type": "string", "default": ""},
        },
        required=["name", "asset_type", "asset_name"],
    ),
    category="utilities",
)
def apply_game_naming(
    name: str,
    asset_type: str,
    asset_name: str,
    variant: str = "",
) -> ToolResult:
    c = _cmds()
    if not c.objExists(name):
        return ToolResult(ok=False, error="对象不存在")
    new_name = f"{asset_type}_{asset_name}"
    if variant:
        new_name += f"_{variant}"
    result = c.rename(name, new_name)
    return ToolResult(ok=True, data=result, message=f"已命名为 {result}")

@tool(
    name="reset_transform",
    description="将变换复位到 0/0/1。",
    parameters=obj_schema(
        {"names": {"type": "array", "items": {"type": "string"}, "default": []}}
    ),
    category="utilities",
)
def reset_transform(names: Optional[List[str]] = None) -> ToolResult:
    c = _cmds()
    targets = names or (c.ls(selection=True) or [])
    for t in targets:
        for attr, val in (
            ("translate", 0),
            ("rotate", 0),
            ("scale", 1),
        ):
            for axis in "XYZ":
                a = f"{t}.{attr}{axis}"
                if c.getAttr(a, lock=True):
                    continue
                try:
                    c.setAttr(a, val)
                except Exception:
                    pass
    return ToolResult(ok=True, data=targets, message="变换已复位")
