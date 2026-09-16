"""Shared skeleton builder from JointDef lists (no AdvancedSkeleton)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from maya_agent.tools._maya import cmds as _cmds, in_maya

JointDef = Dict[str, Any]


def require_maya():
    if not in_maya():
        raise RuntimeError("未在 Maya 中运行")
    return _cmds()


def mesh_transforms(names: Optional[List[str]]) -> List[str]:
    c = _cmds()
    if names:
        out = []
        for n in names:
            if not c.objExists(n):
                raise ValueError(f"对象不存在: {n}")
            out.append((c.ls(n, long=True) or [n])[0])
        return out
    sel = c.ls(selection=True, long=True) or []
    meshes: List[str] = []
    for t in sel:
        if c.listRelatives(t, shapes=True, type="mesh", noIntermediate=True):
            meshes.append(t)
        elif c.nodeType(t) == "mesh":
            p = c.listRelatives(t, parent=True, fullPath=True) or []
            if p:
                meshes.append(p[0])
    if not meshes:
        raise ValueError("未指定网格且选择中没有 mesh")
    return meshes


def combined_bbox(nodes: Sequence[str]) -> Tuple[float, float, float, float, float, float]:
    c = _cmds()
    return tuple(c.exactWorldBoundingBox(list(nodes)))  # type: ignore[return-value]


def template_height(joints: Sequence[JointDef]) -> float:
    ys = [float(j["translate"][1]) for j in joints]
    # Prefer world-ish span: accumulate only root-chain Y is incomplete;
    # use max local Y walk as fallback — builder also uses post-create bbox.
    return max(ys) - min(ys) if ys else 1.0


def _unique(name: str) -> str:
    c = _cmds()
    if not c.objExists(name):
        return name
    i = 1
    while c.objExists(f"{name}{i}"):
        i += 1
    return f"{name}{i}"


def _resolve_name_prefix(joints: Sequence[JointDef], name_prefix: str = "") -> str:
    """Return a prefix so joint short names do not collide with existing scene nodes.

    Never deletes existing joints. If ``name_prefix`` is given, use it; otherwise
    when any template name already exists, auto-pick ``skelN_``.
    """
    c = _cmds()
    prefix = name_prefix or ""
    if prefix:
        if any(c.objExists(f"{prefix}{j['name']}") for j in joints):
            base = prefix.rstrip("_") or "skel"
            i = 1
            while any(c.objExists(f"{base}{i}_{j['name']}") for j in joints):
                i += 1
            return f"{base}{i}_"
        return prefix
    if any(c.objExists(j["name"]) for j in joints):
        i = 1
        while any(c.objExists(f"skel{i}_{j['name']}") for j in joints):
            i += 1
        return f"skel{i}_"
    return ""


def _create_joint(
    name: str,
    local_t: Sequence[float],
    parent: Optional[str],
    radius: float,
    orient: Optional[Sequence[float]] = None,
) -> str:
    """Create a joint. Never deletes an existing node — caller must pass a free name."""
    c = _cmds()
    if c.objExists(name):
        raise RuntimeError(f"关节名已存在，无法创建: {name}")
    c.select(clear=True)
    # Create at origin then parent + set local translate/orient (matches .ma)
    j = c.joint(name=name, position=(0, 0, 0), radius=radius)
    if parent and c.objExists(parent):
        j = c.parent(j, parent)[0]
    if orient is not None:
        try:
            c.setAttr(
                f"{j}.jointOrient",
                float(orient[0]),
                float(orient[1]),
                float(orient[2]),
            )
        except Exception:
            pass
    c.setAttr(f"{j}.translate", float(local_t[0]), float(local_t[1]), float(local_t[2]))
    return j


def _orient_hierarchy(root: str) -> None:
    c = _cmds()
    try:
        c.joint(
            root,
            edit=True,
            orientJoint="xyz",
            secondaryAxisOrient="yup",
            children=True,
            zeroScaleOrient=True,
        )
    except Exception:
        pass


def _mirror_right_branches(created: List[str]) -> List[str]:
    """Mirror every *_R joint that is a direct child of a mid/*_M (or world) joint."""
    c = _cmds()
    mirrored: List[str] = []
    # Find top-most _R joints (parent is not _R)
    roots_r = []
    for j in created:
        short = j.split("|")[-1]
        if not short.endswith("_R"):
            continue
        par = c.listRelatives(j, parent=True, type="joint") or []
        if not par or not par[0].endswith("_R"):
            roots_r.append(j)
    for rj in roots_r:
        short = rj.split("|")[-1]
        left_name = short[:-2] + "_L"
        if c.objExists(left_name):
            continue
        try:
            result = c.mirrorJoint(
                rj,
                mirrorYZ=True,
                mirrorBehavior=True,
                searchReplace=("_R", "_L"),
            )
            if result:
                mirrored.extend(result if isinstance(result, list) else [result])
        except Exception:
            # Fallback: duplicate + flip world X
            try:
                dup = c.duplicate(rj, renameChildren=True)[0]
                # rename hierarchy
                for node in [dup] + (c.listRelatives(dup, allDescendents=True, type="joint", fullPath=True) or []):
                    sn = node.split("|")[-1]
                    if "_R" in sn:
                        nn = sn.replace("_R", "_L")
                        try:
                            c.rename(node, nn)
                        except Exception:
                            pass
                # flip translates on the branch in world
                for node in [dup] + (c.listRelatives(dup, allDescendents=True, type="joint", fullPath=True) or []):
                    pos = c.xform(node, q=True, ws=True, t=True)
                    c.xform(node, ws=True, t=(-pos[0], pos[1], pos[2]))
                mirrored.append(dup)
            except Exception:
                pass
    return mirrored


def _fit_to_bbox(
    root: str,
    bbox: Tuple[float, float, float, float, float, float],
    template_span_y: float,
) -> float:
    c = _cmds()
    xmin, ymin, zmin, xmax, ymax, zmax = bbox
    target_h = max(ymax - ymin, 0.001)
    # Current skeleton height
    joints = c.listRelatives(root, allDescendents=True, type="joint", fullPath=True) or []
    joints = [root] + joints if c.nodeType(root) == "joint" else joints
    if not joints:
        return 1.0
    ys = [c.xform(j, q=True, ws=True, t=True)[1] for j in joints]
    cur_h = max(ys) - min(ys)
    if cur_h < 1e-6:
        cur_h = max(template_span_y, 1.0)
    scale = target_h / cur_h
    cx = (xmin + xmax) * 0.5
    cz = (zmin + zmax) * 0.5
    # Scale about current root, then move root Y to ymin + relative
    c.xform(root, ws=True, s=(scale, scale, scale))
    # Re-read root and shift so lowest joint sits on ymin and centered XZ
    joints = c.listRelatives(root, allDescendents=True, type="joint", fullPath=True) or []
    allj = ([root] if c.nodeType(root) == "joint" else []) + joints
    positions = [c.xform(j, q=True, ws=True, t=True) for j in allj]
    min_y = min(p[1] for p in positions)
    # Also center XZ of root
    rpos = c.xform(root, q=True, ws=True, t=True)
    dx = cx - rpos[0]
    dy = ymin - min_y
    dz = cz - rpos[2]
    c.xform(root, ws=True, t=(rpos[0] + dx, rpos[1] + dy, rpos[2] + dz))
    return scale


def build_skeleton(
    joints: Sequence[JointDef],
    *,
    root_group: str = "DeformationSystem",
    needs_mirror: bool = True,
    orient: bool = True,
    fit_meshes: Optional[List[str]] = None,
    scale: float = 1.0,
    name_prefix: str = "",
) -> Dict[str, Any]:
    """
    Create a joint hierarchy from template defs.
    Returns dict with group, root, joints, scale, bbox, name_prefix.
    """
    c = require_maya()
    if not joints:
        raise ValueError("模板关节列表为空")

    prefix = _resolve_name_prefix(joints, name_prefix)

    # Topological order: parents before children
    by_name = {j["name"]: j for j in joints}
    ordered: List[JointDef] = []
    seen = set()

    def visit(n: str):
        if n in seen or n not in by_name:
            return
        p = by_name[n].get("parent")
        if p:
            visit(p)
        seen.add(n)
        ordered.append(by_name[n])

    for j in joints:
        visit(j["name"])

    created: List[str] = []
    name_to_node: Dict[str, str] = {}  # logical template name -> scene node
    for jdef in ordered:
        parent = jdef.get("parent")
        parent_node = name_to_node.get(parent) if parent else None
        scene_name = f"{prefix}{jdef['name']}"
        node = _create_joint(
            scene_name,
            jdef.get("translate") or (0, 0, 0),
            parent_node,
            float(jdef.get("radius") or 0.5),
            orient=jdef.get("orient"),
        )
        # Tag ik_role / fat for later tools
        role = jdef.get("ik_role") or ""
        if role:
            if not c.attributeQuery("ikRole", node=node, exists=True):
                c.addAttr(node, ln="ikRole", dt="string")
            c.setAttr(f"{node}.ikRole", role, type="string")
        fat = jdef.get("fat")
        if fat is not None:
            if not c.attributeQuery("fat", node=node, exists=True):
                c.addAttr(node, ln="fat", at="double", min=0, dv=1.0)
            try:
                c.setAttr(f"{node}.fat", float(fat))
            except Exception:
                pass
        name_to_node[jdef["name"]] = node
        created.append(node)

    if needs_mirror:
        _mirror_right_branches(created)
        # Refresh created list from hierarchy under roots we made
        roots = [
            n
            for n in list(name_to_node.values())
            if not (c.listRelatives(n, parent=True, type="joint") or [])
        ]
        created = []
        seen = set()
        for r in roots:
            stack = [r]
            while stack:
                cur = stack.pop()
                sn = cur.split("|")[-1]
                if sn not in seen and c.objExists(sn):
                    seen.add(sn)
                    created.append(sn)
                kids = c.listRelatives(cur, children=True, type="joint", fullPath=True) or []
                stack.extend(kids)
        # Propagate ikRole / fat from *_R to mirrored *_L
        for sn in list(created):
            if not sn.endswith("_L"):
                continue
            src = sn[:-2] + "_R"
            if not c.objExists(src):
                continue
            if c.attributeQuery("ikRole", node=src, exists=True):
                role = c.getAttr(f"{src}.ikRole") or ""
                if role:
                    if not c.attributeQuery("ikRole", node=sn, exists=True):
                        c.addAttr(sn, ln="ikRole", dt="string")
                    try:
                        c.setAttr(f"{sn}.ikRole", role, type="string")
                    except Exception:
                        pass
            if c.attributeQuery("fat", node=src, exists=True):
                try:
                    fat = float(c.getAttr(f"{src}.fat"))
                    if not c.attributeQuery("fat", node=sn, exists=True):
                        c.addAttr(sn, ln="fat", at="double", min=0, dv=1.0)
                    c.setAttr(f"{sn}.fat", fat)
                except Exception:
                    pass

    roots = [
        n
        for n in created
        if not (c.listRelatives(n, parent=True, type="joint") or [])
    ]
    root = roots[0] if roots else created[0]

    applied_scale = float(scale) if scale and scale != 1.0 else 1.0
    if applied_scale != 1.0:
        c.xform(root, ws=True, s=(applied_scale, applied_scale, applied_scale))

    fit_scale = 1.0
    bbox = None
    meshes: List[str] = []
    if fit_meshes is not None:
        meshes = mesh_transforms(fit_meshes if fit_meshes else None)
        bbox = combined_bbox(meshes)
        span = template_height(joints)
        fit_scale = _fit_to_bbox(root, bbox, span)

    if orient:
        _orient_hierarchy(root)

    grp_name = _unique(root_group) if root_group else ""
    if grp_name:
        # Parent all top roots under group
        top = [
            n
            for n in created
            if not (c.listRelatives(n, parent=True, type="joint") or [])
        ]
        if not c.objExists(grp_name):
            grp_name = c.group(empty=True, name=grp_name)
        for t in top:
            try:
                c.parent(t, grp_name)
            except Exception:
                pass
    else:
        grp_name = ""

    return {
        "group": grp_name or None,
        "root": root,
        "joints": created,
        "count": len(created),
        "scale": applied_scale * fit_scale,
        "bbox": [round(x, 3) for x in bbox] if bbox else None,
        "meshes": meshes,
        "name_prefix": prefix or None,
    }
