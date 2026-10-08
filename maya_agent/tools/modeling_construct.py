"""Constructive modeling: curves, sweep/revolve/loft, text, thicken, cleanup."""

from __future__ import annotations

from typing import List, Optional

from maya_agent.tools._maya import cmds as _cmds
from maya_agent.tools._mesh import apply_world_transform, collect_mesh_shapes, transform_of
from maya_agent.tools.registry import ToolResult, obj_schema, tool


def _nurbs_to_poly(surface: str, name: str = "") -> str:
    c = _cmds()
    meshes = c.nurbsToPoly(
        surface,
        ch=False,
        mnd=1,
        pt=1,
        f=3,
        ut=1,
        un=1,
        vt=1,
        vn=1,
        cht=False,
    )
    node = meshes[0] if isinstance(meshes, (list, tuple)) else meshes
    if name:
        node = c.rename(node, name)
    try:
        c.delete(surface)
    except Exception:
        pass
    return node


@tool(
    name="create_curve",
    description=(
        "创建曲线：polyline（折线）、ep（编辑点曲线）、cv（CV 曲线）、circle、line。"
        "points 为世界坐标列表。后续可用 mesh_from_curve 扫掠/旋转成网格。"
    ),
    parameters=obj_schema(
        {
            "curve_type": {
                "type": "string",
                "enum": ["polyline", "ep", "cv", "circle", "line"],
                "default": "polyline",
            },
            "points": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}},
                "description": "[[x,y,z], ...]；circle 可不填",
            },
            "name": {"type": "string", "default": ""},
            "degree": {"type": "integer", "default": 3, "description": "ep/cv 阶数，polyline 强制 1"},
            "radius": {"type": "number", "default": 1, "description": "circle 半径"},
            "normal": {
                "type": "array",
                "items": {"type": "number"},
                "description": "circle 法线，默认 [0,1,0]",
            },
            "sections": {"type": "integer", "default": 8},
        }
    ),
    category="modeling",
)
def create_curve(
    curve_type: str = "polyline",
    points: Optional[List[List[float]]] = None,
    name: str = "",
    degree: int = 3,
    radius: float = 1,
    normal: Optional[List[float]] = None,
    sections: int = 8,
) -> ToolResult:
    c = _cmds()
    kind = (curve_type or "polyline").lower()
    pts = [p for p in (points or []) if isinstance(p, (list, tuple)) and len(p) >= 3]
    if kind == "line":
        if len(pts) < 2:
            return ToolResult(ok=False, error="line 至少需要 2 个点")
        pts = [pts[0], pts[-1]]
        kind = "polyline"
    try:
        if kind == "circle":
            nr = normal if normal and len(normal) >= 3 else [0, 1, 0]
            node = c.circle(
                r=radius,
                nr=nr,
                s=max(4, int(sections)),
                name=name or "curveCircle",
            )[0]
        elif kind == "polyline":
            if len(pts) < 2:
                return ToolResult(ok=False, error="polyline 至少需要 2 个点")
            node = c.curve(d=1, p=[(float(p[0]), float(p[1]), float(p[2])) for p in pts], name=name or "curveLine")
        elif kind == "ep":
            if len(pts) < 2:
                return ToolResult(ok=False, error="ep 至少需要 2 个点")
            node = c.curve(
                d=min(3, max(1, int(degree))),
                ep=[(float(p[0]), float(p[1]), float(p[2])) for p in pts],
                name=name or "curveEP",
            )
        elif kind == "cv":
            if len(pts) < 2:
                return ToolResult(ok=False, error="cv 至少需要 2 个点")
            node = c.curve(
                d=min(3, max(1, int(degree))),
                p=[(float(p[0]), float(p[1]), float(p[2])) for p in pts],
                name=name or "curveCV",
            )
        else:
            return ToolResult(ok=False, error=f"未知 curve_type: {curve_type}")
    except Exception as e:
        return ToolResult(ok=False, error=f"创建曲线失败: {e}")
    return ToolResult(ok=True, data={"name": node, "type": kind}, message=f"已创建曲线 {node}")


