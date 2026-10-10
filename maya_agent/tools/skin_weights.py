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


# ---------------------------------------------------------------------------
# Align + transfer (Meshy / mismatched transforms)
# ---------------------------------------------------------------------------


def _world_bbox_mesh(mesh: str) -> Tuple[float, float, float, float, float, float]:
    """World-space AABB from final mesh shape vertices (skinned pose)."""
    import maya.api.OpenMaya as om

    tf = _mesh_transform(mesh)
    sel = om.MSelectionList()
    sel.add(tf)
    dag = sel.getDagPath(0)
    dag.extendToShape()
    fn = om.MFnMesh(dag)
    pts = fn.getPoints(om.MSpace.kWorld)
    if not pts:
        raise ValueError(f"网格无顶点: {tf}")
    xs = [p.x for p in pts]
    ys = [p.y for p in pts]
    zs = [p.z for p in pts]
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


def _combined_world_bbox(
    meshes: Sequence[str],
) -> Tuple[float, float, float, float, float, float]:
    bbs = [_world_bbox_mesh(m) for m in meshes]
    return (
        min(b[0] for b in bbs),
        min(b[1] for b in bbs),
        min(b[2] for b in bbs),
        max(b[3] for b in bbs),
        max(b[4] for b in bbs),
        max(b[5] for b in bbs),
    )


def _bbox_metrics(bb: Tuple[float, float, float, float, float, float]) -> Dict[str, Any]:
    xmin, ymin, zmin, xmax, ymax, zmax = bb
    return {
        "bbox": [round(v, 4) for v in bb],
        "center": (
            (xmin + xmax) * 0.5,
            (ymin + ymax) * 0.5,
            (zmin + zmax) * 0.5,
        ),
        "feet": (
            (xmin + xmax) * 0.5,
            ymin,
            (zmin + zmax) * 0.5,
        ),
        "size": (xmax - xmin, ymax - ymin, zmax - zmin),
        "height": ymax - ymin,
    }


def _skin_influences(mesh: str) -> List[str]:
    c = _cmds()
    sc = _skin_cluster(mesh)
    return list(c.skinCluster(sc, query=True, influence=True) or [])


def _common_dag_ancestor(nodes: Sequence[str]) -> Optional[str]:
    """Longest common DAG parent path shared by all nodes (exclusive of the nodes)."""
    c = _cmds()
    paths: List[List[str]] = []
    for n in nodes:
        if not n or not c.objExists(n):
            continue
        long = (c.ls(n, long=True) or [n])[0]
        parts = [p for p in long.split("|") if p]
        if len(parts) < 2:
            continue
        paths.append(parts[:-1])  # exclude self
    if not paths:
        return None
    common: List[str] = []
    for segs in zip(*paths):
        if len(set(segs)) == 1:
            common.append(segs[0])
        else:
            break
    if not common:
        return None
    return "|" + "|".join(common)


def _assembly_root(node: str) -> str:
    """Top-level DAG under the world for a node (e.g. |Armature, |char1)."""
    c = _cmds()
    long = (c.ls(node, long=True) or [node])[0]
    parts = [p for p in long.split("|") if p]
    if not parts:
        return long
    return "|" + parts[0]


def _infer_align_root(source_mesh: str) -> str:
    """
    Prefer the transform that owns the joints (Armature), not the mesh itself.
    Meshy imports often have |Armature and |char1 as world siblings.
    """
    c = _cmds()
    inf = _skin_influences(source_mesh)
    if not inf:
        return _assembly_root(_mesh_transform(source_mesh))

    # Walk up from first joint; prefer named armature/rig transform
    cur = (c.ls(inf[0], long=True) or [inf[0]])[0]
    fallback = _assembly_root(cur)
    for _ in range(16):
        if not c.objExists(cur):
            break
        short = cur.split("|")[-1].lower()
        nt = c.nodeType(cur)
        if nt == "transform" and (
            short in ("armature", "root", "rig", "skeleton", "skel")
            or "armature" in short
            or short.endswith("_rig")
            or short.endswith("_skel")
        ):
            return cur
        parents = c.listRelatives(cur, parent=True, fullPath=True) or []
        if not parents:
            break
        cur = parents[0]

    anc = _common_dag_ancestor(inf)
    if anc and c.objExists(anc):
        return _assembly_root(anc)
    return fallback


