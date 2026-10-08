"""Modeling tools: primitives, layout, booleans, mesh stats, and upgraded edits."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from maya_agent.tools._maya import cmds as _cmds
from maya_agent.tools._mesh import (
    apply_world_transform,
    bbox_dict,
    collect_mesh_shapes,
    poly_stats,
    resolve_components,
    summarize_components,
    transform_of,
)
from maya_agent.tools.registry import ToolResult, obj_schema, tool

_PRIMITIVES = (
    "cube",
    "sphere",
    "cylinder",
    "plane",
    "cone",
    "torus",
    "disk",
    "pyramid",
    "pipe",
    "helix",
    "prism",
    "platonic",
)

def _make_primitive(
    primitive: str,
    *,
    name: str = "",
    subdivisions: int = 8,
    subdivisions_x: int = 0,
    subdivisions_y: int = 0,
    width: float = 1,
    height: float = 1,
    depth: float = 1,
    radius: float = 1,
    inner_radius: float = 0,
    axis: str = "y",
    sides: int = 6,
    platonic_type: str = "tetrahedron",
    coils: int = 3,
    position: Optional[List[float]] = None,
    rotation: Optional[List[float]] = None,
    scale: Optional[List[float]] = None,
):
    c = _cmds()
    prim = (primitive or "cube").lower()
    sx = int(subdivisions_x or subdivisions or 8)
    sy = int(subdivisions_y or subdivisions or 8)
    ax = (axis or "y").lower()
    axis_vec = {"x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}.get(ax, [0, 1, 0])
    inner = float(inner_radius) if inner_radius else max(radius * 0.5, radius - 0.2)

    def _first(result):
        return result[0] if isinstance(result, (list, tuple)) else result

    try:
        if prim == "cube":
            cdx = max(1, int(subdivisions_x or 1))
            cdy = max(1, int(subdivisions_y or 1))
            cdz = max(1, int(subdivisions_x or subdivisions_y or 1))
            node = _first(
                c.polyCube(
                    w=width, h=height, d=depth, sx=cdx, sy=cdy, sz=cdz, name=name or "pCube"
                )
            )
        elif prim == "sphere":
            node = _first(c.polySphere(r=radius, sx=sx, sy=sy, axis=axis_vec, name=name or "pSphere"))
        elif prim == "cylinder":
            node = _first(c.polyCylinder(r=radius, h=height, sx=sx, sy=max(1, sy // 4), sz=max(1, sx // 4), axis=axis_vec, name=name or "pCylinder"))
        elif prim == "plane":
            node = _first(c.polyPlane(w=width, h=height, sx=sx, sy=sy, axis=axis_vec, name=name or "pPlane"))
        elif prim == "cone":
            node = _first(c.polyCone(r=radius, h=height, sx=sx, axis=axis_vec, name=name or "pCone"))
        elif prim == "torus":
            sr = inner_radius if inner_radius else radius * 0.25
            node = _first(c.polyTorus(r=radius, sr=sr, sx=sx, sy=max(4, sy // 2), axis=axis_vec, name=name or "pTorus"))
        elif prim == "disk":
            if hasattr(c, "polyDisc"):
                node = _first(c.polyDisc(radius=radius, name=name or "pDisc"))
            else:
                node = _first(c.polyCylinder(r=radius, h=0.01, sx=sx, axis=axis_vec, name=name or "pDisk"))
        elif prim == "pyramid":
            node = _first(c.polyPyramid(ns=max(3, int(sides)), w=width, nsh=max(1, sy // 4), nsc=sx, name=name or "pPyramid"))
        elif prim == "pipe":
            node = _first(
                c.polyPipe(
                    r=radius,
                    h=height,
                    thickness=max(0.01, radius - inner * 0.5) if inner_radius else max(0.05, radius * 0.25),
                    sa=sx,
                    sh=max(1, sy // 4),
                    sc=max(1, sx // 4),
                    name=name or "pPipe",
                )
            )
        elif prim == "helix":
            node = _first(
                c.polyHelix(
                    c=max(1, int(coils)),
                    h=height,
                    w=radius * 2,
                    r=max(0.02, inner_radius or radius * 0.1),
                    sa=sx,
                    sco=max(4, sy),
                    name=name or "pHelix",
                )
            )
        elif prim == "prism":
            node = _first(c.polyPrism(ns=max(3, int(sides)), l=height, w=width, name=name or "pPrism"))
        elif prim == "platonic":
            mapping = {
                "tetrahedron": 0,
                "tetra": 0,
                "cube": 1,
                "octahedron": 2,
                "octa": 2,
                "dodecahedron": 3,
                "dodeca": 3,
                "icosahedron": 4,
                "icosa": 4,
            }
            st = mapping.get((platonic_type or "tetrahedron").lower(), 0)
            node = _first(c.polyPlatonicSolid(solidType=st, r=radius, name=name or "pPlatonic"))
        else:
            return None, f"不支持的原始体: {primitive}（可选: {', '.join(_PRIMITIVES)}）"
    except Exception as e:
        return None, f"创建 {prim} 失败: {e}"

    apply_world_transform(node, position, rotation, scale)
    return node, None


@tool(
    name="create_primitive",
    description=(
        "创建单个多边形图元：cube/sphere/cylinder/plane/cone/torus/disk/"
        "pyramid/pipe/helix/prism/platonic。"
        "可指定 position/rotation/scale 与轴向。批量请用 create_primitives。"
    ),
    parameters=obj_schema(
        {
            "primitive": {"type": "string", "enum": list(_PRIMITIVES)},
            "name": {"type": "string", "default": ""},
            "subdivisions": {"type": "integer", "default": 8},
            "subdivisions_x": {"type": "integer", "default": 0, "description": "覆盖轴向细分；0 则用 subdivisions"},
            "subdivisions_y": {"type": "integer", "default": 0},
            "width": {"type": "number", "default": 1},
            "height": {"type": "number", "default": 1},
            "depth": {"type": "number", "default": 1},
            "radius": {"type": "number", "default": 1},
            "inner_radius": {"type": "number", "default": 0, "description": "pipe/torus/helix 内半径；0=自动"},
            "axis": {"type": "string", "enum": ["x", "y", "z"], "default": "y"},
            "sides": {"type": "integer", "default": 6, "description": "pyramid/prism 边数"},
            "platonic_type": {
                "type": "string",
                "enum": ["tetrahedron", "cube", "octahedron", "dodecahedron", "icosahedron"],
                "default": "tetrahedron",
            },
            "coils": {"type": "integer", "default": 3},
            "position": {"type": "array", "items": {"type": "number"}, "description": "世界坐标 [x,y,z]"},
            "rotation": {"type": "array", "items": {"type": "number"}, "description": "欧拉角 [rx,ry,rz] 度"},
            "scale": {"type": "array", "items": {"type": "number"}},
        },
        required=["primitive"],
    ),
    category="modeling",
)
def create_primitive(
    primitive: str,
    name: str = "",
    subdivisions: int = 8,
    subdivisions_x: int = 0,
    subdivisions_y: int = 0,
    width: float = 1,
    height: float = 1,
    depth: float = 1,
    radius: float = 1,
    inner_radius: float = 0,
    axis: str = "y",
    sides: int = 6,
    platonic_type: str = "tetrahedron",
    coils: int = 3,
    position: Optional[List[float]] = None,
    rotation: Optional[List[float]] = None,
    scale: Optional[List[float]] = None,
) -> ToolResult:
    node, err = _make_primitive(
        primitive,
        name=name,
        subdivisions=subdivisions,
        subdivisions_x=subdivisions_x,
        subdivisions_y=subdivisions_y,
        width=width,
        height=height,
        depth=depth,
        radius=radius,
        inner_radius=inner_radius,
        axis=axis,
        sides=sides,
        platonic_type=platonic_type,
        coils=coils,
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


@tool(
    name="create_primitives",
    description=(
        "批量创建几何体并直接落位命名。items 每项可含 primitive/name/position/"
        "rotation/scale/width/height/depth/radius/axis/subdivisions。"
        "适合建筑块体、套件化硬表面。"
    ),
    parameters=obj_schema(
        {
            "items": {
                "type": "array",
                "items": {"type": "object"},
                "description": '如 [{"primitive":"cube","name":"wall_01","position":[0,150,0],"width":400,"height":300,"depth":40}]',
            },
            "group_name": {"type": "string", "default": "", "description": "可选：创建后打组"},
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
            subdivisions_x=int(raw.get("subdivisions_x") or 0),
            subdivisions_y=int(raw.get("subdivisions_y") or 0),
            width=float(raw.get("width") if raw.get("width") is not None else 1),
            height=float(raw.get("height") if raw.get("height") is not None else 1),
            depth=float(raw.get("depth") if raw.get("depth") is not None else 1),
            radius=float(raw.get("radius") if raw.get("radius") is not None else 1),
            inner_radius=float(raw.get("inner_radius") or 0),
            axis=str(raw.get("axis") or "y"),
            sides=int(raw.get("sides") or 6),
            platonic_type=str(raw.get("platonic_type") or "tetrahedron"),
            coils=int(raw.get("coils") or 3),
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
        "相对摆放：stack（沿轴堆叠）、align（对齐 bbox）、"
        "grid_array（矩形阵列）、radial_array（绕轴环形阵列）。"
    ),
    parameters=obj_schema(
        {
            "mode": {
                "type": "string",
                "enum": ["stack", "align", "grid_array", "radial_array"],
            },
            "names": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": "空则用当前选择。阵列时通常传 1 个源对象",
            },
            "axis": {
                "type": "string",
                "enum": ["x", "y", "z"],
                "default": "y",
            },
            "align_to": {
                "type": "string",
                "enum": ["min", "center", "max"],
                "default": "min",
            },
            "gap": {"type": "number", "default": 0.0},
            "count_x": {"type": "integer", "default": 1},
            "count_y": {"type": "integer", "default": 1},
            "count_z": {"type": "integer", "default": 1},
            "spacing": {
                "type": "array",
                "items": {"type": "number"},
                "description": "grid_array 间距 [sx,sy,sz]",
            },
            "count": {"type": "integer", "default": 8, "description": "radial_array 份数（含源）"},
            "radius_offset": {"type": "number", "default": 0, "description": "径向额外半径；0=用 bbox 推算"},
            "rotate_copies": {"type": "boolean", "default": True, "description": "环形阵列是否让副本朝向中心旋转"},
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
    count: int = 8,
    radius_offset: float = 0,
    rotate_copies: bool = True,
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
        ordered = list(targets)
        cursor = None
        moved = []
        for i, n in enumerate(ordered):
            bb = _bb(n)
            if i == 0:
                cursor = bb[ax_i + 3]
                moved.append(n)
                continue
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
        else:
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

    if mode == "radial_array":
        import math

        src = targets[0]
        n = max(2, int(count))
        if n > 180:
            return ToolResult(ok=False, error="环形份数不能超过 180")
        bb = _bb(src)
        size = [bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]]
        # Place copies around Y-up by default: rotate around axis, in the other two axes plane
        plane = [i for i in (0, 1, 2) if i != ax_i]
        span = max(size[plane[0]], size[plane[1]])
        radius = float(radius_offset) if radius_offset else span + float(gap)
        origin = c.xform(src, q=True, ws=True, t=True)
        created = [src]
        rot_attr = ["rx", "ry", "rz"][ax_i]
        for i in range(1, n):
            ang = 360.0 * i / n
            rad = math.radians(ang)
            dup = c.duplicate(src)[0]
            offset = [0.0, 0.0, 0.0]
            offset[plane[0]] = math.cos(rad) * radius
            offset[plane[1]] = math.sin(rad) * radius
            c.xform(
                dup,
                ws=True,
                translation=[
                    origin[0] + offset[0],
                    origin[1] + offset[1],
                    origin[2] + offset[2],
                ],
            )
            if rotate_copies:
                cur = c.xform(dup, q=True, ws=True, rotation=True)
                cur[ax_i] += ang
                c.xform(dup, ws=True, rotation=cur)
            created.append(dup)
        return ToolResult(
            ok=True,
            data={
                "mode": "radial_array",
                "objects": created,
                "count": n,
                "axis": axis,
                "radius": radius,
            },
            message=f"环形阵列：{len(created)} 个（绕 {axis}）",
        )

    return ToolResult(ok=False, error=f"未知 mode: {mode}")


@tool(
    name="combine_meshes",
    description="合并多个多边形网格为一个；可选按阈值焊接顶点并删除历史。",
    parameters=obj_schema(
        {
            "names": {"type": "array", "items": {"type": "string"}, "default": []},
            "new_name": {"type": "string", "default": ""},
            "merge_vertices": {"type": "boolean", "default": False},
            "merge_threshold": {"type": "number", "default": 0.001},
            "delete_history": {"type": "boolean", "default": True},
        }
    ),
    category="modeling",
)
def combine_meshes(
    names: Optional[List[str]] = None,
    new_name: str = "",
    merge_vertices: bool = False,
    merge_threshold: float = 0.001,
    delete_history: bool = True,
) -> ToolResult:
    c = _cmds()
    targets = names or (c.ls(selection=True, type="transform") or [])
    if len(targets) < 2:
        return ToolResult(ok=False, error="至少需要两个对象进行合并")
    c.select(targets, replace=True)
    result = c.polyUnite(ch=True)
    node = result[0] if isinstance(result, (list, tuple)) else result
    if new_name:
        node = c.rename(node, new_name)
    if merge_vertices:
        try:
            c.polyMergeVertex(node, d=float(merge_threshold), am=True, ch=True)
        except Exception:
            pass
    if delete_history:
        try:
            c.delete(node, constructionHistory=True)
        except Exception:
            pass
    return ToolResult(ok=True, data={"name": node}, message=f"已合并为 {node}")


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
    description=(
        "布尔：union / difference / intersection。"
        "mesh_b 为切割体；cutters 可传多个切割体（依次差集/累加）。"
        "keep_originals=true 时复制后再运算。"
    ),
    parameters=obj_schema(
        {
            "mesh_a": {"type": "string", "default": "", "description": "主体；空则用当前选择第一个"},
            "mesh_b": {"type": "string", "default": "", "description": "切割体；可与 cutters 一起用"},
            "cutters": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": "额外切割体列表",
            },
            "operation": {
                "type": "string",
                "enum": ["union", "difference", "intersection"],
                "default": "difference",
            },
            "keep_originals": {"type": "boolean", "default": False},
        }
    ),
    category="modeling",
)
def boolean_meshes(
    mesh_a: str = "",
    mesh_b: str = "",
    cutters: Optional[List[str]] = None,
    operation: str = "difference",
    keep_originals: bool = False,
) -> ToolResult:
    c = _cmds()
    op_map = {"union": 1, "difference": 2, "intersection": 3}
    if operation not in op_map:
        return ToolResult(ok=False, error="无效操作")
    sel = c.ls(selection=True, type="transform") or []
    host = mesh_a or (sel[0] if sel else "")
    extras = [x for x in ([mesh_b] if mesh_b else []) + list(cutters or []) if x]
    if not extras and len(sel) >= 2:
        if not mesh_a:
            host = sel[0]
        extras = [x for x in sel[1:] if x != host]
    if not host or not extras:
        return ToolResult(ok=False, error="需要主体 mesh_a 与至少一个切割体 mesh_b/cutters")
    for n in [host] + extras:
        if not c.objExists(n):
            return ToolResult(ok=False, error=f"对象不存在: {n}")

    working = host
    if keep_originals:
        working = c.duplicate(host)[0]
        extras = [c.duplicate(x)[0] for x in extras]

    def _bool(a, b):
        try:
            return c.polyCBoolOp(a, b, op=op_map[operation], ch=True)
        except Exception:
            return c.polyBoolOp(a, b, op=op_map[operation])

    last = working
    history = []
    for cutter in extras:
        result = _bool(last, cutter)
        last = result[0] if isinstance(result, (list, tuple)) else result
        history.append(last)
    try:
        c.delete(last, constructionHistory=True)
    except Exception:
        pass
    return ToolResult(
        ok=True,
        data={"name": last, "operation": operation, "cutters": extras},
        message=f"布尔 {operation} 完成: {last}",
    )


def _resolve_edit_components(
    mesh: str,
    kind: str,
    indices: Optional[List[Any]],
    selection_mode: str,
    direction: str,
    normal: Optional[List[float]],
    angle_degrees: float,
    bbox_min: Optional[List[float]],
    bbox_max: Optional[List[float]],
    index_from: Optional[int] = None,
    index_to: Optional[int] = None,
):
    comps, tf, err = resolve_components(
        mesh=mesh,
        kind=kind,
        mode=selection_mode or ("indices" if indices else "current"),
        indices=indices,
        index_from=index_from,
        index_to=index_to,
        direction=direction,
        normal=normal,
        angle_degrees=angle_degrees,
        bbox_min=bbox_min,
        bbox_max=bbox_max,
    )
    return comps, tf, err


@tool(
    name="extrude_faces",
    description=(
        "挤出面。可传 mesh + faces 索引，或 selection_mode=by_normal "
        "（如 direction=top 挤出顶面）/all/border。不必先手动点选。"
        "offset>0 且 thickness=0 时相当于 inset。keep_together 控制是否连体挤出。"
    ),
    parameters=obj_schema(
        {
            "mesh": {"type": "string", "default": ""},
            "faces": {
                "type": "array",
                "items": {"type": ["integer", "string"]},
                "default": [],
                "description": "面索引，如 [0,1,2] 或 [\"0:5\"]",
            },
            "selection_mode": {
                "type": "string",
                "enum": ["current", "indices", "all", "by_normal", "by_bbox", "border"],
                "default": "current",
            },
            "direction": {
                "type": "string",
                "default": "",
                "description": "by_normal：top/bottom/front/back/left/right",
            },
            "normal": {"type": "array", "items": {"type": "number"}},
            "angle_degrees": {"type": "number", "default": 35},
            "bbox_min": {"type": "array", "items": {"type": "number"}},
            "bbox_max": {"type": "array", "items": {"type": "number"}},
            "thickness": {"type": "number", "default": 0.2, "description": "沿面法向挤出距离"},
            "offset": {"type": "number", "default": 0.0, "description": "inset/outset"},
            "divisions": {"type": "integer", "default": 1},
            "keep_together": {"type": "boolean", "default": True},
            "world_translate": {
                "type": "array",
                "items": {"type": "number"},
                "description": "可选世界位移 [x,y,z]，替代纯法向挤出",
            },
        }
    ),
    category="modeling",
)
def extrude_faces(
    mesh: str = "",
    faces: Optional[List[Any]] = None,
    selection_mode: str = "current",
    direction: str = "",
    normal: Optional[List[float]] = None,
    angle_degrees: float = 35,
    bbox_min: Optional[List[float]] = None,
    bbox_max: Optional[List[float]] = None,
    thickness: float = 0.2,
    offset: float = 0.0,
    divisions: int = 1,
    keep_together: bool = True,
    world_translate: Optional[List[float]] = None,
) -> ToolResult:
    c = _cmds()
    comps, tf, err = _resolve_edit_components(
        mesh, "face", faces, selection_mode, direction, normal, angle_degrees, bbox_min, bbox_max
    )
    if err:
        return ToolResult(ok=False, error=err)
    kwargs: Dict[str, Any] = {
        "offset": offset,
        "divisions": max(1, int(divisions)),
        "keepFacesTogether": keep_together,
    }
    if world_translate and len(world_translate) >= 3:
        kwargs["ltz"] = 0
        kwargs["translate"] = [float(world_translate[0]), float(world_translate[1]), float(world_translate[2])]
    else:
        kwargs["ltz"] = thickness
    try:
        result = c.polyExtrudeFacet(comps, **kwargs)
    except Exception as e:
        return ToolResult(ok=False, error=f"挤出失败: {e}", data=summarize_components(comps, "face"))
    return ToolResult(
        ok=True,
        data={"mesh": tf, "result": result, "selection": summarize_components(comps, "face")},
        message=f"已挤出 {len(comps)} 个面（{tf}）",
    )


@tool(
    name="bevel_edges",
    description=(
        "对边做 Bevel/倒角。可传 mesh + edges 索引，或 selection_mode="
        "border/hard/all/by_normal（先选对应面再转到边）。"
    ),
    parameters=obj_schema(
        {
            "mesh": {"type": "string", "default": ""},
            "edges": {
                "type": "array",
                "items": {"type": ["integer", "string"]},
                "default": [],
            },
            "selection_mode": {
                "type": "string",
                "enum": ["current", "indices", "all", "border", "hard", "by_normal"],
                "default": "current",
            },
            "direction": {"type": "string", "default": ""},
            "normal": {"type": "array", "items": {"type": "number"}},
            "angle_degrees": {"type": "number", "default": 35},
            "offset": {"type": "number", "default": 0.1},
            "segments": {"type": "integer", "default": 1},
            "fraction": {"type": "number", "default": 0.5},
            "use_fraction": {"type": "boolean", "default": False, "description": "true 时用 fraction 相对倒角"},
        }
    ),
    category="modeling",
)
def bevel_edges(
    mesh: str = "",
    edges: Optional[List[Any]] = None,
    selection_mode: str = "current",
    direction: str = "",
    normal: Optional[List[float]] = None,
    angle_degrees: float = 35,
    offset: float = 0.1,
    segments: int = 1,
    fraction: float = 0.5,
    use_fraction: bool = False,
) -> ToolResult:
    c = _cmds()
    comps, tf, err = _resolve_edit_components(
        mesh, "edge", edges, selection_mode, direction, normal, angle_degrees, None, None
    )
    if err:
        return ToolResult(ok=False, error=err)
    kwargs: Dict[str, Any] = {"segments": max(1, int(segments))}
    if use_fraction:
        kwargs["offsetAsFraction"] = True
        kwargs["fraction"] = fraction
    else:
        kwargs["offset"] = offset
        kwargs["fraction"] = fraction
    try:
        result = c.polyBevel3(comps, **kwargs)
    except Exception:
        try:
            result = c.polyBevel(comps, offset=offset, segments=segments)
        except Exception as e:
            return ToolResult(ok=False, error=f"Bevel 失败: {e}")
    return ToolResult(
        ok=True,
        data={"mesh": tf, "result": result, "selection": summarize_components(comps, "edge")},
        message=f"已对 {len(comps)} 条边倒角（{tf}）",
    )


@tool(
    name="smooth_mesh",
    description=(
        "平滑网格：subdiv=Catmull-Clark 细分；average=平均顶点；"
        "soften=按角度软化边（不增面）。"
    ),
    parameters=obj_schema(
        {
            "names": {"type": "array", "items": {"type": "string"}, "default": []},
            "mode": {
                "type": "string",
                "enum": ["subdiv", "average", "soften"],
                "default": "subdiv",
            },
            "divisions": {"type": "integer", "default": 1},
            "keep_border": {"type": "boolean", "default": True},
            "iterations": {"type": "integer", "default": 1, "description": "average 迭代"},
            "angle": {"type": "number", "default": 30, "description": "soften 角度阈值"},
        }
    ),
    category="modeling",
)
def smooth_mesh(
    names: Optional[List[str]] = None,
    mode: str = "subdiv",
    divisions: int = 1,
    keep_border: bool = True,
    iterations: int = 1,
    angle: float = 30,
) -> ToolResult:
    c = _cmds()
    targets = names or (c.ls(selection=True) or [])
    if not targets:
        return ToolResult(ok=False, error="无对象")
    results = []
    mode = (mode or "subdiv").lower()
    for t in targets:
        if mode == "average":
            results.append(c.polyAverageVertex(t, iterations=max(1, int(iterations))))
        elif mode == "soften":
            results.append(c.polySoftEdge(t, angle=float(angle)))
        else:
            results.append(c.polySmooth(t, divisions=max(1, int(divisions)), keepBorder=keep_border))
    return ToolResult(
        ok=True,
        data=results,
        message=f"已 {mode} 处理 {len(targets)} 个对象",
    )


@tool(
    name="reduce_mesh",
    description="减面（适合游戏 LOD）。percentage 为保留百分比 0-100。",
    parameters=obj_schema(
        {
            "name": {"type": "string", "default": ""},
            "names": {"type": "array", "items": {"type": "string"}, "default": []},
            "percentage": {"type": "number", "description": "保留百分比 0-100", "default": 50},
            "keep_quads": {"type": "boolean", "default": True},
        }
    ),
    category="modeling",
)
def reduce_mesh(
    name: str = "",
    names: Optional[List[str]] = None,
    percentage: float = 50,
    keep_quads: bool = True,
) -> ToolResult:
    c = _cmds()
    targets = [x for x in ([name] if name else []) + list(names or []) if x]
    if not targets:
        targets = c.ls(selection=True) or []
    if not targets:
        return ToolResult(ok=False, error="无选择")
    results = []
    for t in targets:
        results.append(
            c.polyReduce(
                t,
                percentage=max(0.0, min(100.0, 100.0 - float(percentage))),
                keepQuadsWeight=1 if keep_quads else 0,
                keepBorder=True,
                cachingReduce=True,
            )
        )
    return ToolResult(ok=True, data=results, message=f"减面完成，保留约 {percentage}%（{len(targets)} 个）")


@tool(
    name="mirror_geometry",
    description="镜像几何体（沿物体枢轴）。merge_mode：0=不合并，1=合并边界。",
    parameters=obj_schema(
        {
            "name": {"type": "string", "default": ""},
            "axis": {"type": "string", "enum": ["x", "y", "z"], "default": "x"},
            "merge_mode": {"type": "integer", "default": 1},
            "merge_threshold": {"type": "number", "default": 0.001},
            "cut": {"type": "boolean", "default": True, "description": "true=切半再镜像；false=整体复制镜像"},
        }
    ),
    category="modeling",
)
def mirror_geometry(
    name: str = "",
    axis: str = "x",
    merge_mode: int = 1,
    merge_threshold: float = 0.001,
    cut: bool = True,
) -> ToolResult:
    c = _cmds()
    if name:
        c.select(name, replace=True)
    sel = c.ls(selection=True) or []
    if not sel:
        return ToolResult(ok=False, error="无选择")
    axis_map = {"x": 0, "y": 1, "z": 2}
    kwargs = dict(
        direction=axis_map.get((axis or "x").lower(), 0),
        mergeMode=merge_mode,
        mergeThreshold=merge_threshold,
    )
    if not cut:
        kwargs["mirrorAxis"] = axis_map.get((axis or "x").lower(), 0)
    result = c.polyMirrorFace(sel[0], **kwargs)
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
    description=(
        "获取网格拓扑统计（顶点/边/面/三角/UV）以及世界包围盒 bbox/size/center。"
        "支持传组名或层级：自动向下聚合所有 mesh shape。"
    ),
    parameters=obj_schema(
        {
            "name": {"type": "string", "default": "", "description": "对象/组名；空则用当前选择"},
            "aggregate": {"type": "boolean", "default": True},
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
        shapes.extend(collect_mesh_shapes(root))
    shapes = list(dict.fromkeys(shapes))
    if not shapes:
        types = ", ".join(f"{r}({t})" for r, t in root_types.items())
        return ToolResult(
            ok=False,
            error=f"未找到多边形 mesh：{types}。请传入 mesh / 含 mesh 的 transform 或组名。",
            data={"roots": root_types, "mesh_count": 0},
        )

    per_mesh = [poly_stats(s) for s in shapes]
    totals = {
        "vertices": sum(p["vertices"] for p in per_mesh),
        "edges": sum(p["edges"] for p in per_mesh),
        "faces": sum(p["faces"] for p in per_mesh),
        "triangles": sum(p["triangles"] for p in per_mesh),
        "uvs": sum(p["uvs"] for p in per_mesh),
        "mesh_count": len(per_mesh),
    }
    try:
        bb = c.exactWorldBoundingBox(list(roots))
        totals["bbox"] = bbox_dict(bb)
    except Exception:
        totals["bbox"] = None
    data: Dict[str, Any] = {
        "roots": root_types,
        "totals": totals,
        "meshes": per_mesh if (not aggregate or len(per_mesh) <= 20) else per_mesh[:20],
        "meshes_truncated": len(per_mesh) > 20 and aggregate,
    }
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
                "bbox": per_mesh[0].get("bbox"),
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
        "网格质量体检：非流形边/顶点、孔洞边、层叠面、零面积面。"
        "apply_cleanup=true 时尝试焊接近点、删除层叠面（不可逆，建议先确认）。"
    ),
    parameters=obj_schema(
        {
            "names": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": "为空则用当前选择；可传组名",
            },
            "zero_area_threshold": {"type": "number", "default": 1e-8},
            "apply_cleanup": {"type": "boolean", "default": False},
            "merge_threshold": {"type": "number", "default": 0.001},
        }
    ),
    category="modeling",
)
def check_meshes(
    names: Optional[List[str]] = None,
    zero_area_threshold: float = 1e-8,
    apply_cleanup: bool = False,
    merge_threshold: float = 0.001,
) -> ToolResult:
    c = _cmds()
    roots = names or (c.ls(selection=True, long=True) or [])
    if not roots:
        return ToolResult(ok=False, error="无对象可检查")

    shapes: List[str] = []
    for root in roots:
        if not c.objExists(root):
            continue
        shapes.extend(collect_mesh_shapes(root))
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
        "cleaned": [],
    }

    prev_sel = c.ls(selection=True, long=True) or []
    try:
        for shape in shapes:
            entry: Dict[str, Any] = {"shape": shape, "problems": []}
            entry["transform"] = transform_of(shape)
            try:
                c.select(shape, replace=True)
                nm_edges = c.polyInfo(nonManifoldEdges=True) or []
                nm_verts = c.polyInfo(nonManifoldVertices=True) or []
                lamina = c.polyInfo(laminaFaces=True) or []
                if nm_edges:
                    entry["problems"].append({"type": "nonmanifold_edges", "count": len(nm_edges)})
                    summary["nonmanifold_edges"] += len(nm_edges)
                if nm_verts:
                    entry["problems"].append({"type": "nonmanifold_vertices", "count": len(nm_verts)})
                    summary["nonmanifold_vertices"] += len(nm_verts)
                if lamina:
                    entry["problems"].append({"type": "lamina_faces", "count": len(lamina)})
                    summary["lamina_faces"] += len(lamina)
            except Exception as e:
                entry["problems"].append({"type": "polyInfo_error", "detail": str(e)})

            try:
                borders = c.polyInfo(borderEdges=True) or []
                if borders:
                    entry["problems"].append(
                        {
                            "type": "border_edges",
                            "count": len(borders),
                            "note": "开放边界，可能是孔洞或开放网格",
                        }
                    )
                    summary["holes"] += 1
            except Exception:
                pass

            try:
                from maya.api import OpenMaya as om

                sl = om.MSelectionList()
                sl.add(shape)
                dag = sl.getDagPath(0)
                fn = om.MFnMesh(dag)
                zero = 0
                for i in range(fn.numPolygons):
                    try:
                        area = float(fn.getPolygonArea(i, om.MSpace.kWorld))
                    except Exception:
                        area = 1.0
                    if area < float(zero_area_threshold):
                        zero += 1
                if zero:
                    entry["problems"].append({"type": "zero_area_faces", "count": zero})
                    summary["zero_area_faces"] += zero
            except Exception:
                pass

            try:
                entry["vertices"] = int(c.polyEvaluate(shape, vertex=True) or 0)
                entry["edges"] = int(c.polyEvaluate(shape, edge=True) or 0)
                entry["faces"] = int(c.polyEvaluate(shape, face=True) or 0)
            except Exception:
                pass

            if apply_cleanup:
                tf = entry["transform"]
                try:
                    c.polyMergeVertex(tf, d=float(merge_threshold), am=True, ch=True)
                    summary["cleaned"].append(tf)
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

    msg = f"已检查 {summary['meshes_checked']} 个 mesh，{summary['with_issues']} 个有问题"
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
