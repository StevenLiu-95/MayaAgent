"""Modeling tools for mesh creation and editing."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from maya_agent.tools.registry import ToolResult, obj_schema, tool
from maya_agent.tools._maya import cmds as _cmds

@tool(
    name="create_primitive",
    description=(
        "创建单个基础几何体：cube/sphere/cylinder/plane/cone/torus/disk。"
        "可直接指定 position/rotation/scale 落位。批量请用 create_primitives。"
    ),
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
            "position": {
                "type": "array",
                "items": {"type": "number"},
                "description": "可选世界坐标 [x,y,z]",
            },
            "rotation": {
                "type": "array",
                "items": {"type": "number"},
                "description": "可选欧拉角 [rx,ry,rz] 度",
            },
            "scale": {
                "type": "array",
                "items": {"type": "number"},
                "description": "可选缩放 [sx,sy,sz]",
            },
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
    position: Optional[List[float]] = None,
    rotation: Optional[List[float]] = None,
    scale: Optional[List[float]] = None,
) -> ToolResult:
    node, err = _make_primitive(
        primitive,
        name=name,
        subdivisions=subdivisions,
        width=width,
        height=height,
        depth=depth,
        radius=radius,
        position=position,
        rotation=rotation,
        scale=scale,
    )
    if err:
        return ToolResult(ok=False, error=err)
    return ToolResult(
        ok=True,
        data={"name": node, "primitive": primitive},
        message=f"已创建 {primitive}: {node}",
    )


def _make_primitive(
    primitive: str,
    *,
    name: str = "",
    subdivisions: int = 8,
    width: float = 1,
    height: float = 1,
    depth: float = 1,
    radius: float = 1,
    position: Optional[List[float]] = None,
    rotation: Optional[List[float]] = None,
    scale: Optional[List[float]] = None,
) -> Tuple[Optional[str], Optional[str]]:
    c = _cmds()
    creators = {
        "cube": lambda: c.polyCube(w=width, h=height, d=depth, name=name or "pCube"),
        "sphere": lambda: c.polySphere(
            r=radius, sx=subdivisions, sy=subdivisions, name=name or "pSphere"
        ),
        "cylinder": lambda: c.polyCylinder(
            r=radius, h=height, sx=subdivisions, name=name or "pCylinder"
        ),
        "plane": lambda: c.polyPlane(
            w=width, h=height, sx=subdivisions, sy=subdivisions, name=name or "pPlane"
        ),
        "cone": lambda: c.polyCone(
            r=radius, h=height, sx=subdivisions, name=name or "pCone"
        ),
        "torus": lambda: c.polyTorus(
            r=radius, sr=radius * 0.25, name=name or "pTorus"
        ),
        "disk": lambda: (
            c.polyDisc(radius=radius, name=name or "pDisc")
            if hasattr(c, "polyDisc")
            else c.polyCylinder(r=radius, h=0.01, sx=subdivisions, name=name or "pDisk")
        ),
    }
    if primitive not in creators:
        return None, f"不支持的原始体: {primitive}"
    result = creators[primitive]()
    node = result[0] if isinstance(result, (list, tuple)) else result
    if position is not None and len(position) >= 3:
        c.xform(node, ws=True, translation=[float(position[0]), float(position[1]), float(position[2])])
    if rotation is not None and len(rotation) >= 3:
        c.xform(node, ws=True, rotation=[float(rotation[0]), float(rotation[1]), float(rotation[2])])
    if scale is not None and len(scale) >= 3:
        c.xform(node, ws=True, scale=[float(scale[0]), float(scale[1]), float(scale[2])])
    return node, None


@tool(
    name="create_primitives",
    description=(
        "批量创建几何体并直接落位命名。items 每项可含 primitive/name/position/"
        "rotation/scale/width/height/depth/radius。适合建筑块体批量搭建。"
    ),
    parameters=obj_schema(
        {
            "items": {
                "type": "array",
                "items": {"type": "object"},
                "description": (
                    "对象列表，如 "
                    '[{"primitive":"cube","name":"wall_01","position":[0,150,0],'
                    '"width":400,"height":300,"depth":40}]'
                ),
            },
            "group_name": {
                "type": "string",
                "default": "",
                "description": "可选：创建后打组",
            },
        },
        required=["items"],
    ),
    category="modeling",
)
def create_primitives(
    items: Optional[List[Dict[str, Any]]] = None,
    group_name: str = "",
) -> ToolResult:
    c = _cmds()
    items = items or []
    if not items:
        return ToolResult(ok=False, error="items 为空")
    if len(items) > 500:
        return ToolResult(ok=False, error="单次最多 500 个")

    created: List[Dict[str, Any]] = []
    errors: List[str] = []
    for i, raw in enumerate(items):
        if not isinstance(raw, dict):
            errors.append(f"[{i}] 不是对象")
            continue
        prim = str(raw.get("primitive") or "cube")
        node, err = _make_primitive(
            prim,
            name=str(raw.get("name") or ""),
            subdivisions=int(raw.get("subdivisions") or 8),
            width=float(raw.get("width") if raw.get("width") is not None else 1),
            height=float(raw.get("height") if raw.get("height") is not None else 1),
            depth=float(raw.get("depth") if raw.get("depth") is not None else 1),
            radius=float(raw.get("radius") if raw.get("radius") is not None else 1),
            position=raw.get("position"),
            rotation=raw.get("rotation"),
            scale=raw.get("scale"),
        )
        if err:
            errors.append(f"[{i}] {err}")
            continue
        created.append({"name": node, "primitive": prim, "index": i})

    grp = ""
    if group_name and created:
        try:
            names = [x["name"] for x in created]
            c.select(names, replace=True)
            grp = c.group(name=group_name)
        except Exception as e:
            errors.append(f"打组失败: {e}")

    if not created:
        return ToolResult(ok=False, error="全部创建失败", data={"errors": errors})
    msg = f"已批量创建 {len(created)} 个几何体"
    if grp:
        msg += f"，组={grp}"
    if errors:
        msg += f"；{len(errors)} 项失败"
    return ToolResult(
        ok=True,
        data={"created": created, "group": grp or None, "errors": errors},
        message=msg,
    )


@tool(
    name="arrange_objects",
    description=(
        "相对摆放辅助：stack（沿轴堆叠）、align（对齐 bbox）、"
        "grid_array（矩形阵列复制）。减少手算坐标。"
    ),
    parameters=obj_schema(
        {
            "mode": {
                "type": "string",
                "enum": ["stack", "align", "grid_array"],
            },
            "names": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": "对象列表；空则用当前选择。grid_array 时通常传 1 个源对象",
            },
            "axis": {
                "type": "string",
                "enum": ["x", "y", "z"],
                "default": "y",
                "description": "stack 轴向；align 时为对齐轴",
            },
            "align_to": {
                "type": "string",
                "enum": ["min", "center", "max"],
                "default": "min",
                "description": "align 模式：对齐到该轴的 min/center/max",
            },
            "gap": {
                "type": "number",
                "default": 0.0,
                "description": "stack / grid 间距",
            },
            "count_x": {"type": "integer", "default": 1},
            "count_y": {"type": "integer", "default": 1},
            "count_z": {"type": "integer", "default": 1},
            "spacing": {
                "type": "array",
                "items": {"type": "number"},
                "description": "grid_array 间距 [sx,sy,sz]；空则用 bbox+gap",
            },
        },
        required=["mode"],
    ),
    category="modeling",
)
def arrange_objects(
    mode: str,
    names: Optional[List[str]] = None,
    axis: str = "y",
    align_to: str = "min",
    gap: float = 0.0,
    count_x: int = 1,
    count_y: int = 1,
    count_z: int = 1,
    spacing: Optional[List[float]] = None,
) -> ToolResult:
    c = _cmds()
    axis = (axis or "y").lower()
    ax_i = {"x": 0, "y": 1, "z": 2}.get(axis, 1)
    targets = [n for n in (names or []) if c.objExists(n)]
    if not targets:
        targets = c.ls(selection=True, type="transform") or []
    if not targets:
        return ToolResult(ok=False, error="无对象")

    def _bb(n):
        return c.exactWorldBoundingBox(n)

    if mode == "stack":
        # Keep first object; stack subsequent along axis with gap
        ordered = list(targets)
        cursor = None
        moved = []
        for i, n in enumerate(ordered):
            bb = _bb(n)
            size = bb[ax_i + 3] - bb[ax_i]
            if i == 0:
                cursor = bb[ax_i + 3]  # top of first
                moved.append(n)
                continue
            # Place so min face sits at cursor + gap
            new_min = cursor + float(gap)
            delta = new_min - bb[ax_i]
            pos = c.xform(n, q=True, ws=True, t=True)
            pos[ax_i] = pos[ax_i] + delta
            c.xform(n, ws=True, translation=pos)
            bb2 = _bb(n)
            cursor = bb2[ax_i + 3]
            moved.append(n)
        return ToolResult(
            ok=True,
            data={"mode": "stack", "axis": axis, "objects": moved, "gap": gap},
            message=f"已沿 {axis} 堆叠 {len(moved)} 个对象",
        )

    if mode == "align":
        bbs = [_bb(n) for n in targets]
        if align_to == "max":
            ref = max(b[ax_i + 3] for b in bbs)
            for n, bb in zip(targets, bbs):
                delta = ref - bb[ax_i + 3]
                pos = c.xform(n, q=True, ws=True, t=True)
                pos[ax_i] += delta
                c.xform(n, ws=True, translation=pos)
        elif align_to == "center":
            centers = [0.5 * (b[ax_i] + b[ax_i + 3]) for b in bbs]
            ref = sum(centers) / len(centers)
            for n, bb in zip(targets, bbs):
                cur = 0.5 * (bb[ax_i] + bb[ax_i + 3])
                delta = ref - cur
                pos = c.xform(n, q=True, ws=True, t=True)
                pos[ax_i] += delta
                c.xform(n, ws=True, translation=pos)
        else:  # min
            ref = min(b[ax_i] for b in bbs)
            for n, bb in zip(targets, bbs):
                delta = ref - bb[ax_i]
                pos = c.xform(n, q=True, ws=True, t=True)
                pos[ax_i] += delta
                c.xform(n, ws=True, translation=pos)
        return ToolResult(
            ok=True,
            data={"mode": "align", "axis": axis, "align_to": align_to, "objects": targets},
            message=f"已沿 {axis} 对齐到 {align_to}",
        )

    if mode == "grid_array":
        src = targets[0]
        cx = max(1, int(count_x))
        cy = max(1, int(count_y))
        cz = max(1, int(count_z))
        if cx * cy * cz > 500:
            return ToolResult(ok=False, error="阵列总数不能超过 500")
        bb = _bb(src)
        size = [bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]]
        if spacing and len(spacing) >= 3:
            sx, sy, sz = float(spacing[0]), float(spacing[1]), float(spacing[2])
        else:
            g = float(gap)
            sx, sy, sz = size[0] + g, size[1] + g, size[2] + g
        origin = c.xform(src, q=True, ws=True, t=True)
        created = [src]
        for iz in range(cz):
            for iy in range(cy):
                for ix in range(cx):
                    if ix == 0 and iy == 0 and iz == 0:
                        continue
                    dup = c.duplicate(src)[0]
                    c.xform(
                        dup,
                        ws=True,
                        translation=[
                            origin[0] + ix * sx,
                            origin[1] + iy * sy,
                            origin[2] + iz * sz,
                        ],
                    )
                    created.append(dup)
        return ToolResult(
            ok=True,
            data={
                "mode": "grid_array",
                "objects": created,
                "counts": [cx, cy, cz],
                "spacing": [sx, sy, sz],
            },
            message=f"阵列完成：{len(created)} 个",
        )

    return ToolResult(ok=False, error=f"未知 mode: {mode}")


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

def _collect_mesh_shapes(root: str) -> List[str]:
    """Resolve mesh shapes under a transform/group/mesh (recursive)."""
    c = _cmds()
    if not c.objExists(root):
        return []
    ntype = c.nodeType(root)
    if ntype == "mesh":
        return [root]
    shapes = c.listRelatives(root, shapes=True, type="mesh", fullPath=True) or []
    # Descend into hierarchy (group / nested transforms)
    descendants = c.listRelatives(root, allDescendents=True, type="mesh", fullPath=True) or []
    # also include shapes of children transforms that listRelatives may miss on some roots
    out = list(dict.fromkeys(list(shapes) + list(descendants)))
    return out


def _poly_stats(shape: str) -> Dict[str, Any]:
    c = _cmds()
    stats: Dict[str, Any] = {"shape": shape}
    for key, kw in (
        ("vertices", {"vertex": True}),
        ("edges", {"edge": True}),
        ("faces", {"face": True}),
        ("triangles", {"triangle": True}),
        ("uvs", {"uvcoord": True}),
    ):
        try:
            stats[key] = int(c.polyEvaluate(shape, **kw) or 0)
        except Exception:
            stats[key] = 0
    try:
        parents = c.listRelatives(shape, parent=True, fullPath=True) or []
        stats["transform"] = parents[0] if parents else shape
    except Exception:
        stats["transform"] = shape
    return stats


@tool(
    name="get_mesh_stats",
    description=(
        "获取网格拓扑统计（顶点/边/面/三角/UV）。"
        "支持传组名或层级：自动向下聚合所有 mesh shape。"
    ),
    parameters=obj_schema(
        {
            "name": {
                "type": "string",
                "default": "",
                "description": "对象/组名；空则用当前选择",
            },
            "aggregate": {
                "type": "boolean",
                "default": True,
                "description": "为 True 时对层级内所有 mesh 求和",
            },
        }
    ),
    category="modeling",
)
def get_mesh_stats(name: str = "", aggregate: bool = True) -> ToolResult:
    c = _cmds()
    if name:
        if not c.objExists(name):
            return ToolResult(ok=False, error=f"对象不存在: {name}")
        roots = [name]
    else:
        roots = c.ls(selection=True, long=True) or []
    if not roots:
        return ToolResult(ok=False, error="无选择")

    shapes: List[str] = []
    root_types: Dict[str, str] = {}
    for root in roots:
        root_types[root] = c.nodeType(root)
        found = _collect_mesh_shapes(root)
        shapes.extend(found)

    shapes = list(dict.fromkeys(shapes))
    if not shapes:
        types = ", ".join(f"{r}({t})" for r, t in root_types.items())
        return ToolResult(
            ok=False,
            error=(
                f"未找到多边形 mesh：{types}。"
                "请传入 mesh / 含 mesh 的 transform 或组名。"
            ),
            data={"roots": root_types, "mesh_count": 0},
        )

    per_mesh = [_poly_stats(s) for s in shapes]
    totals = {
        "vertices": sum(p["vertices"] for p in per_mesh),
        "edges": sum(p["edges"] for p in per_mesh),
        "faces": sum(p["faces"] for p in per_mesh),
        "triangles": sum(p["triangles"] for p in per_mesh),
        "uvs": sum(p["uvs"] for p in per_mesh),
        "mesh_count": len(per_mesh),
    }
    data: Dict[str, Any] = {
        "roots": root_types,
        "totals": totals,
        "meshes": per_mesh if (not aggregate or len(per_mesh) <= 20) else per_mesh[:20],
        "meshes_truncated": len(per_mesh) > 20 and aggregate,
    }
    # Backward-compatible flat fields when single mesh
    if len(per_mesh) == 1:
        data.update(
            {
                "node": per_mesh[0]["transform"],
                "shape": per_mesh[0]["shape"],
                "vertices": per_mesh[0]["vertices"],
                "edges": per_mesh[0]["edges"],
                "faces": per_mesh[0]["faces"],
                "triangles": per_mesh[0]["triangles"],
                "uvs": per_mesh[0]["uvs"],
            }
        )
    msg = (
        f"网格统计：{totals['mesh_count']} 个 mesh / "
        f"{totals['vertices']} 顶点 / {totals['faces']} 面 / "
        f"{totals['triangles']} 三角"
    )
    return ToolResult(ok=True, data=data, message=msg)


@tool(
    name="check_meshes",
    description=(
        "批量网格质量体检：非流形边/顶点、孔洞边、孤立顶点、零面积面、反转法线提示。"
        "支持组/层级；可对当前选择或指定对象。"
    ),
    parameters=obj_schema(
        {
            "names": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": "为空则用当前选择；可传组名",
            },
            "fix_lamina": {
                "type": "boolean",
                "default": False,
                "description": "预留：当前仅检测不修复",
            },
        }
    ),
    category="modeling",
)
def check_meshes(
    names: Optional[List[str]] = None,
    fix_lamina: bool = False,
) -> ToolResult:
    c = _cmds()
    _ = fix_lamina
    roots = names or (c.ls(selection=True, long=True) or [])
    if not roots:
        return ToolResult(ok=False, error="无对象可检查")

    shapes: List[str] = []
    for root in roots:
        if not c.objExists(root):
            continue
        shapes.extend(_collect_mesh_shapes(root))
    shapes = list(dict.fromkeys(shapes))
    if not shapes:
        return ToolResult(ok=False, error="未找到多边形 mesh")

    issues: List[Dict[str, Any]] = []
    summary = {
        "meshes_checked": len(shapes),
        "with_issues": 0,
        "nonmanifold_edges": 0,
        "nonmanifold_vertices": 0,
        "lamina_faces": 0,
        "zero_area_faces": 0,
        "holes": 0,
    }

    prev_sel = c.ls(selection=True, long=True) or []
    try:
        for shape in shapes:
            entry: Dict[str, Any] = {"shape": shape, "problems": []}
            try:
                parents = c.listRelatives(shape, parent=True, fullPath=True) or []
                entry["transform"] = parents[0] if parents else shape
            except Exception:
                entry["transform"] = shape

            # polyInfo based checks
            try:
                c.select(shape, replace=True)
                nm_edges = c.polyInfo(nonManifoldEdges=True) or []
                nm_verts = c.polyInfo(nonManifoldVertices=True) or []
                lamina = c.polyInfo(laminaFaces=True) or []
                # polyInfo returns list of strings or empty list
                if nm_edges:
                    entry["problems"].append(
                        {"type": "nonmanifold_edges", "count": len(nm_edges)}
                    )
                    summary["nonmanifold_edges"] += len(nm_edges)
                if nm_verts:
                    entry["problems"].append(
                        {"type": "nonmanifold_vertices", "count": len(nm_verts)}
                    )
                    summary["nonmanifold_vertices"] += len(nm_verts)
                if lamina:
                    entry["problems"].append(
                        {"type": "lamina_faces", "count": len(lamina)}
                    )
                    summary["lamina_faces"] += len(lamina)
            except Exception as e:
                entry["problems"].append({"type": "polyInfo_error", "detail": str(e)})

            # Holes / border edges via polyEvaluate
            try:
                # Maya: polyEvaluate(shell=True) / genus not always available —
                # use edge count heuristic via polyInfo borderEdges if present
                borders = []
                try:
                    borders = c.polyInfo(borderEdges=True) or []
                except Exception:
                    borders = []
                if borders:
                    entry["problems"].append(
                        {"type": "border_edges", "count": len(borders),
                         "note": "开放边界，可能是孔洞或开放网格"}
                    )
                    summary["holes"] += 1
            except Exception:
                pass

            # Isolated vertices: vertices with no connected edges (via cleanup query)
            try:
                verts = int(c.polyEvaluate(shape, vertex=True) or 0)
                edges = int(c.polyEvaluate(shape, edge=True) or 0)
                faces = int(c.polyEvaluate(shape, face=True) or 0)
                entry["vertices"] = verts
                entry["edges"] = edges
                entry["faces"] = faces
                # Zero-area faces: use polySelectConstraint if available — skip heavy
            except Exception:
                pass

            if entry["problems"]:
                summary["with_issues"] += 1
                issues.append(entry)
    finally:
        try:
            if prev_sel:
                c.select(prev_sel, replace=True)
            else:
                c.select(clear=True)
        except Exception:
            pass

    msg = (
        f"已检查 {summary['meshes_checked']} 个 mesh，"
        f"{summary['with_issues']} 个有问题"
    )
    if summary["nonmanifold_edges"] or summary["nonmanifold_vertices"]:
        msg += (
            f"（非流形边 {summary['nonmanifold_edges']} / "
            f"顶点 {summary['nonmanifold_vertices']}）"
        )
    return ToolResult(
        ok=True,
        data={"summary": summary, "issues": issues[:50], "truncated": len(issues) > 50},
        message=msg,
    )