def _nodes_to_align(source_mesh: str, align_root: str) -> List[str]:
    """
    World assemblies that must move/scale together.

    Meshy: |Armature (joints) + |char1 (skinned mesh) are siblings — moving only
    Armature leaves bind-pose mesh transform behind in some scenes; moving only
    the mesh leaves the skeleton offset (classic 'green bones beside character').
    Always transform both assemblies when they differ.
    """
    c = _cmds()
    root = _assembly_root(align_root)
    mesh_top = _assembly_root(source_mesh)
    out: List[str] = []
    for n in (root, mesh_top):
        if n and c.objExists(n) and n not in out:
            out.append(n)
    if not out:
        raise ValueError("未找到可对齐的根节点")
    return out


def _bbox_overlap_ratio(
    a: Tuple[float, float, float, float, float, float],
    b: Tuple[float, float, float, float, float, float],
) -> float:
    """Axis-aligned bbox intersection volume / min(volume_a, volume_b)."""
    ix0, iy0, iz0 = max(a[0], b[0]), max(a[1], b[1]), max(a[2], b[2])
    ix1, iy1, iz1 = min(a[3], b[3]), min(a[4], b[4]), min(a[5], b[5])
    if ix1 <= ix0 or iy1 <= iy0 or iz1 <= iz0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0) * (iz1 - iz0)
    va = max(1e-12, (a[3] - a[0]) * (a[4] - a[1]) * (a[5] - a[2]))
    vb = max(1e-12, (b[3] - b[0]) * (b[4] - b[1]) * (b[5] - b[2]))
    return float(inter / min(va, vb))


