"""Animation tools."""

from __future__ import annotations

from typing import List, Optional

from maya_agent.tools.registry import ToolResult, obj_schema, tool
from maya_agent.tools._maya import cmds as _cmds

@tool(
    name="set_keyframe",
    description="为对象属性打关键帧。",
    parameters=obj_schema(
        {
            "names": {"type": "array", "items": {"type": "string"}, "default": []},
            "attribute": {
                "type": "string",
                "default": "",
                "description": "如 translateX；空则对常用变换打关键",
            },
            "time": {"type": "number", "description": "空则当前帧"},
            "value": {"type": "number", "description": "可选，设置属性值后再打关键"},
        }
    ),
    category="animation",
)
def set_keyframe(
    names: Optional[List[str]] = None,
    attribute: str = "",
    time: Optional[float] = None,
    value: Optional[float] = None,
) -> ToolResult:
    c = _cmds()
    targets = names or (c.ls(selection=True) or [])
    if not targets:
        return ToolResult(ok=False, error="无对象")
    keyed = []
    for t in targets:
        kwargs = {"time": time} if time is not None else {}
        if attribute:
            if value is not None:
                c.setAttr(f"{t}.{attribute}", value)
            c.setKeyframe(t, attribute=attribute, **kwargs)
            keyed.append(f"{t}.{attribute}")
        else:
            c.setKeyframe(t, **kwargs)
            keyed.append(t)
    return ToolResult(ok=True, data=keyed, message=f"已打关键 {len(keyed)} 项")

@tool(
    name="delete_keyframes",
    description="删除对象上的关键帧。",
    parameters=obj_schema(
        {
            "names": {"type": "array", "items": {"type": "string"}, "default": []},
            "time_start": {"type": "number"},
            "time_end": {"type": "number"},
            "attribute": {"type": "string", "default": ""},
        }
    ),
    category="animation",
    destructive=True,
)
def delete_keyframes(
    names: Optional[List[str]] = None,
    time_start: Optional[float] = None,
    time_end: Optional[float] = None,
    attribute: str = "",
) -> ToolResult:
    c = _cmds()
    targets = names or (c.ls(selection=True) or [])
    if not targets:
        return ToolResult(ok=False, error="无对象")
    for t in targets:
        kwargs = {}
        if time_start is not None and time_end is not None:
            kwargs["time"] = (time_start, time_end)
        if attribute:
            kwargs["attribute"] = attribute
        c.cutKey(t, **kwargs)
    return ToolResult(ok=True, data=targets, message="关键帧已删除")

@tool(
    name="bake_animation",
    description="烘焙动画到指定帧范围。",
    parameters=obj_schema(
        {
            "names": {"type": "array", "items": {"type": "string"}, "default": []},
            "start": {"type": "number"},
            "end": {"type": "number"},
            "step": {"type": "number", "default": 1},
        },
        required=["start", "end"],
    ),
    category="animation",
)
def bake_animation(
    names: Optional[List[str]] = None,
    start: float = 1,
    end: float = 100,
    step: float = 1,
) -> ToolResult:
    c = _cmds()
    targets = names or (c.ls(selection=True) or [])
    if not targets:
        return ToolResult(ok=False, error="无对象")
    c.bakeResults(
        targets,
        simulation=True,
        time=(start, end),
        sampleBy=step,
        oversamplingRate=1,
        disableImplicitControl=True,
        preserveOutsideKeys=True,
        sparseAnimCurveBake=False,
        removeBakedAttributeFromLayer=False,
        removeBakedAnimFromLayer=False,
        bakeOnOverrideLayer=False,
        minimizeRotation=True,
        controlPoints=False,
        shape=True,
    )
    return ToolResult(ok=True, data=targets, message=f"已烘焙 {start}-{end}")

@tool(
    name="playblast",
    description="生成 Playblast 预览视频/序列。",
    parameters=obj_schema(
        {
            "output_path": {"type": "string", "description": "输出路径，无扩展名也可"},
            "format": {
                "type": "string",
                "enum": ["qt", "avi", "image"],
                "default": "qt",
            },
            "width": {"type": "integer", "default": 1280},
            "height": {"type": "integer", "default": 720},
            "start": {"type": "number"},
            "end": {"type": "number"},
            "show_ornaments": {"type": "boolean", "default": False},
        },
        required=["output_path"],
    ),
    category="animation",
)
def playblast(
    output_path: str,
    format: str = "qt",
    width: int = 1280,
    height: int = 720,
    start: Optional[float] = None,
    end: Optional[float] = None,
    show_ornaments: bool = False,
) -> ToolResult:
    c = _cmds()
    kwargs = dict(
        filename=output_path,
        format=format,
        width=width,
        height=height,
        showOrnaments=show_ornaments,
        forceOverwrite=True,
        viewer=False,
        percent=100,
        quality=90,
    )
    if start is not None and end is not None:
        kwargs["startTime"] = start
        kwargs["endTime"] = end
    path = c.playblast(**kwargs)
    return ToolResult(ok=True, data=path, message=f"Playblast 已输出: {path}")

@tool(
    name="copy_animation",
    description="将源对象动画复制到目标对象（同名属性）。",
    parameters=obj_schema(
        {
            "source": {"type": "string"},
            "target": {"type": "string"},
        },
        required=["source", "target"],
    ),
    category="animation",
)
def copy_animation(source: str, target: str) -> ToolResult:
    c = _cmds()
    c.copyKey(source, time=(":",), option="curve")
    c.pasteKey(target, option="replace")
    return ToolResult(ok=True, message=f"动画已从 {source} 复制到 {target}")
