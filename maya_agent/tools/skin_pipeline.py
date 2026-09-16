"""Skin pipeline tools: list skinned meshes, bake to world, strip rig, clean deformers.

Algorithms distilled from real MayaAgent sessions (skinned character → static geo):
- Capture world-space vertices via OpenMaya *before* resetting transform.
- Delete history + intermediate shapes.
- Parent to world, zero TRS *and* pivots (rotatePivot/scalePivot), then write points back.
- When cleaning deformers, do NOT delete groupId (breaks shading assignments).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from maya_agent.tools.registry import ToolResult, obj_schema, tool
from maya_agent.tools._maya import cmds as _cmds, in_maya

# Deformer / rig leftovers safe to strip after baking. groupId intentionally omitted.
_DEFAULT_CLEAN_TYPES = (
    "parentConstraint",
    "pointConstraint",
    "orientConstraint",
    "scaleConstraint",
    "aimConstraint",
    "poleVectorConstraint",
    "ikHandle",
    "follicle",
    "skinCluster",
    "blendShape",
    "cluster",
    "tweak",
    "wire",
    "lattice",
    "sculpt",
    "wrap",
    "deltaMush",
    "transformGeometry",
    "groupParts",
)


def _require_maya():
    if not in_maya():
        raise RuntimeError("未在 Maya 中运行")
    return _cmds()


def _unlock_trs(node: str) -> None:
    c = _cmds()
    for axis in "XYZ":
        for attr in (f"translate{axis}", f"rotate{axis}", f"scale{axis}"):
            try:
                c.setAttr(f"{node}.{attr}", lock=False)
            except Exception:
                pass


def _reset_identity_with_pivots(node: str) -> None:
    """Zero TRS and pivots — critical for meshes with non-zero rotatePivot (e.g. accessories)."""
    c = _cmds()
    c.setAttr(f"{node}.translate", 0, 0, 0)
    c.setAttr(f"{node}.rotate", 0, 0, 0)
    c.setAttr(f"{node}.scale", 1, 1, 1)
    for attr in (
        "rotatePivot",
        "scalePivot",
        "rotatePivotTranslate",
        "scalePivotTranslate",
    ):
        try:
            c.setAttr(f"{node}.{attr}", 0, 0, 0)
        except Exception:
            pass


def _final_shape_world_bbox(tf: str) -> Tuple[float, float, float, float, float, float]:
    """World bbox from the *final* mesh shape only (ignores intermediate Orig shapes)."""
    import maya.api.OpenMaya as om

    sel = om.MSelectionList()
    sel.add(tf)
    dag = sel.getDagPath(0)
    dag.extendToShape()
    fn = om.MFnMesh(dag)
    pts = fn.getPoints(om.MSpace.kWorld)
    xs = [p.x for p in pts]
    ys = [p.y for p in pts]
    zs = [p.z for p in pts]
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


def _collect_skinned_transforms() -> List[str]:
    c = _cmds()
    found: List[str] = []
    for shape in c.ls(type="mesh", noIntermediate=True) or []:
        hist = c.listHistory(shape, pdo=True) or []
        if any(c.nodeType(h) == "skinCluster" for h in hist):
            parents = c.listRelatives(shape, parent=True, fullPath=True) or []
            if parents:
                found.append(parents[0])
    return sorted(set(found))


def _skin_info(tf: str) -> Dict[str, Any]:
    c = _cmds()
    shapes = c.listRelatives(tf, shapes=True, type="mesh", fullPath=True, noIntermediate=True) or []
    clusters: List[str] = []
    influences: List[str] = []
    for shp in shapes:
        hist = c.listHistory(shp, pdo=True) or []
        for h in hist:
            if c.nodeType(h) == "skinCluster" and h not in clusters:
                clusters.append(h)
                try:
                    influences.extend(c.skinCluster(h, query=True, influence=True) or [])
                except Exception:
                    pass
    return {
        "transform": tf,
        "short": tf.split("|")[-1],
        "shapes": shapes,
        "skinClusters": clusters,
        "influence_count": len(set(influences)),
    }


def bake_mesh_world_space(tf: str) -> str:
    """
    Duplicate a mesh transform and bake its *current deformed / world* shape
    into a world-parented static mesh with identity transform + zero pivots.
    """
    import maya.api.OpenMaya as om

    c = _cmds()
    if not c.objExists(tf):
        raise ValueError(f"对象不存在: {tf}")

    dup = c.duplicate(tf, returnRootsOnly=True)[0]
    _unlock_trs(dup)

    # Capture world vertices while still under the original hierarchy (pose correct).
    sel = om.MSelectionList()
    sel.add(dup)
    dag = sel.getDagPath(0)
    dag.extendToShape()
    fnmesh = om.MFnMesh(dag)
    world_pts = fnmesh.getPoints(om.MSpace.kWorld)

    c.delete(dup, constructionHistory=True)
    for shp in c.listRelatives(dup, children=True, type="mesh", fullPath=True) or []:
        try:
            if c.getAttr(f"{shp}.intermediateObject"):
                c.delete(shp)
        except Exception:
            pass

    # Absorb parent transform into world, then flatten local TRS/pivots.
    try:
        c.parent(dup, world=True)
    except Exception:
        pass

    _reset_identity_with_pivots(dup)

    sel = om.MSelectionList()
    sel.add(dup)
    dag = sel.getDagPath(0)
    dag.extendToShape()
    fnmesh = om.MFnMesh(dag)
    # Transform is identity → object space == world space for these points.
    fnmesh.setPoints(world_pts, om.MSpace.kObject)
    return dup


def _bbox_error(
    a: Sequence[float], b: Sequence[float]
) -> float:
    return max(abs(x - y) for x, y in zip(a, b))


def _unique_name(base: str) -> str:
    c = _cmds()
    if not c.objExists(base):
        return base
    i = 1
    while c.objExists(f"{base}{i}"):
        i += 1
    return f"{base}{i}"


def _clean_node_types(
    types: Sequence[str],
    *,
    also_curves: bool = False,
    also_locators: bool = False,
    also_joints: bool = False,
    also_group_id: bool = False,
) -> Dict[str, int]:
    c = _cmds()
    type_list = list(types)
    if also_curves:
        type_list.append("nurbsCurve")
    if also_locators:
        type_list.append("locator")
    if also_joints:
        type_list.append("joint")
    if also_group_id:
        type_list.append("groupId")

    cleaned: Dict[str, int] = {}
    for t in type_list:
        try:
            nodes = c.ls(type=t) or []
        except Exception:
            continue
        if not nodes:
            continue
        try:
            c.delete(nodes)
            cleaned[t] = len(nodes)
        except Exception:
            # Partial delete: count survivors
            left = c.ls(type=t) or []
            removed = max(0, len(nodes) - len(left))
            if removed:
                cleaned[t] = removed
    return cleaned


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@tool(
    name="list_skinned_meshes",
    description=(
        "列出场景中带 skinCluster 的网格 transform（长名、skinCluster、影响骨骼数）。"
        "移除绑定/烘焙静态模型前建议先调用。"
    ),
    parameters=obj_schema({}),
    category="rigging",
)
def list_skinned_meshes() -> ToolResult:
    try:
        _require_maya()
    except RuntimeError as e:
        return ToolResult(ok=False, error=str(e))
    items = [_skin_info(tf) for tf in _collect_skinned_transforms()]
    return ToolResult(
        ok=True,
        data={"count": len(items), "meshes": items},
        message=f"找到 {len(items)} 个蒙皮网格",
    )


@tool(
    name="bake_mesh_to_world",
    description=(
        "将网格烘焙为世界坐标下的静态模型（identity 变换 + 清零 pivot）。"
        "适用于蒙皮网格：保留当前变形姿态，去掉 skinCluster 历史。"
        "names 为空且 skinned_only=true 时处理全部蒙皮网格。"
        "注意：对比 bbox 请用最终 shape 顶点，勿直接用含 intermediate 的 exactWorldBoundingBox。"
    ),
    parameters=obj_schema(
        {
            "names": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": "要烘焙的 transform；空则按 skinned_only / 选择",
            },
            "skinned_only": {
                "type": "boolean",
                "default": True,
                "description": "names 为空时是否只处理带 skinCluster 的网格",
            },
            "name_prefix": {
                "type": "string",
                "default": "BAKE_",
                "description": "新对象名前缀",
            },
            "group_name": {
                "type": "string",
                "default": "BakedGeo",
                "description": "归组名；空字符串表示不归组",
            },
            "tolerance": {
                "type": "number",
                "default": 0.01,
                "description": "与参考世界 bbox 误差超过此值则记入 warnings",
            },
        }
    ),
    category="rigging",
    destructive=True,
)
def bake_mesh_to_world(
    names: Optional[List[str]] = None,
    skinned_only: bool = True,
    name_prefix: str = "BAKE_",
    group_name: str = "BakedGeo",
    tolerance: float = 0.01,
) -> ToolResult:
    try:
        c = _require_maya()
    except RuntimeError as e:
        return ToolResult(ok=False, error=str(e))

    targets: List[str] = []
    if names:
        for n in names:
            if not c.objExists(n):
                return ToolResult(ok=False, error=f"对象不存在: {n}")
            long_n = (c.ls(n, long=True) or [n])[0]
            targets.append(long_n)
    elif skinned_only:
        targets = _collect_skinned_transforms()
    else:
        sel = c.ls(selection=True, type="transform", long=True) or []
        targets = sel

    if not targets:
        return ToolResult(ok=False, error="没有可烘焙的网格")

    baked: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    new_nodes: List[str] = []

    for tf in targets:
        try:
            ref = _final_shape_world_bbox(tf)
            dup = bake_mesh_world_space(tf)
            short = tf.split("|")[-1]
            new_name = c.rename(dup, _unique_name(f"{name_prefix}{short}"))
            new_bb = c.exactWorldBoundingBox(new_name)
            err = _bbox_error(ref, new_bb)
            entry = {
                "source": tf,
                "baked": new_name,
                "bbox_error": round(err, 6),
                "bbox": [round(x, 4) for x in new_bb],
            }
            baked.append(entry)
            new_nodes.append(new_name)
            if err > float(tolerance):
                warnings.append(entry)
        except Exception as e:
            return ToolResult(
                ok=False,
                error=f"烘焙失败 {tf}: {e}",
                data={"baked": baked, "warnings": warnings},
            )

    grp = ""
    if group_name and new_nodes:
        grp = _unique_name(group_name)
        grp = c.group(empty=True, name=grp)
        c.parent(new_nodes, grp)

    return ToolResult(
        ok=True,
        data={
            "count": len(baked),
            "group": grp or None,
            "baked": baked,
            "warnings": warnings,
        },
        message=(
            f"已烘焙 {len(baked)} 个网格"
            + (f" → {grp}" if grp else "")
            + (f"；{len(warnings)} 个误差超限" if warnings else "")
        ),
    )


@tool(
    name="delete_mesh_history",
    description=(
        "删除网格构造历史，并可选清理 intermediate（*ShapeOrig）形状。"
        "烘焙/导出前常用；不会移除 skinCluster 权重姿态（请用 bake_mesh_to_world）。"
    ),
    parameters=obj_schema(
        {
            "names": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": "空则用当前选择",
            },
            "clean_intermediate": {
                "type": "boolean",
                "default": True,
                "description": "删除 intermediateObject=True 的 mesh shape",
            },
        }
    ),
    category="rigging",
    destructive=True,
)
def delete_mesh_history(
    names: Optional[List[str]] = None,
    clean_intermediate: bool = True,
) -> ToolResult:
    try:
        c = _require_maya()
    except RuntimeError as e:
        return ToolResult(ok=False, error=str(e))

    targets = names or (c.ls(selection=True, long=True) or [])
    if not targets:
        return ToolResult(ok=False, error="无对象")

    removed_inter: List[str] = []
    for t in targets:
        if not c.objExists(t):
            continue
        try:
            c.delete(t, constructionHistory=True)
        except Exception as e:
            return ToolResult(ok=False, error=f"删除历史失败 {t}: {e}")
        if clean_intermediate:
            for shp in c.listRelatives(t, children=True, type="mesh", fullPath=True) or []:
                try:
                    if c.getAttr(f"{shp}.intermediateObject"):
                        c.delete(shp)
                        removed_inter.append(shp)
                except Exception:
                    pass

    return ToolResult(
        ok=True,
        data={"targets": targets, "removed_intermediate": removed_inter},
        message=f"已清理 {len(targets)} 个对象历史"
        + (f"，删除 {len(removed_inter)} 个 intermediate" if removed_inter else ""),
    )


@tool(
    name="clean_rig_nodes",
    description=(
        "清理绑定残留：约束、IK、skinCluster、常见 deformer 等。"
        "默认保留 groupId 以免破坏材质（shadingEngine）分配。"
        "可选删除控制器曲线、locator、骨骼。"
    ),
    parameters=obj_schema(
        {
            "delete_controls": {
                "type": "boolean",
                "default": True,
                "description": "删除 nurbsCurve（常见控制器）",
            },
            "delete_locators": {"type": "boolean", "default": True},
            "delete_joints": {
                "type": "boolean",
                "default": False,
                "description": "删除全部 joint（危险，确认后再开）",
            },
            "delete_group_id": {
                "type": "boolean",
                "default": False,
                "description": "删除 groupId；通常会破坏材质分配，默认关闭",
            },
            "extra_types": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": "额外要删的节点类型",
            },
        }
    ),
    category="rigging",
    destructive=True,
)
def clean_rig_nodes(
    delete_controls: bool = True,
    delete_locators: bool = True,
    delete_joints: bool = False,
    delete_group_id: bool = False,
    extra_types: Optional[List[str]] = None,
) -> ToolResult:
    try:
        _require_maya()
    except RuntimeError as e:
        return ToolResult(ok=False, error=str(e))

    types = list(_DEFAULT_CLEAN_TYPES)
    if extra_types:
        types.extend(extra_types)
    cleaned = _clean_node_types(
        types,
        also_curves=delete_controls,
        also_locators=delete_locators,
        also_joints=delete_joints,
        also_group_id=delete_group_id,
    )
    return ToolResult(
        ok=True,
        data={"cleaned": cleaned, "total_removed": sum(cleaned.values())},
        message=f"已清理 {sum(cleaned.values())} 个节点" if cleaned else "无可清理节点",
    )


@tool(
    name="extract_skinned_geometry",
    description=(
        "一键：烘焙全部（或指定）蒙皮网格为静态模型，归组，再删除绑定根节点/骨骼/控制器并清理 deformer。"
        "用于「移除骨骼和控制器，只留蒙皮模型」。"
        "默认不删 groupId，以保留材质。若传入 delete_roots（如角色 Rig 顶组），会删除这些层级（含其下原始蒙皮网格）。"
    ),
    parameters=obj_schema(
        {
            "names": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": "指定蒙皮 transform；空则处理场景中全部蒙皮网格",
            },
            "group_name": {"type": "string", "default": "BakedGeo"},
            "name_prefix": {"type": "string", "default": "BAKE_"},
            "delete_roots": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": "烘焙后删除的绑定/角色根节点（如 MyChar_Rig）",
            },
            "delete_joints": {
                "type": "boolean",
                "default": True,
                "description": "删除场景中剩余 joint",
            },
            "delete_controls": {
                "type": "boolean",
                "default": True,
                "description": "删除 nurbsCurve / locator 控制器",
            },
            "clean_deformers": {
                "type": "boolean",
                "default": True,
                "description": "清理约束、skinCluster、常见 deformer",
            },
            "tolerance": {"type": "number", "default": 0.01},
        }
    ),
    category="rigging",
    destructive=True,
)
def extract_skinned_geometry(
    names: Optional[List[str]] = None,
    group_name: str = "BakedGeo",
    name_prefix: str = "BAKE_",
    delete_roots: Optional[List[str]] = None,
    delete_joints: bool = True,
    delete_controls: bool = True,
    clean_deformers: bool = True,
    tolerance: float = 0.01,
) -> ToolResult:
    try:
        c = _require_maya()
    except RuntimeError as e:
        return ToolResult(ok=False, error=str(e))

    bake_result = bake_mesh_to_world(
        names=names or [],
        skinned_only=not bool(names),
        name_prefix=name_prefix,
        group_name=group_name,
        tolerance=tolerance,
    )
    if not bake_result.ok:
        return bake_result

    deleted_roots: List[str] = []
    for root in delete_roots or []:
        if root and c.objExists(root):
            try:
                c.delete(root)
                deleted_roots.append(root)
            except Exception as e:
                return ToolResult(
                    ok=False,
                    error=f"删除根节点失败 {root}: {e}",
                    data=bake_result.data,
                )

    cleaned: Dict[str, int] = {}
    if clean_deformers or delete_joints or delete_controls:
        cleaned = _clean_node_types(
            _DEFAULT_CLEAN_TYPES if clean_deformers else [],
            also_curves=delete_controls,
            also_locators=delete_controls,
            also_joints=delete_joints,
            also_group_id=False,
        )

    # Scene summary
    summary = {
        "mesh": len(c.ls(type="mesh", noIntermediate=True) or []),
        "joint": len(c.ls(type="joint") or []),
        "skinCluster": len(c.ls(type="skinCluster") or []),
        "nurbsCurve": len(c.ls(type="nurbsCurve") or []),
        "ikHandle": len(c.ls(type="ikHandle") or []),
        "constraint": len(c.ls(type="constraint") or []),
    }

    data = dict(bake_result.data or {})
    data.update(
        {
            "deleted_roots": deleted_roots,
            "cleaned": cleaned,
            "summary": summary,
        }
    )
    return ToolResult(
        ok=True,
        data=data,
        message=(
            f"已提取静态几何 {data.get('count', 0)} 个"
            + (f"，删除根 {deleted_roots}" if deleted_roots else "")
            + f"；残留 joint={summary['joint']} skin={summary['skinCluster']}"
        ),
    )
