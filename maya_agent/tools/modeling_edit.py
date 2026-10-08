"""Component-level modeling: select, extrude edges, topology, normals, transform."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from maya_agent.tools._maya import cmds as _cmds
from maya_agent.tools._mesh import (
    as_vec3,
    convert_components,
    resolve_components,
    select_components,
    summarize_components,
    transform_of,
)
from maya_agent.tools.registry import ToolResult, obj_schema, tool

_SEL_MODES = [
    "current",
    "indices",
    "range",
    "all",
    "by_normal",
    "by_bbox",
    "border",
    "hard",
    "nonmanifold",
    "grow",
    "shrink",
    "convert",
]


def _pick(
    mesh: str,
    kind: str,
    indices: Optional[List[Any]],
    selection_mode: str,
    direction: str = "",
    normal: Optional[List[float]] = None,
    angle_degrees: float = 35,
    bbox_min: Optional[List[float]] = None,
    bbox_max: Optional[List[float]] = None,
    index_from: Optional[int] = None,
    index_to: Optional[int] = None,
    convert_from: str = "",
):
    return resolve_components(
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
        convert_from=convert_from,
    )


_COMMON_SEL = {
    "mesh": {"type": "string", "default": "", "description": "网格名；空则从当前选择推断"},
    "selection_mode": {
        "type": "string",
        "enum": _SEL_MODES,
        "default": "current",
        "description": (
            "current=当前分量；indices/range=索引；all=全部；"
            "by_normal=按世界法线（direction=top/front/...）；"
            "by_bbox=面心在包围盒内；border/hard/nonmanifold；grow/shrink/convert"
        ),
    },
    "indices": {
        "type": "array",
        "items": {"type": ["integer", "string"]},
        "default": [],
        "description": "索引列表，如 [0,1,2] 或 [\"0:12\"]",
    },
    "index_from": {"type": "integer"},
    "index_to": {"type": "integer"},
    "direction": {
        "type": "string",
        "default": "",
        "description": "top/bottom/front/back/left/right 或 +y/-z",
    },
    "normal": {"type": "array", "items": {"type": "number"}},
    "angle_degrees": {"type": "number", "default": 35},
    "bbox_min": {"type": "array", "items": {"type": "number"}},
    "bbox_max": {"type": "array", "items": {"type": "number"}},
    "convert_from": {
        "type": "string",
        "default": "",
        "description": "convert 模式的源类型：face/edge/vertex",
    },
}


@tool(
    name="select_mesh_components",
    description=(
        "选择或查询网格分量（面/边/顶点）。这是建模编辑的入口："
        "先按索引、法线方向、包围盒、边界边等选出分量，再挤出/倒角/拓扑编辑。"
        "keep_selection=true 时写入 Maya 选择，供后续工具使用。"
    ),
    parameters=obj_schema(
        {
            **_COMMON_SEL,
            "component": {
                "type": "string",
                "enum": ["face", "edge", "vertex"],
                "default": "face",
            },
            "keep_selection": {"type": "boolean", "default": True},
            "add": {"type": "boolean", "default": False},
        }
    ),
    category="modeling",
)
def select_mesh_components(
    mesh: str = "",
    component: str = "face",
    selection_mode: str = "current",
    indices: Optional[List[Any]] = None,
    index_from: Optional[int] = None,
    index_to: Optional[int] = None,
    direction: str = "",
    normal: Optional[List[float]] = None,
    angle_degrees: float = 35,
    bbox_min: Optional[List[float]] = None,
    bbox_max: Optional[List[float]] = None,
    convert_from: str = "",
    keep_selection: bool = True,
    add: bool = False,
) -> ToolResult:
    comps, tf, err = _pick(
        mesh,
        component,
        indices,
        selection_mode,
        direction,
        normal,
        angle_degrees,
        bbox_min,
        bbox_max,
        index_from,
        index_to,
        convert_from,
    )
    if err:
        return ToolResult(ok=False, error=err)
    if keep_selection:
        select_components(comps, replace=not add, add=add)
    info = summarize_components(comps, component)
    info["mesh"] = tf
    return ToolResult(
        ok=True,
        data=info,
        message=f"已解析 {info['count']} 个{component}（{tf}）",
    )


@tool(
    name="extrude_edges",
    description=(
        "挤出边。可传 mesh + edges 或 selection_mode=border（开放边）/"
        "by_normal。width=沿边法向，thickness=另一局部轴，divisions=分段。"
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
            "width": {"type": "number", "default": 0.2},
            "thickness": {"type": "number", "default": 0.0},
            "divisions": {"type": "integer", "default": 1},
            "keep_together": {"type": "boolean", "default": True},
        }
    ),
    category="modeling",
)
def extrude_edges(
    mesh: str = "",
    edges: Optional[List[Any]] = None,
    selection_mode: str = "current",
    direction: str = "",
    normal: Optional[List[float]] = None,
    angle_degrees: float = 35,
    width: float = 0.2,
    thickness: float = 0.0,
    divisions: int = 1,
    keep_together: bool = True,
) -> ToolResult:
    c = _cmds()
    comps, tf, err = _pick(
        mesh, "edge", edges, selection_mode, direction, normal, angle_degrees
    )
    if err:
        return ToolResult(ok=False, error=err)
    try:
        result = c.polyExtrudeEdge(
            comps,
            lty=width,
            ltz=thickness,
            divisions=max(1, int(divisions)),
            keepFacesTogether=keep_together,
        )
    except Exception as e:
        return ToolResult(ok=False, error=f"挤出边失败: {e}")
    return ToolResult(
        ok=True,
        data={"mesh": tf, "result": result, "selection": summarize_components(comps, "edge")},
        message=f"已挤出 {len(comps)} 条边（{tf}）",
    )


@tool(
    name="edit_mesh_topology",
    description=(
        "拓扑编辑（先解析分量再执行）。operation："
        "delete / extract / duplicate_faces / collapse / merge_vertices / "
        "poke / wedge / bridge / fill_holes / connect / insert_edgeloop / "
        "triangulate / quadrangulate / detach_edges。"
        "extract=把面撕成新网格；fill_holes 填开放边界。"
    ),
    parameters=obj_schema(
        {
            **_COMMON_SEL,
            "component": {
                "type": "string",
                "enum": ["face", "edge", "vertex"],
                "default": "face",
            },
            "operation": {
                "type": "string",
                "enum": [
                    "delete",
                    "extract",
                    "duplicate_faces",
                    "collapse",
                    "merge_vertices",
                    "poke",
                    "wedge",
                    "bridge",
                    "fill_holes",
                    "connect",
                    "insert_edgeloop",
                    "triangulate",
                    "quadrangulate",
                    "detach_edges",
                ],
            },
            "merge_threshold": {"type": "number", "default": 0.001},
            "divisions": {"type": "integer", "default": 1},
            "weight": {"type": "number", "default": 0.5, "description": "insert_edgeloop 位置 0-1"},
            "wedge_angle": {"type": "number", "default": 45},
            "wedge_axis": {"type": "array", "items": {"type": "number"}},
            "new_name": {"type": "string", "default": ""},
        },
        required=["operation"],
    ),
    category="modeling",
    destructive=True,
)
def edit_mesh_topology(
    operation: str,
    mesh: str = "",
    component: str = "face",
    selection_mode: str = "current",
    indices: Optional[List[Any]] = None,
    index_from: Optional[int] = None,
    index_to: Optional[int] = None,
    direction: str = "",
    normal: Optional[List[float]] = None,
    angle_degrees: float = 35,
    bbox_min: Optional[List[float]] = None,
    bbox_max: Optional[List[float]] = None,
    convert_from: str = "",
    merge_threshold: float = 0.001,
    divisions: int = 1,
    weight: float = 0.5,
    wedge_angle: float = 45,
    wedge_axis: Optional[List[float]] = None,
    new_name: str = "",
) -> ToolResult:
    c = _cmds()
    op = (operation or "").lower()
    kind = component
    if op in ("merge_vertices",):
        kind = "vertex"
    elif op in ("bridge", "insert_edgeloop", "detach_edges", "connect"):
        if kind == "face" and op != "connect":
            kind = "edge"
    elif op in ("extract", "duplicate_faces", "poke", "wedge"):
        kind = "face"
    elif op in ("fill_holes", "triangulate", "quadrangulate"):
        kind = kind or "face"

    comps: List[str] = []
    tf = mesh
    if op in ("fill_holes", "triangulate", "quadrangulate") and (
        selection_mode in ("all", "current") and not indices and mesh
    ):
        tf = transform_of(mesh) if mesh else tf
        if not tf:
            comps, tf, err = _pick(mesh, kind, indices, selection_mode)
            if err:
                return ToolResult(ok=False, error=err)
        else:
            comps = [tf]
    else:
        comps, tf, err = _pick(
            mesh,
            kind,
            indices,
            selection_mode,
            direction,
            normal,
            angle_degrees,
            bbox_min,
            bbox_max,
            index_from,
            index_to,
            convert_from,
        )
        if err and op not in ("fill_holes", "triangulate", "quadrangulate"):
            return ToolResult(ok=False, error=err)
        if err:
            if not mesh:
                return ToolResult(ok=False, error=err)
            tf = transform_of(mesh)
            comps = [tf]

    result: Any = None
    extra: Dict[str, Any] = {}
    try:
        if op == "delete":
            c.delete(comps)
            result = {"deleted": len(comps)}
        elif op == "extract":
            result = c.polyChipOff(comps, dup=False, keepFacesTogether=True)
            try:
                sep = c.polySeparate(tf)
                extra["separated"] = sep
                if new_name and sep:
                    extra["separated"] = [c.rename(sep[-1], new_name)] + list(sep[:-1])
            except Exception:
                pass
        elif op == "duplicate_faces":
            result = c.polyChipOff(comps, dup=True, keepFacesTogether=True)
            try:
                extra["separated"] = c.polySeparate(tf)
            except Exception:
                pass
        elif op == "collapse":
            if kind == "face":
                result = c.polyCollapseFacet(comps)
            elif kind == "edge":
                result = c.polyCollapseEdge(comps)
            else:
                result = c.polyMergeVertex(comps, d=1e6, am=True)
        elif op == "merge_vertices":
            result = c.polyMergeVertex(comps, d=float(merge_threshold), am=True, ch=True)
        elif op == "poke":
            result = c.polyPoke(comps)
        elif op == "wedge":
            axis = as_vec3(wedge_axis, (1.0, 0.0, 0.0))
            result = c.polyWedgeFace(
                comps,
                wedgeAngle=float(wedge_angle),
                axis=list(axis),
            )
        elif op == "bridge":
            result = c.polyBridgeEdge(comps, divisions=max(0, int(divisions)))
        elif op == "fill_holes":
            target = comps if kind == "edge" else [tf]
            try:
                result = c.polyCloseBorder(target)
            except Exception:
                result = c.polyCloseBorder(tf)
        elif op == "connect":
            result = c.polyConnectComponents(comps)
        elif op == "insert_edgeloop":
            result = c.polySplitRing(comps, weight=float(weight), splitType=1, smoothingAngle=30)
        elif op == "triangulate":
            result = c.polyTriangulate(tf if selection_mode == "all" else comps)
        elif op == "quadrangulate":
            try:
                result = c.polyQuad(tf if selection_mode == "all" else comps, angle=30)
            except Exception as e:
                return ToolResult(ok=False, error=f"四边化失败: {e}")
        elif op == "detach_edges":
            result = c.polySplitEdge(comps)
        else:
            return ToolResult(ok=False, error=f"未知 operation: {operation}")
    except Exception as e:
        return ToolResult(ok=False, error=f"{op} 失败: {e}", data=summarize_components(comps, kind))

    data = {"mesh": tf, "operation": op, "result": result, "selection": summarize_components(comps, kind)}
    data.update(extra)
    return ToolResult(ok=True, data=data, message=f"拓扑 {op} 完成（{tf}）")


@tool(
    name="edit_mesh_normals",
    description=(
        "法线与软硬边：reverse / conform / set_to_face / unlock / "
        "soften / harden / average。soften 用 angle 阈值（度）。"
    ),
    parameters=obj_schema(
        {
            "mesh": {"type": "string", "default": ""},
            "names": {"type": "array", "items": {"type": "string"}, "default": []},
            "operation": {
                "type": "string",
                "enum": ["reverse", "conform", "set_to_face", "unlock", "soften", "harden", "average"],
            },
            "user_normal": {
                "type": "boolean",
                "default": False,
                "description": "reverse 时是否同时翻用户法线",
            },
            "angle": {"type": "number", "default": 30},
            "selection_mode": {
                "type": "string",
                "enum": ["all", "current", "indices", "border", "hard"],
                "default": "all",
            },
            "component": {"type": "string", "enum": ["face", "edge", "vertex"], "default": "edge"},
            "indices": {
                "type": "array",
                "items": {"type": ["integer", "string"]},
                "default": [],
            },
        },
        required=["operation"],
    ),
    category="modeling",
)
def edit_mesh_normals(
    operation: str,
    mesh: str = "",
    names: Optional[List[str]] = None,
    user_normal: bool = False,
    angle: float = 30,
    selection_mode: str = "all",
    component: str = "edge",
    indices: Optional[List[Any]] = None,
) -> ToolResult:
    c = _cmds()
    op = (operation or "").lower()
    targets = [x for x in ([mesh] if mesh else []) + list(names or []) if x]
    if not targets:
        targets = c.ls(selection=True, type="transform") or []
    if not targets:
        return ToolResult(ok=False, error="无对象")

    done = []
    for t in targets:
        tf = transform_of(t)
        try:
            if op == "reverse":
                c.polyNormal(tf, normalMode=0, userNormalMode=1 if user_normal else 0)
            elif op == "conform":
                c.polyNormal(tf, normalMode=2)
            elif op == "set_to_face":
                c.polyNormalPerVertex(tf, unFreezeNormal=True)
                try:
                    c.polySetToFaceNormal(tf)
                except Exception:
                    c.polyNormalPerVertex(tf, freezeNormal=False)
            elif op == "unlock":
                c.polyNormalPerVertex(tf, unFreezeNormal=True)
            elif op in ("soften", "harden"):
                comps, _, err = _pick(
                    tf, "edge", indices, selection_mode if selection_mode != "all" else "all"
                )
                target = comps if selection_mode != "all" and not err else tf
                deg = 180.0 if op == "soften" and selection_mode == "all" else (float(angle) if op == "soften" else 0.0)
                if op == "harden":
                    deg = 0.0
                c.polySoftEdge(target, angle=deg)
            elif op == "average":
                try:
                    c.polyAverageNormal(tf)
                except Exception:
                    c.polySoftEdge(tf, angle=180)
            else:
                return ToolResult(ok=False, error=f"未知 operation: {operation}")
            done.append(tf)
        except Exception as e:
            return ToolResult(ok=False, error=f"{tf}: {e}", data={"done": done})
    return ToolResult(ok=True, data={"objects": done, "operation": op}, message=f"法线 {op}：{len(done)} 个对象")


@tool(
    name="transform_components",
    description=(
        "移动/旋转/缩放分量，或沿轴压平（flatten）。"
        "flatten_axis=x/y/z 且 flatten_to=min/center/max/value。"
        "不必先点选：可传 mesh + selection_mode=by_normal。"
    ),
    parameters=obj_schema(
        {
            **_COMMON_SEL,
            "component": {
                "type": "string",
                "enum": ["face", "edge", "vertex"],
                "default": "vertex",
            },
            "translate": {"type": "array", "items": {"type": "number"}},
            "rotate": {"type": "array", "items": {"type": "number"}},
            "scale": {"type": "array", "items": {"type": "number"}},
            "world_space": {"type": "boolean", "default": True},
            "flatten_axis": {
                "type": "string",
                "default": "",
                "description": "x/y/z 时沿该轴压平顶点；空则不压平",
            },
            "flatten_to": {
                "type": "string",
                "enum": ["min", "center", "max", "value"],
                "default": "center",
            },
            "flatten_value": {"type": "number", "default": 0},
        }
    ),
    category="modeling",
)
def transform_components(
    mesh: str = "",
    component: str = "vertex",
    selection_mode: str = "current",
    indices: Optional[List[Any]] = None,
    index_from: Optional[int] = None,
    index_to: Optional[int] = None,
    direction: str = "",
    normal: Optional[List[float]] = None,
    angle_degrees: float = 35,
    bbox_min: Optional[List[float]] = None,
    bbox_max: Optional[List[float]] = None,
    convert_from: str = "",
    translate: Optional[List[float]] = None,
    rotate: Optional[List[float]] = None,
    scale: Optional[List[float]] = None,
    world_space: bool = True,
    flatten_axis: str = "",
    flatten_to: str = "center",
    flatten_value: float = 0,
) -> ToolResult:
    c = _cmds()
    comps, tf, err = _pick(
        mesh,
        component,
        indices,
        selection_mode,
        direction,
        normal,
        angle_degrees,
        bbox_min,
        bbox_max,
        index_from,
        index_to,
        convert_from,
    )
    if err:
        return ToolResult(ok=False, error=err)

    tvec = as_vec3(translate)
    rvec = as_vec3(rotate)
    svec = as_vec3(scale)
    if tvec:
        c.move(tvec[0], tvec[1], tvec[2], comps, relative=True, worldSpace=world_space)
    if rvec:
        c.rotate(rvec[0], rvec[1], rvec[2], comps, relative=True, worldSpace=world_space)
    if svec:
        c.scale(svec[0], svec[1], svec[2], comps, relative=True)

    if flatten_axis:
        axis_key = (flatten_axis or "").lower()
        if axis_key not in ("x", "y", "z"):
            return ToolResult(ok=False, error="flatten_axis 必须是 x/y/z")
        ax = {"x": 0, "y": 1, "z": 2}[axis_key]
        verts = comps if component == "vertex" else convert_components(comps, "vertex")
        if not verts:
            return ToolResult(ok=False, error="压平失败：没有可变换的顶点")
        pts = []
        for v in verts:
            p = c.xform(v, q=True, ws=True, t=True)
            pts.append((v, p))
        coords = [p[ax] for _, p in pts]
        if flatten_to == "min":
            target = min(coords)
        elif flatten_to == "max":
            target = max(coords)
        elif flatten_to == "value":
            target = float(flatten_value)
        else:
            target = sum(coords) / float(len(coords) or 1)
        for v, p in pts:
            p[ax] = target
            c.xform(v, ws=True, t=p)

    return ToolResult(
        ok=True,
        data={"mesh": tf, "selection": summarize_components(comps, component)},
        message=f"已变换 {len(comps)} 个{component}（{tf}）",
    )