def _snap_rig_root_to_target(
    *,
    source_mesh: str,
    target_meshes: Sequence[str],
    align_root: str = "",
    match: str = "feet",
    uniform_scale: bool = True,
    scale_tolerance: float = 0.02,
    max_pivot_error: float = 2.0,
) -> Dict[str, Any]:
    """
    Uniform-scale + world-translate so the *skinned* source mesh bbox matches
    the combined target bbox.

    Moves Armature **and** the source-mesh assembly together (Meshy sibling
    layout). Scale/translate use the source feet/center as world pivot so both
    stay locked. Do not move nodes back after weight transfer.
    """
    c = _cmds()
    src = _mesh_transform(source_mesh)
    targets = [_mesh_transform(t) for t in target_meshes]
    root = _long(align_root) if (align_root or "").strip() else _infer_align_root(src)
    if not c.objExists(root):
        raise ValueError(f"对齐根节点不存在: {root}")
    movers = _nodes_to_align(src, root)

    src_bb = _world_bbox_mesh(src)
    dst_bb = _combined_world_bbox(targets)
    src_m = _bbox_metrics(src_bb)
    dst_m = _bbox_metrics(dst_bb)
    src_h = float(src_m["height"])
    dst_h = float(dst_m["height"])
    if src_h < 1e-6 or dst_h < 1e-6:
        raise ValueError("源或目标包围盒高度过小，无法对齐")

    match = (match or "feet").strip().lower()
    if match not in ("feet", "center"):
        raise ValueError("match 必须是 feet 或 center")
    pivot_key = "feet" if match == "feet" else "center"
    dst_pivot = dst_m[pivot_key]

    before_states = {
        n: {
            "translate": list(c.xform(n, query=True, worldSpace=True, translation=True)),
            "scale": list(c.getAttr(f"{n}.scale")[0]),
            "rotate": list(c.xform(n, query=True, worldSpace=True, rotation=True)),
        }
        for n in movers
    }

    # Already overlapping enough → skip (avoid double-align drift)
    pre_err = sum(abs(src_m[pivot_key][i] - dst_m[pivot_key][i]) for i in range(3))
    pre_overlap = _bbox_overlap_ratio(src_bb, dst_bb)
    height_ratio = dst_h / src_h
    if (
        pre_err <= float(max_pivot_error)
        and pre_overlap >= 0.35
        and abs(height_ratio - 1.0) <= float(scale_tolerance)
    ):
        return {
            "align_root": root,
            "movers": movers,
            "match": match,
            "scale_applied": 1.0,
            "translation_delta": [0.0, 0.0, 0.0],
            "source_before": src_m,
            "target": dst_m,
            "source_after": src_m,
            "skipped": True,
            "feet_error": round(pre_err, 5),
            "overlap_ratio": round(pre_overlap, 4),
            "root_before": before_states.get(root),
            "root_after": before_states.get(root),
        }

    scale = 1.0
    if uniform_scale and abs(height_ratio - 1.0) > float(scale_tolerance):
        scale = height_ratio
        # Scale every mover about the *current* source pivot (world)
        pivot = list(src_m[pivot_key])
        for n in movers:
            c.scale(
                scale,
                scale,
                scale,
                n,
                relative=True,
                pivot=pivot,
                worldSpace=True,
            )

    src_m_mid = _bbox_metrics(_world_bbox_mesh(src))
    src_pivot = src_m_mid[pivot_key]
    delta = (
        dst_pivot[0] - src_pivot[0],
        dst_pivot[1] - src_pivot[1],
        dst_pivot[2] - src_pivot[2],
    )
    if any(abs(v) > 1e-9 for v in delta):
        for n in movers:
            c.move(delta[0], delta[1], delta[2], n, relative=True, worldSpace=True)

    after_bb = _world_bbox_mesh(src)
    after_src = _bbox_metrics(after_bb)
    err = sum(abs(after_src[pivot_key][i] - dst_m[pivot_key][i]) for i in range(3))
    overlap = _bbox_overlap_ratio(after_bb, dst_bb)

    # If feet match failed (odd proportions), retry center translation once
    if err > float(max_pivot_error) and match == "feet":
        c_delta = (
            dst_m["center"][0] - after_src["center"][0],
            dst_m["center"][1] - after_src["center"][1],
            dst_m["center"][2] - after_src["center"][2],
        )
        if any(abs(v) > 1e-9 for v in c_delta):
            for n in movers:
                c.move(
                    c_delta[0],
                    c_delta[1],
                    c_delta[2],
                    n,
                    relative=True,
                    worldSpace=True,
                )
            delta = (delta[0] + c_delta[0], delta[1] + c_delta[1], delta[2] + c_delta[2])
            after_bb = _world_bbox_mesh(src)
            after_src = _bbox_metrics(after_bb)
            err = sum(
                abs(after_src["center"][i] - dst_m["center"][i]) for i in range(3)
            )
            overlap = _bbox_overlap_ratio(after_bb, dst_bb)
            match = "center_fallback"

    after_states = {
        n: {
            "translate": list(c.xform(n, query=True, worldSpace=True, translation=True)),
            "scale": list(c.getAttr(f"{n}.scale")[0]),
            "rotate": list(c.xform(n, query=True, worldSpace=True, rotation=True)),
        }
        for n in movers
    }

    if err > float(max_pivot_error) and overlap < 0.15:
        raise ValueError(
            f"对齐后仍偏差过大（pivot_error={err:.3f}, overlap={overlap:.3f}）。"
            f"已移动: {movers}。请检查源网格是否为 Meshy 蒙皮网格、目标是否为原角色分件，"
            "或手动指定 align_root=Armature。"
        )

    return {
        "align_root": root,
        "movers": movers,
        "match": match,
        "scale_applied": scale,
        "translation_delta": [round(v, 5) for v in delta],
        "source_before": src_m,
        "target": dst_m,
        "source_after": after_src,
        "skipped": False,
        "feet_error": round(err, 5),
        "overlap_ratio": round(overlap, 4),
        "root_before": before_states.get(_assembly_root(root)),
        "root_after": after_states.get(_assembly_root(root)),
        "mover_before": before_states,
        "mover_after": after_states,
    }


def _ensure_bound_to_influences(
    mesh: str,
    influences: Sequence[str],
    *,
    max_influences: int = 4,
) -> str:
    """Return skinCluster on mesh; bind to influences if missing."""
    c = _cmds()
    tf = _mesh_transform(mesh)
    try:
        return _skin_cluster(tf)
    except ValueError:
        pass
    joints = [j for j in influences if c.objExists(j)]
    if not joints:
        raise ValueError(f"无法绑定 {tf}：没有有效影响骨")
    c.select(joints, replace=True)
    c.select(tf, add=True)
    sc = c.skinCluster(
        toSelectedBones=True,
        bindMethod=0,
        normalizeWeights=1,
        maximumInfluences=max(1, int(max_influences)),
        obeyMaxInfluences=True,
        dropoffRate=4.0,
        removeUnusedInfluence=False,
    )
    return sc[0] if isinstance(sc, (list, tuple)) else str(sc)


