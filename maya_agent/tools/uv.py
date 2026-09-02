"""UV mapping tools."""

from __future__ import annotations

from typing import List, Optional

from maya_agent.tools.registry import ToolResult, obj_schema, tool
from maya_agent.tools._maya import cmds as _cmds

@tool(
    name="auto_unwrap_uv",
    description="自动展开 UV（planar / cylindrical / spherical / automatic）。",
    parameters=obj_schema(
        {
            "name": {"type": "string", "default": ""},
            "method": {
                "type": "string",
                "enum": ["automatic", "planar", "cylindrical", "spherical"],
                "default": "automatic",
            },
            "optimize": {"type": "boolean", "default": True},
        }
    ),
    category="uv",
)
def auto_unwrap_uv(name: str = "", method: str = "automatic", optimize: bool = True) -> ToolResult:
    c = _cmds()
    if name:
        c.select(name, replace=True)
    sel = c.ls(selection=True) or []
    if not sel:
        return ToolResult(ok=False, error="无选择")
    target = sel[0]
    if method == "automatic":
        c.polyAutoProjection(target, lm=0, pb=0, ibd=1, cm=0, l=2, sc=1, o=1, p=6, ps=0.2, ws=0)
    elif method == "planar":
        c.polyProjection(f"{target}.f[*]", type="Planar", md="y")
    elif method == "cylindrical":
        c.polyProjection(f"{target}.f[*]", type="Cylindrical")
    elif method == "spherical":
        c.polyProjection(f"{target}.f[*]", type="Spherical")
    if optimize:
        try:
            c.unfold(target, i=5000, ss=0.001, gb=0, gmb=0.5, pub=0, ps=0, oa=0, us=False)
            c.u3dLayout(target, res=256, scl=1, spc=0.006, mar=0.01)
        except Exception:
            pass
    return ToolResult(ok=True, data=target, message=f"UV 已用 {method} 展开")

@tool(
    name="layout_uv",
    description="排布 UV 岛到 0-1 空间。",
    parameters=obj_schema(
        {
            "names": {"type": "array", "items": {"type": "string"}, "default": []},
            "resolution": {"type": "integer", "default": 256},
            "spacing": {"type": "number", "default": 0.006},
        }
    ),
    category="uv",
)
def layout_uv(
    names: Optional[List[str]] = None,
    resolution: int = 256,
    spacing: float = 0.006,
) -> ToolResult:
    c = _cmds()
    targets = names or (c.ls(selection=True) or [])
    if not targets:
        return ToolResult(ok=False, error="无对象")
    for t in targets:
        try:
            c.u3dLayout(t, res=resolution, scl=1, spc=spacing, mar=0.01)
        except Exception:
            c.polyLayoutUV(t, scale=1, layout=2, percentageSpace=spacing * 100)
    return ToolResult(ok=True, data=targets, message="UV Layout 完成")

@tool(
    name="check_uv_overlaps",
    description="检查 UV 重叠（返回是否有重叠壳的提示）。",
    parameters=obj_schema({"name": {"type": "string", "default": ""}}),
    category="uv",
)
def check_uv_overlaps(name: str = "") -> ToolResult:
    c = _cmds()
    if name:
        c.select(name, replace=True)
    sel = c.ls(selection=True) or []
    if not sel:
        return ToolResult(ok=False, error="无选择")
    # Use UV shell count / polyEvaluate as lightweight check
    shells = c.polyEvaluate(sel[0], uvShell=True)
    uvs = c.polyEvaluate(sel[0], uvcoord=True)
    return ToolResult(
        ok=True,
        data={"uv_shells": shells, "uv_coords": uvs},
        message=f"UV Shells={shells}, UVCoords={uvs}（请在 UV 编辑器中确认重叠）",
    )
