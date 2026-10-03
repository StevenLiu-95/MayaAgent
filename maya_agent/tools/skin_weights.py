"""Skin-weight read / write / analyze tools (OpenMaya API).

Built from MayaAgent skinning sessions: bind tools exist, but QC and repair
need exact weight I/O, remote-influence reports, prune/limit, and mirroring.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from maya_agent.tools.registry import ToolResult, obj_schema, tool
from maya_agent.tools._maya import cmds as _cmds, in_maya

_EPS = 1e-5
_SAMPLE_LIMIT = 24


def _require_maya():
    if not in_maya():
        raise RuntimeError("未在 Maya 中运行")
    return _cmds()


def _long(name: str) -> str:
    c = _cmds()
    longs = c.ls(name, long=True) or []
    return longs[0] if longs else name


def _mesh_shape(mesh: str) -> str:
    c = _cmds()
    if not c.objExists(mesh):
        raise ValueError(f"对象不存在: {mesh}")
    if c.nodeType(mesh) == "mesh":
        return mesh
    shapes = c.listRelatives(mesh, shapes=True, type="mesh", fullPath=True, noIntermediate=True) or []
    if not shapes:
        raise ValueError(f"未找到 mesh shape: {mesh}")
    return shapes[0]


def _mesh_transform(mesh: str) -> str:
    c = _cmds()
    if c.nodeType(mesh) == "mesh":
        parents = c.listRelatives(mesh, parent=True, fullPath=True) or []
        return parents[0] if parents else mesh
    return _long(mesh)


def _skin_cluster(mesh: str) -> str:
    c = _cmds()
    shp = _mesh_shape(mesh)
    hist = c.listHistory(shp, pruneDagObjects=True) or []
    skins = [h for h in hist if c.nodeType(h) == "skinCluster"]
    if not skins:
        raise ValueError(f"未找到 skinCluster: {mesh}")
    return skins[0]


def _fn_skin(mesh: str):
    import maya.api.OpenMaya as om
    import maya.api.OpenMayaAnim as oma

    sc = _skin_cluster(mesh)
    tf = _mesh_transform(mesh)
    s1 = om.MSelectionList()
    s1.add(sc)
    fn = oma.MFnSkinCluster(s1.getDependNode(0))
    s2 = om.MSelectionList()
    s2.add(tf)
    dag = s2.getDagPath(0)
    dag.extendToShape()
    return fn, dag, sc


def _influence_names(fn) -> List[str]:
    return [o.partialPathName() for o in fn.influenceObjects()]


def _resolve_joint(names: Sequence[str], joint: str) -> str:
    if joint in names:
        return joint
    short = joint.split("|")[-1]
    for n in names:
        if n == short or n.split("|")[-1] == short:
            return n
        if n.endswith("|" + short):
            return n
    raise ValueError(f"不是该 skinCluster 的影响骨: {joint}（可选: {list(names)[:12]}…）")


def _vert_count(mesh: str) -> int:
    return int(_cmds().polyEvaluate(_mesh_shape(mesh), vertex=True) or 0)


def _component_range(n: int, indices: Optional[Sequence[int]] = None):
    import maya.api.OpenMaya as om

    fnc = om.MFnSingleIndexedComponent()
    comp = fnc.create(om.MFn.kMeshVertComponent)
    if indices is None:
        fnc.addElements(list(range(n)))
    else:
        clean = sorted({int(i) for i in indices if 0 <= int(i) < n})
        if not clean:
            raise ValueError("顶点索引为空或越界")
        fnc.addElements(clean)
        n = len(clean)
    return fnc, comp, n


def get_weight_rows(
    mesh: str,
    *,
    indices: Optional[Sequence[int]] = None,
    min_weight: float = _EPS,
) -> Tuple[List[Dict[str, float]], List[str], List[int]]:
    import maya.api.OpenMaya as om

    fn, dag, _sc = _fn_skin(mesh)
    names = _influence_names(fn)
    n = _vert_count(mesh)
    _fnc, comp, count = _component_range(n, indices)
    w, inf_count = fn.getWeights(dag, comp)
    n_inf = int(inf_count)
    rows: List[Dict[str, float]] = []
    used_idx = list(range(n)) if indices is None else sorted({int(i) for i in indices if 0 <= int(i) < n})
    for i in range(count):
        d: Dict[str, float] = {}
        base = i * n_inf
        for k, nm in enumerate(names):
            v = float(w[base + k])
            if v > min_weight:
                d[nm] = v
        rows.append(d)
    return rows, names, used_idx


def set_weight_rows(
    mesh: str,
    wlist: Sequence[Dict[str, float]],
    *,
    indices: Optional[Sequence[int]] = None,
) -> int:
    import maya.api.OpenMaya as om

    fn, dag, _sc = _fn_skin(mesh)
    names = _influence_names(fn)
    col = {nm: k for k, nm in enumerate(names)}
    objs = fn.influenceObjects()
    all_idx = om.MIntArray([fn.indexForInfluenceObject(o) for o in objs])
    n = _vert_count(mesh)
    if indices is None:
        if len(wlist) != n:
            raise ValueError(f"权重行数 {len(wlist)} 与顶点数 {n} 不符")
        used = list(range(n))
    else:
        used = sorted({int(i) for i in indices if 0 <= int(i) < n})
        if len(wlist) != len(used):
            raise ValueError(f"权重行数 {len(wlist)} 与指定顶点数 {len(used)} 不符")
    unknown = {j for w in wlist for j in w if j not in col}
    resolved: Dict[str, str] = {}
    still = []
    for j in unknown:
        try:
            resolved[j] = _resolve_joint(names, j)
        except ValueError:
            still.append(j)
    if still:
        raise ValueError(f"不是该 skinCluster 的影响骨: {sorted(still)}")

    flat: List[float] = []
    n_inf = len(names)
    for w in wlist:
        row = [0.0] * n_inf
        mapped: Dict[str, float] = {}
        for j, v in w.items():
            mapped[resolved.get(j, j)] = float(v)
        s = sum(mapped.values()) or 1.0
        for j, v in mapped.items():
            row[col[j]] = v / s
        flat.extend(row)

    _fnc, comp, _ = _component_range(n, used)
    fn.setWeights(dag, comp, all_idx, om.MDoubleArray(flat), False)
    return len(used)


def _influence_totals(rows: Sequence[Dict[str, float]]) -> Dict[str, float]:
    tot: Dict[str, float] = {}
    for w in rows:
        for k, v in w.items():
            tot[k] = tot.get(k, 0.0) + float(v)
    return {k: round(v, 4) for k, v in sorted(tot.items(), key=lambda kv: -kv[1])}


def _world_points(mesh: str) -> List[Tuple[float, float, float]]:
    c = _cmds()
    tf = _mesh_transform(mesh)
    n = _vert_count(mesh)
    return [
        tuple(float(x) for x in c.pointPosition(f"{tf}.vtx[{i}]", world=True))
        for i in range(n)
    ]


def _joint_world(name: str) -> Optional[Tuple[float, float, float]]:
    c = _cmds()
    if not c.objExists(name):
        return None
    t = c.xform(name, q=True, ws=True, t=True)
    return float(t[0]), float(t[1]), float(t[2])


def _mesh_bbox(mesh: str) -> Dict[str, Any]:
    c = _cmds()
    tf = _mesh_transform(mesh)
    bb = c.exactWorldBoundingBox(tf)
    size = [float(bb[3] - bb[0]), float(bb[4] - bb[1]), float(bb[5] - bb[2])]
    return {
        "min": [float(bb[0]), float(bb[1]), float(bb[2])],
        "max": [float(bb[3]), float(bb[4]), float(bb[5])],
        "center": [0.5 * (bb[0] + bb[3]), 0.5 * (bb[1] + bb[4]), 0.5 * (bb[2] + bb[5])],
        "size": size,
        "diagonal": float((size[0] ** 2 + size[1] ** 2 + size[2] ** 2) ** 0.5),
    }


def _sample_rows(
    rows: Sequence[Dict[str, float]],
    indices: Sequence[int],
    limit: int = _SAMPLE_LIMIT,
) -> List[Dict[str, Any]]:
    out = []
    for i, w in zip(indices, rows):
        if len(out) >= limit:
            break
        out.append({"index": int(i), "weights": {k: round(v, 4) for k, v in w.items()}})
    return out


def _resolve_meshes(meshes: Optional[List[str]]) -> List[str]:
    c = _cmds()
    names = [m for m in (meshes or []) if m]
    if not names:
        names = c.ls(selection=True, long=True) or []
    out = []
    for m in names:
        try:
            out.append(_mesh_transform(m))
        except Exception:
            continue
    return list(dict.fromkeys(out))


@tool(
    name="get_skin_weights",
    description=(
        "读取网格 skinCluster 权重。默认返回影响骨列表、每骨权重总和、使用的最大影响数；"
        "include_per_vertex=true 或指定 vertex_indices 时才返回逐顶点字典（大网格请抽样，避免撑爆上下文）。"
        "写入请用 set_skin_weights（未列出的影响骨会被置 0）。"
    ),
    parameters=obj_schema(
        {
            "mesh": {"type": "string", "description": "蒙皮网格 transform 或 shape"},
            "include_per_vertex": {
                "type": "boolean",
                "default": False,
                "description": "是否返回逐顶点权重；顶点数大时请用 vertex_indices 抽样",
            },
            "vertex_indices": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "只读这些顶点；空则全部",
            },
            "min_weight": {"type": "number", "default": 0.00001},
            "sample": {
                "type": "integer",
                "default": 8,
                "description": "未开 include_per_vertex 时附带的样例顶点数",
            },
        },
        required=["mesh"],
    ),
    category="rigging",
)
def get_skin_weights(
    mesh: str,
    include_per_vertex: bool = False,
    vertex_indices: Optional[List[int]] = None,
    min_weight: float = _EPS,
    sample: int = 8,
) -> ToolResult:
    try:
        _require_maya()
        tf = _mesh_transform(mesh)
        sc = _skin_cluster(tf)
        n = _vert_count(tf)
        idx = list(vertex_indices) if vertex_indices else None
        if include_per_vertex or idx is not None:
            rows, names, used = get_weight_rows(tf, indices=idx, min_weight=min_weight)
            data: Dict[str, Any] = {
                "mesh": tf,
                "skinCluster": sc,
                "vertex_count": n,
                "read_count": len(used),
                "influences": names,
                "influence_count": len(names),
                "influence_totals": _influence_totals(rows),
                "max_influences_used": max((len(w) for w in rows), default=0),
            }
            if include_per_vertex:
                if len(rows) > 800:
                    return ToolResult(
                        ok=False,
                        error=(
                            f"逐顶点权重 {len(rows)} 条过大。请缩小 vertex_indices，"
                            "或设 include_per_vertex=false 只看汇总。"
                        ),
                        data={"mesh": tf, "vertex_count": n, "influences": names},
                    )
                data["vertices"] = [
                    {"index": used[i], "weights": rows[i]} for i in range(len(rows))
                ]
            else:
                data["sample"] = _sample_rows(rows, used, max(1, min(int(sample), 40)))
        else:
            rows, names, used = get_weight_rows(tf, min_weight=min_weight)
            data = {
                "mesh": tf,
                "skinCluster": sc,
                "vertex_count": n,
                "influences": names,
                "influence_count": len(names),
                "influence_totals": _influence_totals(rows),
                "max_influences_used": max((len(w) for w in rows), default=0),
                "bbox": _mesh_bbox(tf),
                "sample": _sample_rows(rows, used, max(1, min(int(sample), 40))),
            }
        return ToolResult(
            ok=True,
            data=data,
            message=(
                f"{tf}: {n} 顶点 / {len(data['influences'])} 影响骨 / "
                f"单点最多 {data['max_influences_used']} 骨"
            ),
        )
    except Exception as e:
        return ToolResult(ok=False, error=str(e))


@tool(
    name="set_skin_weights",
    description=(
        "精确写入蒙皮权重（OpenMaya setWeights，未列出的影响骨置 0 再归一化）。"
        "三种用法：1) joint=某骨 → 指定顶点（或全部）100% 跟该骨；"
        "2) drop_influences=[骨名] → 剔除后把剩余权重重新归一；"
        "3) vertex_weights=[{index, weights:{关节:值}}] 逐点覆盖。"
        "大网格刚性绑定优先用 joint=，不要传全顶点数组。"
    ),
    parameters=obj_schema(
        {
            "mesh": {"type": "string"},
            "joint": {
                "type": "string",
                "default": "",
                "description": "刚性：全部或 vertices 指定点 100% 跟此骨",
            },
            "vertices": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "与 joint= 合用：只改这些顶点",
            },
            "drop_influences": {
                "type": "array",
                "items": {"type": "string"},
                "description": "从现有权重中剔除这些骨并归一化",
            },
            "vertex_weights": {
                "type": "array",
                "items": {"type": "object"},
                "description": "[{index:int, weights:{joint:float}}]",
            },
        },
        required=["mesh"],
    ),
    category="rigging",
    destructive=True,
)
def set_skin_weights(
    mesh: str,
    joint: str = "",
    vertices: Optional[List[int]] = None,
    drop_influences: Optional[List[str]] = None,
    vertex_weights: Optional[List[Dict[str, Any]]] = None,
) -> ToolResult:
    try:
        _require_maya()
        tf = _mesh_transform(mesh)
        n = _vert_count(tf)
        modes = [
            bool((joint or "").strip()),
            bool(drop_influences),
            bool(vertex_weights),
        ]
        if sum(1 for m in modes if m) != 1:
            return ToolResult(
                ok=False,
                error="请只选一种写法：joint= 或 drop_influences= 或 vertex_weights=",
            )

        if (joint or "").strip():
            idx = list(vertices) if vertices else None
            count = len(idx) if idx is not None else n
            rows = [{joint: 1.0}] * count
            wrote = set_weight_rows(tf, rows, indices=idx)
            return ToolResult(
                ok=True,
                data={"mesh": tf, "joint": joint, "vertices_written": wrote},
                message=f"{tf}: {wrote} 顶点 → {joint} 100%",
            )

        if drop_influences:
            drop = set(drop_influences)
            rows, names, used = get_weight_rows(tf)
            n_changed = 0
            out = []
            for w in rows:
                d = {k: v for k, v in w.items() if k not in drop and k.split("|")[-1] not in drop}
                if len(d) != len(w):
                    n_changed += 1
                s = sum(d.values()) or 1.0
                out.append({k: v / s for k, v in d.items()} if d else w)
            wrote = set_weight_rows(tf, out)
            return ToolResult(
                ok=True,
                data={
                    "mesh": tf,
                    "dropped": list(drop),
                    "vertices_changed": n_changed,
                    "vertices_written": wrote,
                    "influences": names,
                },
                message=f"{tf}: 剔除 {list(drop)}，改写 {n_changed}/{wrote} 顶点",
            )

        items = list(vertex_weights or [])
        if len(items) > 2000:
            return ToolResult(ok=False, error="vertex_weights 超过 2000 条，请分批或改用 joint=/drop_influences=")
        idx = []
        rows = []
        for item in items:
            if not isinstance(item, dict):
                continue
            i = int(item.get("index", -1))
            w = item.get("weights") or {}
            if i < 0 or i >= n or not isinstance(w, dict):
                continue
            idx.append(i)
            rows.append({str(k): float(v) for k, v in w.items()})
        if not idx:
            return ToolResult(ok=False, error="vertex_weights 为空或索引无效")
        wrote = set_weight_rows(tf, rows, indices=idx)
        return ToolResult(
            ok=True,
            data={"mesh": tf, "vertices_written": wrote},
            message=f"{tf}: 已写入 {wrote} 个顶点权重",
        )
    except Exception as e:
        return ToolResult(ok=False, error=str(e))


@tool(
    name="analyze_skin_weights",
    description=(
        "蒙皮权重体检：权重和≠1、零权重顶点、单点影响数>max_influences、"
        "每骨权重总和、以及『顶点距离影响骨过远』的泄漏样本。"
        "绑完/修完权重后调用；可对多个网格或当前选择。"
    ),
    parameters=obj_schema(
        {
            "meshes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "空则用当前选择",
            },
            "max_influences": {
                "type": "integer",
                "default": 4,
                "description": "游戏管线常用 4；超过则记入 over_influenced",
            },
            "distance_ratio": {
                "type": "number",
                "default": 0.55,
                "description": "顶点到主影响骨距离 > bbox对角×该值 视为远端泄漏",
            },
            "flag_prefixes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "额外点名的影响骨前缀，如 Hair、Eye_、Finger",
            },
        }
    ),
    category="rigging",
)
def analyze_skin_weights(
    meshes: Optional[List[str]] = None,
    max_influences: int = 4,
    distance_ratio: float = 0.55,
    flag_prefixes: Optional[List[str]] = None,
) -> ToolResult:
    try:
        _require_maya()
        targets = _resolve_meshes(meshes)
        if not targets:
            return ToolResult(ok=False, error="无网格可检查（传入 meshes 或先选择）")
        prefixes = tuple(flag_prefixes or [])
        reports = []
        issues = 0
        for tf in targets:
            try:
                rows, names, used = get_weight_rows(tf)
                pts = _world_points(tf)
                bbox = _mesh_bbox(tf)
                diag = max(float(bbox["diagonal"]), 1.0)
                joint_pos = {nm: _joint_world(nm) for nm in names}
                denorm = []
                zero = []
                over = []
                distant = []
                flagged: Dict[str, float] = {}
                for i, w in enumerate(rows):
                    s = sum(w.values())
                    if s < _EPS:
                        zero.append(i)
                    elif abs(s - 1.0) > 0.02:
                        if len(denorm) < 12:
                            denorm.append({"index": i, "sum": round(s, 4)})
                    if len(w) > int(max_influences):
                        if len(over) < 12:
                            over.append({"index": i, "count": len(w), "joints": list(w)[:8]})
                    if prefixes:
                        for k, v in w.items():
                            if k.startswith(prefixes) and v > 0.02:
                                flagged[k] = flagged.get(k, 0.0) + v
                    if w and i < len(pts):
                        main = max(w.items(), key=lambda kv: kv[1])[0]
                        jp = joint_pos.get(main)
                        if jp:
                            dx = pts[i][0] - jp[0]
                            dy = pts[i][1] - jp[1]
                            dz = pts[i][2] - jp[2]
                            dist = (dx * dx + dy * dy + dz * dz) ** 0.5
                            if dist > diag * float(distance_ratio) and w[main] > 0.2:
                                if len(distant) < 12:
                                    distant.append(
                                        {
                                            "index": i,
                                            "joint": main,
                                            "weight": round(w[main], 3),
                                            "distance": round(dist, 2),
                                        }
                                    )
                item = {
                    "mesh": tf,
                    "vertex_count": len(rows),
                    "influence_count": len(names),
                    "influence_totals": _influence_totals(rows),
                    "max_influences_used": max((len(w) for w in rows), default=0),
                    "zero_weight_count": len(zero),
                    "denormalized_count": sum(1 for w in rows if abs(sum(w.values()) - 1.0) > 0.02),
                    "over_influenced_count": sum(1 for w in rows if len(w) > int(max_influences)),
                    "distant_leak_samples": distant,
                    "denormalized_samples": denorm,
                    "over_influenced_samples": over,
                    "bbox": bbox,
                }
                if prefixes:
                    item["flagged_influence_totals"] = {
                        k: round(v, 2) for k, v in sorted(flagged.items(), key=lambda kv: -kv[1])[:24]
                    }
                reports.append(item)
                issues += (
                    item["zero_weight_count"]
                    + item["denormalized_count"]
                    + item["over_influenced_count"]
                    + len(distant)
                )
            except Exception as e:
                reports.append({"mesh": tf, "error": str(e)})
                issues += 1
        return ToolResult(
            ok=True,
            data={"count": len(reports), "issue_score": issues, "meshes": reports},
            message=f"已体检 {len(reports)} 个网格（issue_score={issues}）",
        )
    except Exception as e:
        return ToolResult(ok=False, error=str(e))


@tool(
    name="prune_skin_weights",
    description="按阈值剔除微小影响并可选归一化（导出前常用）。",
    parameters=obj_schema(
        {
            "mesh": {"type": "string"},
            "threshold": {"type": "number", "default": 0.01},
            "normalize": {"type": "boolean", "default": True},
        },
        required=["mesh"],
    ),
    category="rigging",
    destructive=True,
)
def prune_skin_weights(mesh: str, threshold: float = 0.01, normalize: bool = True) -> ToolResult:
    try:
        _require_maya()
        c = _cmds()
        tf = _mesh_transform(mesh)
        sc = _skin_cluster(tf)
        c.skinPercent(sc, tf, pruneWeights=float(threshold))
        if normalize:
            c.skinCluster(sc, edit=True, forceNormalizeWeights=True)
        rows, _names, _ = get_weight_rows(tf)
        return ToolResult(
            ok=True,
            data={
                "mesh": tf,
                "skinCluster": sc,
                "threshold": threshold,
                "max_influences_used": max((len(w) for w in rows), default=0),
            },
            message=f"{tf}: 已 prune < {threshold}" + (" 并归一化" if normalize else ""),
        )
    except Exception as e:
        return ToolResult(ok=False, error=str(e))


@tool(
    name="normalize_skin_weights",
    description="强制 skinCluster 权重归一化（每顶点总和=1）。",
    parameters=obj_schema({"mesh": {"type": "string"}}, required=["mesh"]),
    category="rigging",
    destructive=True,
)
def normalize_skin_weights(mesh: str) -> ToolResult:
    try:
        _require_maya()
        tf = _mesh_transform(mesh)
        sc = _skin_cluster(tf)
        _cmds().skinCluster(sc, edit=True, forceNormalizeWeights=True)
        return ToolResult(ok=True, data={"mesh": tf, "skinCluster": sc}, message=f"{tf}: 已归一化")
    except Exception as e:
        return ToolResult(ok=False, error=str(e))


@tool(
    name="limit_skin_influences",
    description=(
        "将每顶点影响骨裁到 max_influences（保留权重最大的 N 根并归一化）。"
        "UE/Unity 导出前常用 max_influences=4。"
    ),
    parameters=obj_schema(
        {
            "mesh": {"type": "string"},
            "max_influences": {"type": "integer", "default": 4},
        },
        required=["mesh"],
    ),
    category="rigging",
    destructive=True,
)
def limit_skin_influences(mesh: str, max_influences: int = 4) -> ToolResult:
    try:
        _require_maya()
        tf = _mesh_transform(mesh)
        cap = max(1, int(max_influences))
        rows, names, _ = get_weight_rows(tf)
        changed = 0
        out = []
        for w in rows:
            if len(w) <= cap:
                out.append(w)
                continue
            top = sorted(w.items(), key=lambda kv: -kv[1])[:cap]
            s = sum(v for _k, v in top) or 1.0
            out.append({k: v / s for k, v in top})
            changed += 1
        wrote = set_weight_rows(tf, out)
        sc = _skin_cluster(tf)
        try:
            _cmds().skinCluster(sc, edit=True, maximumInfluences=cap, obeyMaxInfluences=True)
        except Exception:
            pass
        return ToolResult(
            ok=True,
            data={
                "mesh": tf,
                "max_influences": cap,
                "vertices_changed": changed,
                "vertices_written": wrote,
                "influence_count": len(names),
            },
            message=f"{tf}: {changed}/{wrote} 顶点裁到 ≤{cap} 骨",
        )
    except Exception as e:
        return ToolResult(ok=False, error=str(e))


def _mirror_joint(name: str) -> str:
    if name.endswith("_L"):
        return name[:-2] + "_R"
    if name.endswith("_R"):
        return name[:-2] + "_L"
    if name.endswith("_l"):
        return name[:-2] + "_r"
    if name.endswith("_r"):
        return name[:-2] + "_l"
    low = name.lower()
    if "_left" in low:
        return name.replace("Left", "Right").replace("left", "right")
    if "_right" in low:
        return name.replace("Right", "Left").replace("right", "left")
    return name


@tool(
    name="mirror_skin_weights",
    description=(
        "左右镜像蒙皮权重。mode=average 按镜像顶点平均（修不对称）；"
        "mode=copy 用 Maya copySkinWeights 从一侧拷到另一侧。"
        "默认按世界 X 轴、关节名 _L/_R 互换。"
    ),
    parameters=obj_schema(
        {
            "mesh": {"type": "string"},
            "mode": {
                "type": "string",
                "enum": ["average", "copy"],
                "default": "average",
            },
            "tolerance": {
                "type": "number",
                "default": 0.5,
                "description": "镜像点匹配容差（世界单位）",
            },
        },
        required=["mesh"],
    ),
    category="rigging",
    destructive=True,
)
def mirror_skin_weights(mesh: str, mode: str = "average", tolerance: float = 0.5) -> ToolResult:
    try:
        _require_maya()
        c = _cmds()
        tf = _mesh_transform(mesh)
        sc = _skin_cluster(tf)
        if mode == "copy":
            c.copySkinWeights(
                ss=sc,
                ds=sc,
                mirrorMode="YZ",
                surfaceAssociation="closestPoint",
                influenceAssociation=["oneToOne", "closestJoint"],
            )
            return ToolResult(
                ok=True,
                data={"mesh": tf, "mode": "copy"},
                message=f"{tf}: 已 copySkinWeights 镜像（YZ）",
            )

        rows, _names, _ = get_weight_rows(tf)
        pts = _world_points(tf)
        tol = max(float(tolerance), 1e-4)
        buckets: Dict[Tuple[int, int, int], List[int]] = {}
        for i, p in enumerate(pts):
            key = (round(p[0] / tol), round(p[1] / tol), round(p[2] / tol))
            buckets.setdefault(key, []).append(i)

        def _find(px, py, pz) -> Optional[int]:
            key = (round(px / tol), round(py / tol), round(pz / tol))
            cand = buckets.get(key) or []
            if not cand:
                return None
            return min(
                cand,
                key=lambda j: abs(pts[j][0] - px) + abs(pts[j][1] - py) + abs(pts[j][2] - pz),
            )

        out = []
        matched = 0
        for i, p in enumerate(pts):
            j = _find(-p[0], p[1], p[2])
            if j is None:
                out.append(dict(rows[i]))
                continue
            acc: Dict[str, float] = {}
            for k, v in rows[i].items():
                acc[k] = acc.get(k, 0.0) + 0.5 * v
            for k, v in rows[j].items():
                mk = _mirror_joint(k)
                acc[mk] = acc.get(mk, 0.0) + 0.5 * v
            out.append({k: v for k, v in acc.items() if v > _EPS})
            matched += 1
        wrote = set_weight_rows(tf, out)
        return ToolResult(
            ok=True,
            data={"mesh": tf, "mode": "average", "matched": matched, "vertices_written": wrote},
            message=f"{tf}: 镜像平均匹配 {matched}/{wrote} 顶点",
        )
    except Exception as e:
        return ToolResult(ok=False, error=str(e))


@tool(
    name="smooth_skin_weights",
    description="平滑蒙皮权重（Maya skinCluster smoothWeights）。可限制在当前选择的顶点。",
    parameters=obj_schema(
        {
            "mesh": {"type": "string"},
            "iterations": {"type": "integer", "default": 2},
            "factor": {"type": "number", "default": 0.5},
            "use_selection": {
                "type": "boolean",
                "default": False,
                "description": "true 时只平滑当前选中的顶点",
            },
        },
        required=["mesh"],
    ),
    category="rigging",
    destructive=True,
)
def smooth_skin_weights(
    mesh: str,
    iterations: int = 2,
    factor: float = 0.5,
    use_selection: bool = False,
) -> ToolResult:
    try:
        _require_maya()
        c = _cmds()
        tf = _mesh_transform(mesh)
        sc = _skin_cluster(tf)
        prev = c.ls(selection=True, long=True) or []
        try:
            if not use_selection:
                c.select(tf, replace=True)
            for _ in range(max(1, int(iterations))):
                c.skinCluster(sc, edit=True, smoothWeights=float(factor))
        finally:
            try:
                if prev:
                    c.select(prev, replace=True)
                else:
                    c.select(clear=True)
            except Exception:
                pass
        return ToolResult(
            ok=True,
            data={"mesh": tf, "iterations": iterations, "factor": factor},
            message=f"{tf}: 平滑 {iterations} 次",
        )
    except Exception as e:
        return ToolResult(ok=False, error=str(e))


@tool(
    name="copy_skin_weights",
    description="在两网格间传递蒙皮权重（copySkinWeights，按最近点 + 最近关节）。",
    parameters=obj_schema(
        {
            "source": {"type": "string"},
            "destination": {"type": "string"},
            "no_mirror": {"type": "boolean", "default": True},
        },
        required=["source", "destination"],
    ),
    category="rigging",
    destructive=True,
)
def copy_skin_weights(source: str, destination: str, no_mirror: bool = True) -> ToolResult:
    try:
        _require_maya()
        c = _cmds()
        src = _mesh_transform(source)
        dst = _mesh_transform(destination)
        ss = _skin_cluster(src)
        ds = _skin_cluster(dst)
        c.copySkinWeights(
            ss=ss,
            ds=ds,
            noMirror=bool(no_mirror),
            surfaceAssociation="closestPoint",
            influenceAssociation=["closestJoint", "oneToOne", "label"],
        )
        return ToolResult(
            ok=True,
            data={"source": src, "destination": dst, "source_skin": ss, "dest_skin": ds},
            message=f"权重已复制 {src} → {dst}",
        )
    except Exception as e:
        return ToolResult(ok=False, error=str(e))