def _do_copy_skin_weights(source: str, destination: str, *, no_mirror: bool = True) -> Dict[str, Any]:
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
    return {"source": src, "destination": dst, "source_skin": ss, "dest_skin": ds}


@tool(
    name="align_skinned_rig",
    description=(
        "把 Meshy/错位蒙皮源对齐到目标网格（或分件合并包围盒）。"
        "同时移动 Armature 与源网格顶层节点（兄弟层级常见），按脚底对齐并可选均匀缩放。"
        "在 copy_skin_weights / transfer_skin_weights 前调用；对齐后保持，不要移回。"
    ),
    parameters=obj_schema(
        {
            "source_mesh": {
                "type": "string",
                "description": "已蒙皮的源网格（如 Meshy 的 char1）",
            },
            "target_meshes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "对齐目标：原角色网格或分件列表",
            },
            "align_root": {
                "type": "string",
                "default": "",
                "description": "骨架根（默认自动推断 Armature）",
            },
            "match": {
                "type": "string",
                "enum": ["feet", "center"],
                "default": "feet",
            },
            "uniform_scale": {"type": "boolean", "default": True},
            "scale_tolerance": {
                "type": "number",
                "default": 0.02,
                "description": "高度比与 1 的偏差小于此值则不缩放",
            },
            "max_pivot_error": {
                "type": "number",
                "default": 2.0,
                "description": "对齐后脚底/中心允许的最大偏差（场景单位）",
            },
        },
        required=["source_mesh", "target_meshes"],
    ),
    category="rigging",
    destructive=True,
)
def align_skinned_rig(
    source_mesh: str,
    target_meshes: List[str],
    align_root: str = "",
    match: str = "feet",
    uniform_scale: bool = True,
    scale_tolerance: float = 0.02,
    max_pivot_error: float = 2.0,
) -> ToolResult:
    try:
        _require_maya()
        if not target_meshes:
            return ToolResult(ok=False, error="target_meshes 不能为空")
        info = _snap_rig_root_to_target(
            source_mesh=source_mesh,
            target_meshes=target_meshes,
            align_root=align_root,
            match=match,
            uniform_scale=bool(uniform_scale),
            scale_tolerance=float(scale_tolerance),
            max_pivot_error=float(max_pivot_error),
        )
        skipped = "（已重叠，跳过）" if info.get("skipped") else ""
        return ToolResult(
            ok=True,
            data=info,
            message=(
                f"已对齐 movers={info.get('movers')} → 目标"
                f"{skipped}（scale={info['scale_applied']:.4f}, "
                f"feet_error={info['feet_error']}, overlap={info.get('overlap_ratio')}）"
            ),
        )
    except Exception as e:
        return ToolResult(ok=False, error=str(e))


@tool(
    name="copy_skin_weights",
    description=(
        "在两网格间传递蒙皮权重（copySkinWeights，按最近点 + 最近关节）。"
        "默认 align=true：先把源侧 Armature+蒙皮网格一起对齐到目标再拷贝（修复 Meshy 错位）。"
        "对齐会保留，拷完不能把骨架移回。多目标请用 transfer_skin_weights。"
    ),
    parameters=obj_schema(
        {
            "source": {"type": "string"},
            "destination": {"type": "string"},
            "no_mirror": {"type": "boolean", "default": True},
            "align": {
                "type": "boolean",
                "default": True,
                "description": "拷贝前对齐源骨架+源网格到目标",
            },
            "align_root": {"type": "string", "default": ""},
            "match": {
                "type": "string",
                "enum": ["feet", "center"],
                "default": "feet",
            },
            "uniform_scale": {"type": "boolean", "default": True},
            "max_pivot_error": {"type": "number", "default": 2.0},
        },
        required=["source", "destination"],
    ),
    category="rigging",
    destructive=True,
)
def copy_skin_weights(
    source: str,
    destination: str,
    no_mirror: bool = True,
    align: bool = True,
    align_root: str = "",
    match: str = "feet",
    uniform_scale: bool = True,
    max_pivot_error: float = 2.0,
) -> ToolResult:
    try:
        _require_maya()
        src = _mesh_transform(source)
        dst = _mesh_transform(destination)
        align_info = None
        if align:
            align_info = _snap_rig_root_to_target(
                source_mesh=src,
                target_meshes=[dst],
                align_root=align_root,
                match=match,
                uniform_scale=bool(uniform_scale),
                max_pivot_error=float(max_pivot_error),
            )
        data = _do_copy_skin_weights(src, dst, no_mirror=no_mirror)
        data["aligned"] = bool(align)
        if align_info:
            data["align"] = align_info
        msg = f"权重已复制 {src} → {dst}"
        if align_info:
            msg += (
                f"；对齐 movers={align_info.get('movers')} "
                f"feet_error={align_info['feet_error']} "
                f"overlap={align_info.get('overlap_ratio')}"
            )
        return ToolResult(ok=True, data=data, message=msg)
    except Exception as e:
        return ToolResult(ok=False, error=str(e))


