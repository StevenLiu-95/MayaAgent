"""Factory tools: create_skeleton_* per template + list_skeleton_templates.

Pure maya.cmds — no AdvancedSkeleton MEL / .ma import at runtime.
"""

from __future__ import annotations

from typing import List, Optional

from maya_agent.tools.registry import ToolResult, obj_schema, tool
from maya_agent.tools.skeleton_templates import list_templates, template_payload
from maya_agent.tools.skeleton_templates.builder import build_skeleton


def _create_from_template(
    template_id: str,
    *,
    names: Optional[List[str]] = None,
    group_name: str = "DeformationSystem",
    orient: bool = False,
    scale: float = 1.0,
    fit_to_meshes: bool = False,
    name_prefix: str = "",
) -> ToolResult:
    try:
        joints, needs_mirror, label = template_payload(template_id)
    except (KeyError, ValueError) as e:
        return ToolResult(ok=False, error=str(e))
    fit = names if fit_to_meshes else None
    if fit_to_meshes and names is not None and len(names) == 0:
        fit = []  # means use selection
    try:
        data = build_skeleton(
            joints,
            root_group=group_name,
            needs_mirror=needs_mirror,
            orient=orient,
            fit_meshes=fit,
            scale=scale,
            name_prefix=name_prefix,
        )
    except Exception as e:
        return ToolResult(ok=False, error=str(e))
    data["template"] = template_id
    data["label"] = label
    return ToolResult(
        ok=True,
        data=data,
        message=f"已创建骨架模板「{label}」共 {data.get('count', 0)} 根骨骼"
        + (f"（前缀 {data.get('name_prefix')}）" if data.get("name_prefix") else ""),
    )


_COMMON_PARAMS = {
    "names": {
        "type": "array",
        "items": {"type": "string"},
        "default": [],
        "description": "用于适配包围盒的网格；fit_to_meshes=true 且为空则用当前选择",
    },
    "group_name": {"type": "string", "default": "DeformationSystem"},
    "orient": {
        "type": "boolean",
        "default": False,
        "description": "是否重新 orientJoint（默认保留模板 jointOrient）",
    },
    "scale": {"type": "number", "default": 1.0},
    "fit_to_meshes": {
        "type": "boolean",
        "default": False,
        "description": "按网格包围盒高度缩放并对齐骨架",
    },
    "name_prefix": {
        "type": "string",
        "default": "",
        "description": "关节名前缀；空且场景已有同名骨时自动加 skelN_，不会删除已有骨架",
    },
}


def _kwargs(
    names,
    group_name,
    orient,
    scale,
    fit_to_meshes,
    name_prefix,
):
    return dict(
        names=names,
        group_name=group_name,
        orient=orient,
        scale=scale,
        fit_to_meshes=fit_to_meshes,
        name_prefix=name_prefix,
    )


@tool(
    name="list_skeleton_templates",
    description=(
        "列出可用的原生骨架模板（不依赖 AdvancedSkeleton）。"
        "available=true 的可用 create_skeleton_<id> 创建。"
    ),
    parameters=obj_schema({}),
    category="rigging",
)
def list_skeleton_templates() -> ToolResult:
    rows = list_templates()
    avail = sum(1 for r in rows if r["available"])
    return ToolResult(
        ok=True,
        data={"templates": rows, "available_count": avail},
        message=f"共 {len(rows)} 个模板，其中 {avail} 个可用",
    )


@tool(
    name="create_skeleton_biped",
    description=(
        "创建标准双足模板骨架（ADV biped 拓扑，纯 cmds，不依赖 AdvancedSkeleton）。"
        "含脊柱/头/四肢/手指；自动镜像生成左侧。可 fit_to_meshes 对齐角色。"
    ),
    parameters=obj_schema(dict(_COMMON_PARAMS)),
    category="rigging",
    destructive=True,
)
def create_skeleton_biped(
    names: Optional[List[str]] = None,
    group_name: str = "DeformationSystem",
    orient: bool = False,
    scale: float = 1.0,
    fit_to_meshes: bool = False,
    name_prefix: str = "",
) -> ToolResult:
    return _create_from_template(
        "biped", **_kwargs(names, group_name, orient, scale, fit_to_meshes, name_prefix)
    )