@tool(
    name="mesh_from_curve",
    description=(
        "由曲线生成多边形：pipe=沿路径扫圆管；revolve=绕轴旋转；"
        "planar=封闭曲线填面；loft=多条曲线放样。结果转为 polygon。"
    ),
    parameters=obj_schema(
        {
            "mode": {
                "type": "string",
                "enum": ["pipe", "revolve", "planar", "loft"],
            },
            "curve": {"type": "string", "default": "", "description": "路径/轮廓曲线；空则用当前选择"},
            "curves": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": "loft 需要至少 2 条",
            },
            "radius": {"type": "number", "default": 0.1, "description": "pipe 截面半径"},
            "axis": {"type": "string", "enum": ["x", "y", "z"], "default": "y", "description": "revolve 轴"},
            "pivot": {"type": "array", "items": {"type": "number"}, "description": "revolve 轴通过点，默认原点"},
            "sweep": {"type": "number", "default": 360, "description": "revolve 角度"},
            "sections": {"type": "integer", "default": 8},
            "name": {"type": "string", "default": ""},
            "keep_curves": {"type": "boolean", "default": True},
        },
        required=["mode"],
    ),
    category="modeling",
)
def mesh_from_curve(
    mode: str,
    curve: str = "",
    curves: Optional[List[str]] = None,
    radius: float = 0.1,
    axis: str = "y",
    pivot: Optional[List[float]] = None,
    sweep: float = 360,
    sections: int = 8,
    name: str = "",
    keep_curves: bool = True,
) -> ToolResult:
    c = _cmds()
    mode = (mode or "").lower()
    sel = c.ls(selection=True) or []
    path = curve or (sel[0] if sel else "")
    loft_crvs = [x for x in (curves or []) if x]
    if mode == "loft":
        if len(loft_crvs) < 2:
            loft_crvs = [x for x in sel if c.objExists(x)]
        if len(loft_crvs) < 2:
            return ToolResult(ok=False, error="loft 需要至少 2 条曲线")
        for n in loft_crvs:
            if not c.objExists(n):
                return ToolResult(ok=False, error=f"曲线不存在: {n}")
    elif not path or not c.objExists(path):
        return ToolResult(ok=False, error="请指定 curve 或先选择曲线")

    created_helpers: List[str] = []
    try:
        if mode == "pipe":
            profile = c.circle(r=max(0.001, float(radius)), s=max(4, int(sections)), name="ma_pipe_profile")[0]
            created_helpers.append(profile)
            # Align profile to path start
            try:
                start = c.pointOnCurve(path, pr=0, p=True)
                c.xform(profile, ws=True, t=start)
            except Exception:
                pass
            surf = c.extrude(
                profile,
                path,
                et=2,
                ucp=1,
                fpt=1,
                upn=1,
                rsp=1,
                name="ma_pipe_surf",
            )[0]
        elif mode == "revolve":
            ax = {"x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}.get((axis or "y").lower(), [0, 1, 0])
            piv = pivot if pivot and len(pivot) >= 3 else [0, 0, 0]
            surf = c.revolve(
                path,
                ax=ax,
                p=piv,
                ssw=0,
                esw=float(sweep),
                degree=3,
                sections=max(4, int(sections)),
                name="ma_revolve_surf",
            )[0]
        elif mode == "planar":
            surf = c.planarSrf(path, name="ma_planar_surf")[0]
        elif mode == "loft":
            surf = c.loft(*loft_crvs, ch=False, uniform=True, name="ma_loft_surf")[0]
        else:
            return ToolResult(ok=False, error=f"未知 mode: {mode}")
        node = _nurbs_to_poly(surf, name=name or "")
    except Exception as e:
        for h in created_helpers:
            if c.objExists(h):
                try:
                    c.delete(h)
                except Exception:
                    pass
        return ToolResult(ok=False, error=f"{mode} 失败: {e}")

    for h in created_helpers:
        if c.objExists(h):
            try:
                c.delete(h)
            except Exception:
                pass
    if not keep_curves:
        to_del = loft_crvs if mode == "loft" else ([path] if path else [])
        for n in to_del:
            try:
                if c.objExists(n):
                    c.delete(n)
            except Exception:
                pass
    return ToolResult(ok=True, data={"name": node, "mode": mode}, message=f"{mode} 网格已生成: {node}")


@tool(
    name="create_text_mesh",
    description="把文字建成多边形网格（textCurves → 填面 → 挤出厚度）。适合铭牌、UI 占位、简单标识。",
    parameters=obj_schema(
        {
            "text": {"type": "string"},
            "font": {"type": "string", "default": "Arial", "description": "系统字体名，如 Arial / Microsoft YaHei"},
            "name": {"type": "string", "default": ""},
            "extrude": {"type": "number", "default": 0.1, "description": "厚度；0=仅平面"},
            "scale": {"type": "number", "default": 1},
            "position": {"type": "array", "items": {"type": "number"}},
        },
        required=["text"],
    ),
    category="modeling",
)
def create_text_mesh(
    text: str,
    font: str = "Arial",
    name: str = "",
    extrude: float = 0.1,
    scale: float = 1,
    position: Optional[List[float]] = None,
) -> ToolResult:
    c = _cmds()
    if not (text or "").strip():
        return ToolResult(ok=False, error="text 为空")
    try:
        created = c.textCurves(f=font, t=text, name=name or "text")
    except Exception as e:
        return ToolResult(ok=False, error=f"textCurves 失败（检查字体名）: {e}")
    root = created[0] if isinstance(created, (list, tuple)) else created
    curves = c.listRelatives(root, allDescendents=True, type="nurbsCurve", fullPath=True) or []
    if not curves:
        parents = c.listRelatives(root, children=True, fullPath=True) or []
        for p in parents:
            curves.extend(c.listRelatives(p, allDescendents=True, type="nurbsCurve", fullPath=True) or [])
    meshes: List[str] = []
    for crv in curves:
        try:
            srf = c.planarSrf(crv, ch=False)[0]
            meshes.append(_nurbs_to_poly(srf))
        except Exception:
            continue
    if not meshes:
        return ToolResult(ok=False, error="未能从文字曲线生成网格（字形可能未闭合）", data={"root": root})

    if len(meshes) > 1:
        c.select(meshes, replace=True)
        united = c.polyUnite(ch=False)
        node = united[0] if isinstance(united, (list, tuple)) else united
    else:
        node = meshes[0]
    if name:
        try:
            node = c.rename(node, name)
        except Exception:
            pass
    if extrude and abs(float(extrude)) > 1e-8:
        try:
            c.polyExtrudeFacet(f"{node}.f[*]", ltz=float(extrude), keepFacesTogether=True)
        except Exception:
            pass
    if scale and abs(float(scale) - 1.0) > 1e-8:
        c.xform(node, ws=False, scale=[float(scale), float(scale), float(scale)])
    apply_world_transform(node, position=position)
    try:
        if c.objExists(root):
            c.delete(root)
    except Exception:
        pass
    try:
        c.delete(node, constructionHistory=True)
    except Exception:
        pass
    return ToolResult(ok=True, data={"name": node}, message=f"文字网格已创建: {node}")


@tool(
    name="thicken_mesh",
    description=(
        "给开放或封闭网格加厚度：挤出全部面并保持连体。"
        "正值沿法线向外，负值向内。适合板片实体化、墙体加厚。"
    ),
    parameters=obj_schema(
        {
            "name": {"type": "string", "default": ""},
            "thickness": {"type": "number", "default": 0.1},
            "divisions": {"type": "integer", "default": 1},
            "offset": {"type": "number", "default": 0},
        }
    ),
    category="modeling",
)
def thicken_mesh(
    name: str = "",
    thickness: float = 0.1,
    divisions: int = 1,
    offset: float = 0,
) -> ToolResult:
    c = _cmds()
    node = name or ((c.ls(selection=True) or [None])[0])
    if not node:
        return ToolResult(ok=False, error="无对象")
    tf = transform_of(node)
    try:
        result = c.polyExtrudeFacet(
            f"{tf}.f[*]",
            ltz=float(thickness),
            offset=float(offset),
            divisions=max(1, int(divisions)),
            keepFacesTogether=True,
        )
    except Exception as e:
        return ToolResult(ok=False, error=f"加厚失败: {e}")
    return ToolResult(ok=True, data={"name": tf, "result": result}, message=f"已加厚 {tf}（{thickness}）")


@tool(
    name="cleanup_mesh",
    description=(
        "网格清理：焊接顶点、删除历史、三角化/四边化、尝试去掉非流形。"
        "游戏导出前常用。有损操作，建议先确认。"
    ),
    parameters=obj_schema(
        {
            "names": {"type": "array", "items": {"type": "string"}, "default": []},
            "merge_vertices": {"type": "boolean", "default": True},
            "merge_threshold": {"type": "number", "default": 0.001},
            "delete_history": {"type": "boolean", "default": True},
            "freeze": {"type": "boolean", "default": True},
            "center_pivot": {"type": "boolean", "default": False},
            "triangulate": {"type": "boolean", "default": False},
            "quadrangulate": {"type": "boolean", "default": False},
            "soften_angle": {
                "type": "number",
                "default": -1,
                "description": ">=0 时按该角度软化边；-1=跳过",
            },
        }
    ),
    category="modeling",
    destructive=True,
)
def cleanup_mesh(
    names: Optional[List[str]] = None,
    merge_vertices: bool = True,
    merge_threshold: float = 0.001,
    delete_history: bool = True,
    freeze: bool = True,
    center_pivot: bool = False,
    triangulate: bool = False,
    quadrangulate: bool = False,
    soften_angle: float = -1,
) -> ToolResult:
    c = _cmds()
    roots = names or (c.ls(selection=True, long=True) or [])
    if not roots:
        return ToolResult(ok=False, error="无对象")
    done = []
    for root in roots:
        if not c.objExists(root):
            continue
        shapes = collect_mesh_shapes(root)
        tfs = list(dict.fromkeys(transform_of(s) for s in shapes)) or [root]
        for tf in tfs:
            if merge_vertices:
                try:
                    c.polyMergeVertex(tf, d=float(merge_threshold), am=True, ch=True)
                except Exception:
                    pass
            if triangulate:
                try:
                    c.polyTriangulate(tf)
                except Exception:
                    pass
            if quadrangulate:
                try:
                    c.polyQuad(tf, angle=30)
                except Exception:
                    pass
            if soften_angle is not None and float(soften_angle) >= 0:
                try:
                    c.polySoftEdge(tf, angle=float(soften_angle))
                except Exception:
                    pass
            if freeze:
                try:
                    c.makeIdentity(tf, apply=True, t=True, r=True, s=True, n=0)
                except Exception:
                    pass
            if center_pivot:
                try:
                    c.xform(tf, centerPivots=True)
                except Exception:
                    pass
            if delete_history:
                try:
                    c.delete(tf, constructionHistory=True)
                except Exception:
                    pass
            done.append(tf)
    return ToolResult(ok=True, data={"objects": done}, message=f"已清理 {len(done)} 个网格")