@tool(
    name="transfer_skin_weights",
    description=(
        "批量：Meshy 合并蒙皮体 → 原始分件。默认先把 Armature+源网格对齐到分件包围盒，"
        "再自动 bind 并 closestPoint 拷权重。对齐保留，勿移回错位骨架。"
    ),
    parameters=obj_schema(
        {
            "source": {
                "type": "string",
                "description": "Meshy 蒙皮网格，如 char1 / Jinx_Skinned",
            },
            "destinations": {
                "type": "array",
                "items": {"type": "string"},
                "description": "原始分件网格列表",
            },
            "align": {"type": "boolean", "default": True},
            "align_root": {"type": "string", "default": ""},
            "match": {
                "type": "string",
                "enum": ["feet", "center"],
                "default": "feet",
            },
            "uniform_scale": {"type": "boolean", "default": True},
            "max_pivot_error": {"type": "number", "default": 2.0},
            "auto_bind": {
                "type": "boolean",
                "default": True,
                "description": "目标无 skinCluster 时自动绑定到源影响骨",
            },
            "max_influences": {"type": "integer", "default": 4},
            "no_mirror": {"type": "boolean", "default": True},
        },
        required=["source", "destinations"],
    ),
    category="rigging",
    destructive=True,
)
def transfer_skin_weights(
    source: str,
    destinations: List[str],
    align: bool = True,
    align_root: str = "",
    match: str = "feet",
    uniform_scale: bool = True,
    max_pivot_error: float = 2.0,
    auto_bind: bool = True,
    max_influences: int = 4,
    no_mirror: bool = True,
) -> ToolResult:
    try:
        _require_maya()
        if not destinations:
            return ToolResult(ok=False, error="destinations 不能为空")
        src = _mesh_transform(source)
        dests = [_mesh_transform(d) for d in destinations]
        influences = _skin_influences(src)

        align_info = None
        if align:
            align_info = _snap_rig_root_to_target(
                source_mesh=src,
                target_meshes=dests,
                align_root=align_root,
                match=match,
                uniform_scale=bool(uniform_scale),
                max_pivot_error=float(max_pivot_error),
            )

        results: List[Dict[str, Any]] = []
        errors: List[str] = []
        for dst in dests:
            try:
                if auto_bind:
                    _ensure_bound_to_influences(
                        dst, influences, max_influences=max_influences
                    )
                info = _do_copy_skin_weights(src, dst, no_mirror=no_mirror)
                results.append(info)
            except Exception as e:
                errors.append(f"{dst}: {e}")

        ok = len(results) > 0 and not errors
        partial = len(results) > 0 and bool(errors)
        data: Dict[str, Any] = {
            "source": src,
            "copied": results,
            "errors": errors,
            "influence_count": len(influences),
            "aligned": bool(align),
        }
        if align_info:
            data["align"] = align_info
        msg = f"已传递权重 {src} → {len(results)}/{len(dests)} 个网格"
        if align_info:
            msg += (
                f"；movers={align_info.get('movers')} "
                f"feet_error={align_info['feet_error']} "
                f"overlap={align_info.get('overlap_ratio')}"
            )
        if errors:
            msg += f"；失败 {len(errors)} 个"
        return ToolResult(ok=ok or partial, data=data, message=msg, error="; ".join(errors[:5]))
    except Exception as e:
        return ToolResult(ok=False, error=str(e))