@tool(
    name="create_skeleton_biped_game",
    description=(
        "创建游戏向双足模板骨架（ADV bipedGame：Spine1/2+Chest，无 Cup）。"
        "纯 cmds，不依赖 AdvancedSkeleton。"
    ),
    parameters=obj_schema(dict(_COMMON_PARAMS)),
    category="rigging",
    destructive=True,
)
def create_skeleton_biped_game(
    names: Optional[List[str]] = None,
    group_name: str = "DeformationSystem",
    orient: bool = False,
    scale: float = 1.0,
    fit_to_meshes: bool = False,
    name_prefix: str = "",
) -> ToolResult:
    return _create_from_template(
        "biped_game",
        **_kwargs(names, group_name, orient, scale, fit_to_meshes, name_prefix),
    )


@tool(
    name="create_skeleton_ue5",
    description=(
        "创建 UE5 Mannequin 风格模板骨架（多段 Spine）。纯 cmds，不依赖 AdvancedSkeleton。"
    ),
    parameters=obj_schema(dict(_COMMON_PARAMS)),
    category="rigging",
    destructive=True,
)
def create_skeleton_ue5(
    names: Optional[List[str]] = None,
    group_name: str = "DeformationSystem",
    orient: bool = False,
    scale: float = 1.0,
    fit_to_meshes: bool = False,
    name_prefix: str = "",
) -> ToolResult:
    return _create_from_template(
        "ue5", **_kwargs(names, group_name, orient, scale, fit_to_meshes, name_prefix)
    )


@tool(
    name="create_skeleton_cat",
    description="创建四足猫科模板骨架（含尾）。纯 cmds，不依赖 AdvancedSkeleton。",
    parameters=obj_schema(dict(_COMMON_PARAMS)),
    category="rigging",
    destructive=True,
)
def create_skeleton_cat(
    names: Optional[List[str]] = None,
    group_name: str = "DeformationSystem",
    orient: bool = False,
    scale: float = 1.0,
    fit_to_meshes: bool = False,
    name_prefix: str = "",
) -> ToolResult:
    return _create_from_template(
        "cat", **_kwargs(names, group_name, orient, scale, fit_to_meshes, name_prefix)
    )


@tool(
    name="create_skeleton_horse",
    description="创建四足有蹄（马）模板骨架（长颈+尾）。纯 cmds，不依赖 AdvancedSkeleton。",
    parameters=obj_schema(dict(_COMMON_PARAMS)),
    category="rigging",
    destructive=True,
)
def create_skeleton_horse(
    names: Optional[List[str]] = None,
    group_name: str = "DeformationSystem",
    orient: bool = False,
    scale: float = 1.0,
    fit_to_meshes: bool = False,
    name_prefix: str = "",
) -> ToolResult:
    return _create_from_template(
        "horse", **_kwargs(names, group_name, orient, scale, fit_to_meshes, name_prefix)
    )


def _register_template_tool(template_id: str, label: str, extra: str = ""):
    def _fn(
        names: Optional[List[str]] = None,
        group_name: str = "DeformationSystem",
        orient: bool = False,
        scale: float = 1.0,
        fit_to_meshes: bool = False,
        name_prefix: str = "",
    ) -> ToolResult:
        return _create_from_template(
            template_id,
            **_kwargs(names, group_name, orient, scale, fit_to_meshes, name_prefix),
        )

    _fn.__name__ = f"create_skeleton_{template_id}"
    desc = (
        f"创建「{label}」模板骨架（纯 cmds，不依赖 AdvancedSkeleton）。"
        f"{extra}可 fit_to_meshes 对齐角色。"
    )
    return tool(
        name=f"create_skeleton_{template_id}",
        description=desc,
        parameters=obj_schema(dict(_COMMON_PARAMS)),
        category="rigging",
        destructive=True,
    )(_fn)


for _tid, _label, _extra in (
    ("biped_bendy", "双足 Bendy", "含弯曲辅助骨拓扑；"),
    ("ue4", "UE4 Mannequin", ""),
    ("previs", "预演简化双足", "关节更少；"),
    ("gorilla", "类人猿", ""),
    ("bird", "鸟类", "含翅骨；"),
    ("fish", "鱼类", ""),
    ("bug", "昆虫", ""),
    ("dinosaur", "恐龙", ""),
    ("dragon", "龙", "含翅/尾；"),
    ("vehicle", "载具", "极简轮轴拓扑；"),
):
    _register_template_tool(_tid, _label, _extra)
