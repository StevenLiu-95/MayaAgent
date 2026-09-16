"""Native SkinCage: loft limb tubes along deform joints, unite, skinCluster.

Inspired by AdvancedSkeleton asCreateSkinCage / asBuildChainCurves, but
implemented with pure maya.cmds (no ADV MEL).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from maya_agent.tools.registry import ToolResult, obj_schema, tool
from maya_agent.tools._maya import cmds as _cmds, in_maya


def _require():
    if not in_maya():
        raise RuntimeError("未在 Maya 中运行")
    return _cmds()


def _short(n: str) -> str:
    return n.split("|")[-1]


def _world_pos(node: str) -> Tuple[float, float, float]:
    c = _cmds()
    p = c.xform(node, q=True, ws=True, t=True)
    return float(p[0]), float(p[1]), float(p[2])


def _distance(a: Sequence[float], b: Sequence[float]) -> float:
    return (
        (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2
    ) ** 0.5


def _unique(name: str) -> str:
    c = _cmds()
    if not c.objExists(name):
        return name
    i = 1
    while c.objExists(f"{name}{i}"):
        i += 1
    return f"{name}{i}"


def _collect_joints(root: str) -> List[str]:
    c = _cmds()
    if not c.objExists(root):
        raise ValueError(f"根骨骼不存在: {root}")
    kids = c.listRelatives(root, allDescendents=True, type="joint", fullPath=True) or []
    # Prefer short names for stability
    out = [_short(root)]
    for k in kids:
        sn = _short(k)
        if sn not in out:
            out.append(sn)
    return out


def _chain_from(start: str, stop_names: Sequence[str]) -> List[str]:
    """Walk children preferring the first joint child until a stop or leaf."""
    c = _cmds()
    chain = [start]
    cur = start
    stops = set(stop_names)
    for _ in range(64):
        kids = c.listRelatives(cur, children=True, type="joint") or []
        if not kids:
            break
        # Prefer continuing same limb: first child not branching to mid names
        nxt = kids[0]
        for k in kids:
            if k in stops:
                continue
            nxt = k
            break
        if nxt in stops and nxt != start:
            break
        chain.append(nxt)
        cur = nxt
        if cur in stops:
            break
    return chain


def _detect_chains(root: str) -> List[List[str]]:
    """Heuristic limb chains for SkinCage loft."""
    c = _cmds()
    all_j = _collect_joints(root)
    by_role: Dict[str, List[str]] = {}
    for j in all_j:
        role = ""
        if c.attributeQuery("ikRole", node=j, exists=True):
            try:
                role = c.getAttr(f"{j}.ikRole") or ""
            except Exception:
                role = ""
        if not role:
            # name heuristic
            low = j.lower()
            for key, r in (
                ("shoulder", "shoulder"),
                ("hip", "hip"),
                ("thigh", "hip"),
                ("root", "root"),
                ("chest", "chest"),
                ("spine", "spine"),
                ("tail", "tail"),
                ("neck", "neck"),
                ("head", "head"),
            ):
                if key in low:
                    role = r
                    break
        by_role.setdefault(role or "other", []).append(j)

    chains: List[List[str]] = []

    # Spine: Root -> ... -> Head
    if c.objExists("Root_M"):
        spine = []
        cur = "Root_M"
        spine.append(cur)
        for name in (
            "Spine1_M", "Spine2_M", "Spine3_M", "Spine4_M", "Spine5_M",
            "Chest_M", "Neck_M", "Neck1_M", "Neck2_M", "Neck3_M", "Neck4_M",
            "Head_M", "HeadEnd_M",
        ):
            if c.objExists(name):
                spine.append(name)
        if len(spine) >= 2:
            chains.append(spine)

    # Arms / legs by side
    for side in ("_R", "_L"):
        for start, end_hint in (
            (f"Shoulder{side}", f"Wrist{side}"),
            (f"UpperArm{side}", f"Hand{side}"),
            (f"Hip{side}", f"Ankle{side}"),
            (f"Thigh{side}", f"Foot{side}"),
        ):
            if not c.objExists(start):
                continue
            chain = [start]
            cur = start
            for _ in range(12):
                kids = c.listRelatives(cur, children=True, type="joint") or []
                if not kids:
                    break
                # pick child continuing the limb (skip fingers hanging off wrist early)
                nxt = None
                for k in kids:
                    kn = _short(k)
                    if any(x in kn for x in ("Finger", "Thumb", "Cup", "Toe", "Heel", "Eye", "Jaw")):
                        continue
                    nxt = kn
                    break
                if nxt is None:
                    nxt = _short(kids[0])
                chain.append(nxt)
                cur = nxt
                if end_hint and cur == end_hint:
                    break
                if any(x in cur for x in ("Wrist", "Hand", "Ankle", "Foot")):
                    break
            if len(chain) >= 2:
                chains.append(chain)

    # Tail
    tails = [j for j in all_j if "Tail" in j and j.endswith("_M")]
    if len(tails) >= 2:
        # sort by name
        tails_sorted = sorted(tails)
        chains.append(tails_sorted)

    # Deduplicate identical chains
    uniq = []
    seen = set()
    for ch in chains:
        key = tuple(ch)
        if key not in seen:
            seen.add(key)
            uniq.append(ch)
    return uniq


def _profile_radius(joint: str, radius_scale: float) -> float:
    c = _cmds()
    fat = 1.0
    if c.attributeQuery("fat", node=joint, exists=True):
        try:
            fat = float(c.getAttr(f"{joint}.fat") or 1.0)
        except Exception:
            fat = 1.0
    # bone length estimate
    kids = c.listRelatives(joint, children=True, type="joint") or []
    length = 1.0
    if kids:
        length = max(_distance(_world_pos(joint), _world_pos(kids[0])), 0.2)
    return max(length * 0.35 * fat * radius_scale, 0.15)


def _cross(a: Sequence[float], b: Sequence[float]) -> Tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _norm(v: Sequence[float]) -> Tuple[float, float, float]:
    l = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) or 1.0
    return (v[0] / l, v[1] / l, v[2] / l)


def _square_profile(
    center: Sequence[float],
    radius: float,
    name: str,
    axis: Optional[Sequence[float]] = None,
) -> str:
    """Square closed curve centered at joint, plane perpendicular to bone axis."""
    c = _cmds()
    x, y, z = center
    r = radius
    ax = _norm(axis) if axis else (0.0, 1.0, 0.0)
    # Build orthonormal basis (u, v) in plane ⊥ axis
    up = (0.0, 1.0, 0.0) if abs(ax[1]) < 0.9 else (1.0, 0.0, 0.0)
    u = _norm(_cross(ax, up))
    v = _norm(_cross(ax, u))
    corners = [(-r, -r), (r, -r), (r, r), (-r, r), (-r, -r)]
    pts = [
        (
            x + u[0] * a + v[0] * b,
            y + u[1] * a + v[1] * b,
            z + u[2] * a + v[2] * b,
        )
        for a, b in corners
    ]
    return c.curve(name=_unique(name), degree=1, point=pts)


def _loft_chain_to_poly(chain: List[str], radius_scale: float) -> Optional[str]:
    c = _cmds()
    if len(chain) < 2:
        return None
    curves = []
    for i, j in enumerate(chain):
        if not c.objExists(j):
            continue
        pos = _world_pos(j)
        rad = _profile_radius(j, radius_scale)
        # Axis toward next (or from previous) joint
        if i + 1 < len(chain) and c.objExists(chain[i + 1]):
            nxt = _world_pos(chain[i + 1])
            axis = (nxt[0] - pos[0], nxt[1] - pos[1], nxt[2] - pos[2])
        elif i > 0 and c.objExists(chain[i - 1]):
            prv = _world_pos(chain[i - 1])
            axis = (pos[0] - prv[0], pos[1] - prv[1], pos[2] - prv[2])
        else:
            axis = (0.0, 1.0, 0.0)
        crv = _square_profile(pos, rad, f"cageCrv_{_short(j)}", axis=axis)
        curves.append(crv)
    if len(curves) < 2:
        for crv in curves:
            try:
                c.delete(crv)
            except Exception:
                pass
        return None
    loft_node = None
    poly = None
    try:
        loft_node = c.loft(curves, ch=False, uniform=True, close=False, degree=1, polygon=0)[0]
        poly = c.nurbsToPoly(
            loft_node,
            mnd=1,
            ch=False,
            f=3,
            pt=1,
            pc=200,
            chr=0.1,
            ft=0.01,
            mel=0.001,
            d=0.1,
            ut=1,
            un=3,
            vt=1,
            vn=3,
            uch=0,
            ucr=0,
            cht=0.2,
            n=_unique(f"cageSeg_{_short(chain[0])}"),
        )[0]
    except Exception:
        poly = None
    for node in curves:
        try:
            c.delete(node)
        except Exception:
            pass
    if loft_node and c.objExists(loft_node):
        try:
            c.delete(loft_node)
        except Exception:
            pass
    return poly


@tool(
    name="create_skin_cage",
    description=(
        "沿变形骨骼链自动生成 SkinCage（剖面曲线 loft → 多边形合并 → 对 cage 蒙皮）。"
        "纯 maya.cmds，不依赖 AdvancedSkeleton。"
        "root_joint 默认 Root_M；生成后可用 bind_from_skin_cage 把权重拷到角色网格。"
    ),
    parameters=obj_schema(
        {
            "root_joint": {
                "type": "string",
                "default": "Root_M",
                "description": "变形骨根",
            },
            "radius_scale": {
                "type": "number",
                "default": 1.0,
                "description": "Cage 粗细倍率（读取关节 fat 属性）",
            },
            "cage_name": {"type": "string", "default": "skinCage"},
            "group_name": {"type": "string", "default": "Geometry"},
        }
    ),
    category="rigging",
    destructive=True,
)
def create_skin_cage(
    root_joint: str = "Root_M",
    radius_scale: float = 1.0,
    cage_name: str = "skinCage",
    group_name: str = "Geometry",
) -> ToolResult:
    try:
        c = _require()
    except RuntimeError as e:
        return ToolResult(ok=False, error=str(e))

    root = root_joint or "Root_M"
    if not c.objExists(root):
        # try find any Root*
        candidates = c.ls("Root*", type="joint") or []
        if not candidates:
            return ToolResult(ok=False, error=f"找不到根骨骼: {root}")
        root = candidates[0]

    chains = _detect_chains(root)
    if not chains:
        return ToolResult(ok=False, error="未能识别可用于 SkinCage 的骨骼链")

    segments: List[str] = []
    for ch in chains:
        poly = _loft_chain_to_poly(ch, float(radius_scale))
        if poly:
            segments.append(poly)

    if not segments:
        return ToolResult(ok=False, error="SkinCage 分段生成失败")

    # Unite
    cage = _unique(cage_name)
    try:
        if len(segments) == 1:
            cage = c.rename(segments[0], cage)
        else:
            united = c.polyUnite(segments, ch=False, mergeUVSets=1, name=cage)[0]
            cage = united
            try:
                c.delete(segments)  # leftovers if any
            except Exception:
                pass
        c.polyMergeVertex(cage, d=0.05, am=True, ch=False)
    except Exception as e:
        return ToolResult(ok=False, error=f"合并 SkinCage 失败: {e}", data={"segments": segments})

    # Influences: all joints under root excluding end helpers
    influences = []
    for j in _collect_joints(root):
        if any(x in j for x in ("End", "Heel", "Eye", "JawEnd", "HeadEnd", "ToesEnd")):
            continue
        influences.append(j)

    skin = ""
    try:
        c.select(influences, replace=True)
        c.select(cage, add=True)
        skin = c.skinCluster(
            toSelectedBones=True,
            bindMethod=0,
            normalizeWeights=1,
            maximumInfluences=3,
            obeyMaxInfluences=True,
            name=_unique("skinClusterSkinCage"),
        )[0]
    except Exception as e:
        return ToolResult(
            ok=False,
            error=f"Cage 已创建但蒙皮失败: {e}",
            data={"cage": cage, "influences": influences},
        )

    grp = group_name
    if grp:
        if not c.objExists(grp):
            grp = c.group(empty=True, name=_unique(grp))
        try:
            c.parent(cage, grp)
        except Exception:
            pass

    return ToolResult(
        ok=True,
        data={
            "cage": cage,
            "skinCluster": skin,
            "influences": influences,
            "chains": chains,
            "group": grp,
        },
        message=f"已创建 SkinCage「{cage}」（{len(chains)} 条链，{len(influences)} 影响骨）",
    )


@tool(
    name="bind_from_skin_cage",
    description=(
        "将 SkinCage 的蒙皮权重拷贝到角色网格（copySkinWeights）。"
        "若未提供 cage，则对网格与骨骼做标准 smooth bind。"
        "不依赖 AdvancedSkeleton。"
    ),
    parameters=obj_schema(
        {
            "meshes": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": "目标网格；空则用当前选择",
            },
            "cage": {
                "type": "string",
                "default": "",
                "description": "SkinCage 节点名；空则尝试 skinCage",
            },
            "influences": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": "无 cage 时用于 smooth bind 的骨骼；空则用 Root_M 层级",
            },
            "max_influences": {"type": "integer", "default": 4},
        }
    ),
    category="rigging",
    destructive=True,
)
def bind_from_skin_cage(
    meshes: Optional[List[str]] = None,
    cage: str = "",
    influences: Optional[List[str]] = None,
    max_influences: int = 4,
) -> ToolResult:
    try:
        c = _require()
    except RuntimeError as e:
        return ToolResult(ok=False, error=str(e))

    targets: List[str] = list(meshes or [])
    if not targets:
        sel = c.ls(selection=True, long=True) or []
        for t in sel:
            if c.listRelatives(t, shapes=True, type="mesh", noIntermediate=True):
                targets.append(t)
    if not targets:
        return ToolResult(ok=False, error="未指定网格且选择中没有 mesh")

    cage_node = cage or ("skinCage" if c.objExists("skinCage") else "")
    results: List[Dict[str, Any]] = []

    if cage_node and c.objExists(cage_node):
        # influences from cage skinCluster
        hist = c.listHistory(cage_node) or []
        cage_skins = c.ls(hist, type="skinCluster") or []
        if not cage_skins:
            return ToolResult(ok=False, error=f"{cage_node} 上没有 skinCluster，请先 create_skin_cage")
        cage_skin = cage_skins[0]
        infs = c.skinCluster(cage_skin, q=True, influence=True) or []
        for mesh in targets:
            try:
                # remove existing skin
                mh = c.listHistory(mesh) or []
                for s in c.ls(mh, type="skinCluster") or []:
                    c.skinCluster(s, e=True, unbind=True)
                c.select(infs, replace=True)
                c.select(mesh, add=True)
                new_skin = c.skinCluster(
                    toSelectedBones=True,
                    bindMethod=0,
                    normalizeWeights=1,
                    maximumInfluences=int(max_influences),
                    obeyMaxInfluences=True,
                )[0]
                c.copySkinWeights(
                    sourceSkin=cage_skin,
                    destinationSkin=new_skin,
                    noMirror=True,
                    surfaceAssociation="closestPoint",
                    influenceAssociation=["closestJoint", "oneToOne"],
                )
                results.append({"mesh": mesh, "skinCluster": new_skin, "method": "cage_copy"})
            except Exception as e:
                return ToolResult(
                    ok=False,
                    error=f"拷贝权重失败 {mesh}: {e}",
                    data={"done": results},
                )
        return ToolResult(
            ok=True,
            data={"cage": cage_node, "bound": results},
            message=f"已从 SkinCage 绑定 {len(results)} 个网格",
        )

    # Fallback smooth bind
    infs = list(influences or [])
    if not infs:
        if c.objExists("Root_M"):
            infs = _collect_joints("Root_M")
        else:
            infs = c.ls(type="joint") or []
    if not infs:
        return ToolResult(ok=False, error="没有可用的影响骨骼")

    for mesh in targets:
        try:
            mh = c.listHistory(mesh) or []
            for s in c.ls(mh, type="skinCluster") or []:
                c.skinCluster(s, e=True, unbind=True)
            c.select(infs, replace=True)
            c.select(mesh, add=True)
            new_skin = c.skinCluster(
                toSelectedBones=True,
                bindMethod=0,
                normalizeWeights=1,
                maximumInfluences=int(max_influences),
                obeyMaxInfluences=True,
            )[0]
            results.append({"mesh": mesh, "skinCluster": new_skin, "method": "smooth_bind"})
        except Exception as e:
            return ToolResult(ok=False, error=f"绑定失败 {mesh}: {e}", data={"done": results})

    return ToolResult(
        ok=True,
        data={"cage": None, "bound": results, "influences": infs},
        message=f"已 smooth bind {len(results)} 个网格（无 SkinCage）",
    )
