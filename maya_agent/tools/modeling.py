"""Modeling tools for mesh creation and editing."""

from __future__ import annotations

from typing import List, Optional

from maya_agent.tools.registry import ToolResult, obj_schema, tool
from maya_agent.tools._maya import cmds as _cmds

@tool(
    name="create_primitive",
    description="创建基础几何体：cube/sphere/cylinder/plane/cone/torus/disk。",
    parameters=obj_schema(
        {
            "primitive": {
                "type": "string",
                "enum": ["cube", "sphere", "cylinder", "plane", "cone", "torus", "disk"],
            },
            "name": {"type": "string", "default": ""},
            "subdivisions": {"type": "integer", "default": 8},
            "width": {"type": "number", "default": 1},
            "height": {"type": "number", "default": 1},
            "depth": {"type": "number", "default": 1},
            "radius": {"type": "number", "default": 1},
        },
        required=["primitive"],
    ),
    category="modeling",
)
def create_primitive(
    primitive: str,
    name: str = "",
    subdivisions: int = 8,
    width: float = 1,
    height: float = 1,
    depth: float = 1,
    radius: float = 1,
) -> ToolResult:
    c = _cmds()
    creators = {
        "cube": lambda: c.polyCube(w=width, h=height, d=depth, name=name or "pCube"),
        "sphere": lambda: c.polySphere(r=radius, sx=subdivisions, sy=subdivisions, name=name or "pSphere"),
        "cylinder": lambda: c.polyCylinder(r=radius, h=height, sx=subdivisions, name=name or "pCylinder"),
        "plane": lambda: c.polyPlane(w=width, h=height, sx=subdivisions, sy=subdivisions, name=name or "pPlane"),
        "cone": lambda: c.polyCone(r=radius, h=height, sx=subdivisions, name=name or "pCone"),
        "torus": lambda: c.polyTorus(r=radius, sr=radius * 0.25, name=name or "pTorus"),
        "disk": lambda: c.polyDisc(radius=radius, name=name or "pDisc") if hasattr(c, "polyDisc") else c.polyCylinder(r=radius, h=0.01, sx=subdivisions, name=name or "pDisk"),
    }
    if primitive not in creators:
        return ToolResult(ok=False, error=f"不支持的原始体: {primitive}")
    result = creators[primitive]()
    return ToolResult(ok=True, data=result, message=f"已创建 {primitive}: {result[0]}")

@tool(
    name="combine_meshes",
    description="合并多个多边形网格为一个。",
    parameters=obj_schema(
        {
            "names": {"type": "array", "items": {"type": "string"}, "default": []},
            "new_name": {"type": "string", "default": ""},
        }
    ),
    category="modeling",
)
def combine_meshes(names: Optional[List[str]] = None, new_name: str = "") -> ToolResult:
    c = _cmds()
    targets = names or (c.ls(selection=True, type="transform") or [])
    if len(targets) < 2:
        return ToolResult(ok=False, error="至少需要两个对象进行合并")
    c.select(targets, replace=True)
    result = c.polyUnite(ch=True)
    if new_name:
        result = [c.rename(result[0], new_name)] + list(result[1:])
    return ToolResult(ok=True, data=result, message=f"已合并为 {result[0]}")

@tool(
    name="separate_meshes",
    description="分离多边形壳为独立对象。",
    parameters=obj_schema(
        {"name": {"type": "string", "description": "为空则使用当前选择", "default": ""}}
    ),
    category="modeling",
)
def separate_meshes(name: str = "") -> ToolResult:
    c = _cmds()
    if name:
        c.select(name, replace=True)
    sel = c.ls(selection=True) or []
    if not sel:
        return ToolResult(ok=False, error="无选择")
    result = c.polySeparate(sel[0])
    return ToolResult(ok=True, data=result, message=f"已分离为 {len(result)} 部分")

@tool(
    name="boolean_meshes",
    description="布尔运算：union / difference / intersection。",
    parameters=obj_schema(
        {
            "mesh_a": {"type": "string"},
            "mesh_b": {"type": "string"},
            "operation": {
                "type": "string",
                "enum": ["union", "difference", "intersection"],
                "default": "difference",
            },
        },
        required=["mesh_a", "mesh_b"],
    ),
    category="modeling",
)
def boolean_meshes(mesh_a: str, mesh_b: str, operation: str = "difference") -> ToolResult:
    c = _cmds()
    op_map = {"union": 1, "difference": 2, "intersection": 3}
    if operation not in op_map:
        return ToolResult(ok=False, error="无效操作")
    # Prefer modern boolean
    try:
        result = c.polyCBoolOp(mesh_a, mesh_b, op=op_map[operation], ch=True)
    except Exception:
        result = c.polyBoolOp(mesh_a, mesh_b, op=op_map[operation])
    return ToolResult(ok=True, data=result, message=f"布尔 {operation} 完成: {result[0]}")

@tool(
    name="extrude_faces",
    description="挤出当前选中的面（或指定网格所有面需先选面）。",
    parameters=obj_schema(
        {
            "thickness": {"type": "number", "default": 0.2},
            "offset": {"type": "number", "default": 0.0},
            "divisions": {"type": "integer", "default": 1},
        }
    ),
    category="modeling",
)
def extrude_faces(thickness: float = 0.2, offset: float = 0.0, divisions: int = 1) -> ToolResult:
    c = _cmds()
    sel = c.ls(selection=True, flatten=True) or []
    if not sel:
        return ToolResult(ok=False, error="请先选择面")
    result = c.polyExtrudeFacet(sel, ltz=thickness, offset=offset, divisions=divisions)
    return ToolResult(ok=True, data=result, message="挤出完成")

@tool(
    name="bevel_edges",
    description="对选中边做 Bevel。",
    parameters=obj_schema(
        {
            "offset": {"type": "number", "default": 0.1},
            "segments": {"type": "integer", "default": 1},
            "fraction": {"type": "number", "default": 0.5},
        }
    ),
    category="modeling",
)
def bevel_edges(offset: float = 0.1, segments: int = 1, fraction: float = 0.5) -> ToolResult:
    c = _cmds()
    sel = c.ls(selection=True, flatten=True) or []
    if not sel:
        return ToolResult(ok=False, error="请先选择边")
    result = c.polyBevel3(sel, offset=offset, segments=segments, fraction=fraction)
    return ToolResult(ok=True, data=result, message="Bevel 完成")

@tool(
    name="smooth_mesh",
    description="平滑网格（细分或软化法线）。",
    parameters=obj_schema(
        {
            "names": {"type": "array", "items": {"type": "string"}, "default": []},
            "divisions": {"type": "integer", "default": 1},
            "keep_border": {"type": "boolean", "default": True},
        }
    ),
    category="modeling",
)
def smooth_mesh(
    names: Optional[List[str]] = None,
    divisions: int = 1,
    keep_border: bool = True,
) -> ToolResult:
    c = _cmds()
    targets = names or (c.ls(selection=True) or [])
    if not targets:
        return ToolResult(ok=False, error="无对象")
    results = []
    for t in targets:
        results.append(c.polySmooth(t, divisions=divisions, keepBorder=keep_border))
    return ToolResult(ok=True, data=results, message=f"已平滑 {len(targets)} 个对象")

@tool(
    name="reduce_mesh",
    description="减面（适合游戏 LOD）。",
    parameters=obj_schema(
        {
            "name": {"type": "string", "default": ""},
            "percentage": {
                "type": "number",
                "description": "保留百分比 0-100",
                "default": 50,
            },
            "keep_quads": {"type": "boolean", "default": True},
        }
    ),
    category="modeling",
)
def reduce_mesh(name: str = "", percentage: float = 50, keep_quads: bool = True) -> ToolResult:
    c = _cmds()
    if name:
        c.select(name, replace=True)
    sel = c.ls(selection=True) or []
    if not sel:
        return ToolResult(ok=False, error="无选择")
    result = c.polyReduce(
        sel[0],
        percentage=100 - percentage,
        keepQuadsWeight=1 if keep_quads else 0,
        keepBorder=True,
        cachingReduce=True,
    )
    return ToolResult(ok=True, data=result, message=f"减面完成，保留约 {percentage}%")

@tool(
    name="mirror_geometry",
    description="镜像几何体。",
    parameters=obj_schema(
        {
            "name": {"type": "string", "default": ""},
            "axis": {"type": "string", "enum": ["x", "y", "z"], "default": "x"},
            "merge_mode": {"type": "integer", "default": 1, "description": "0=不合并,1=合并边界"},
            "merge_threshold": {"type": "number", "default": 0.001},
        }
    ),
    category="modeling",
)
def mirror_geometry(
    name: str = "",
    axis: str = "x",
    merge_mode: int = 1,
    merge_threshold: float = 0.001,
) -> ToolResult:
    c = _cmds()
    if name:
        c.select(name, replace=True)
    sel = c.ls(selection=True) or []
    if not sel:
        return ToolResult(ok=False, error="无选择")
    axis_map = {"x": 0, "y": 1, "z": 2}
    result = c.polyMirrorFace(
        sel[0],
        direction=axis_map.get(axis, 0),
        mergeMode=merge_mode,
        mergeThreshold=merge_threshold,
    )
    return ToolResult(ok=True, data=result, message=f"已沿 {axis} 镜像")

@tool(
    name="center_pivot",
    description="将枢轴居中到物体包围盒中心，或移到世界原点。",
    parameters=obj_schema(
        {
            "names": {"type": "array", "items": {"type": "string"}, "default": []},
            "to_world_origin": {"type": "boolean", "default": False},
        }
    ),
    category="modeling",
)
def center_pivot(names: Optional[List[str]] = None, to_world_origin: bool = False) -> ToolResult:
    c = _cmds()
    targets = names or (c.ls(selection=True) or [])
    if not targets:
        return ToolResult(ok=False, error="无对象")
    for t in targets:
        if to_world_origin:
            c.xform(t, pivots=(0, 0, 0), worldSpace=True)
        else:
            c.xform(t, centerPivots=True)
    return ToolResult(ok=True, data=targets, message="枢轴已更新")

@tool(
    name="freeze_transform",
    description="冻结变换（游戏导出前常用）。",
    parameters=obj_schema(
        {
            "names": {"type": "array", "items": {"type": "string"}, "default": []},
            "translate": {"type": "boolean", "default": True},
            "rotate": {"type": "boolean", "default": True},
            "scale": {"type": "boolean", "default": True},
        }
    ),
    category="modeling",
)
def freeze_transform(
    names: Optional[List[str]] = None,
    translate: bool = True,
    rotate: bool = True,
    scale: bool = True,
) -> ToolResult:
    c = _cmds()
    targets = names or (c.ls(selection=True) or [])
    if not targets:
        return ToolResult(ok=False, error="无对象")
    c.makeIdentity(targets, apply=True, t=translate, r=rotate, s=scale, n=0)
    return ToolResult(ok=True, data=targets, message="变换已冻结")

@tool(
    name="get_mesh_stats",
    description="获取网格拓扑统计：顶点数、面数、三角面数、是否有非流形等。",
    parameters=obj_schema(
        {"name": {"type": "string", "default": "", "description": "为空则用当前选择"}}
    ),
    category="modeling",
)
def get_mesh_stats(name: str = "") -> ToolResult:
    c = _cmds()
    if name:
        c.select(name, replace=True)
    sel = c.ls(selection=True, long=True) or []
    if not sel:
        return ToolResult(ok=False, error="无选择")
    node = sel[0]
    shapes = c.listRelatives(node, shapes=True, fullPath=True) or [node]
    shape = shapes[0]
    verts = c.polyEvaluate(shape, vertex=True)
    edges = c.polyEvaluate(shape, edge=True)
    faces = c.polyEvaluate(shape, face=True)
    tris = c.polyEvaluate(shape, triangle=True)
    uv = c.polyEvaluate(shape, uvcoord=True)
    data = {
        "node": node,
        "shape": shape,
        "vertices": verts,
        "edges": edges,
        "faces": faces,
        "triangles": tris,
        "uvs": uv,
    }
    return ToolResult(ok=True, data=data, message="网格统计完成")
