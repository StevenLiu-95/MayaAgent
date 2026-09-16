"""Native auto-rig helpers (no AdvancedSkeleton required).

Creates a game-style biped joint chain from mesh bounding box, FK controllers,
and smooth-bind. Complements ADV wrappers when the plugin is not installed.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from maya_agent.tools.registry import ToolResult, obj_schema, tool
from maya_agent.tools._maya import cmds as _cmds, in_maya

# name, parent, (x_frac_of_half_width, y_frac_of_height, z_frac_of_half_depth)
# x/z: 0 = center; +1 ≈ right/front at half-extent
_BIPED_LAYOUT = (
    ("Root_M", None, (0.0, 0.52, 0.0)),
    ("Hip_M", "Root_M", (0.0, 0.52, 0.0)),
    ("Spine1_M", "Hip_M", (0.0, 0.62, 0.0)),
    ("Spine2_M", "Spine1_M", (0.0, 0.70, 0.0)),
    ("Chest_M", "Spine2_M", (0.0, 0.78, 0.05)),
    ("Neck_M", "Chest_M", (0.0, 0.86, 0.02)),
    ("Head_M", "Neck_M", (0.0, 0.96, 0.04)),
    ("Shoulder_L", "Chest_M", (0.55, 0.80, 0.0)),
    ("Elbow_L", "Shoulder_L", (0.95, 0.62, -0.04)),
    ("Wrist_L", "Elbow_L", (1.25, 0.50, 0.02)),
    ("Shoulder_R", "Chest_M", (-0.55, 0.80, 0.0)),
    ("Elbow_R", "Shoulder_R", (-0.95, 0.62, -0.04)),
    ("Wrist_R", "Elbow_R", (-1.25, 0.50, 0.02)),
    ("Hip_L", "Hip_M", (0.22, 0.50, 0.0)),
    ("Knee_L", "Hip_L", (0.24, 0.28, 0.06)),
    ("Ankle_L", "Knee_L", (0.24, 0.06, 0.0)),
    ("Toes_L", "Ankle_L", (0.24, 0.02, 0.18)),
    ("Hip_R", "Hip_M", (-0.22, 0.50, 0.0)),
    ("Knee_R", "Hip_R", (-0.24, 0.28, 0.06)),
    ("Ankle_R", "Knee_R", (-0.24, 0.06, 0.0)),
    ("Toes_R", "Ankle_R", (-0.24, 0.02, 0.18)),
)


def _require():
    if not in_maya():
        raise RuntimeError("未在 Maya 中运行")
    return _cmds()


def _mesh_transforms(names: Optional[List[str]]) -> List[str]:
    c = _cmds()
    if names:
        out = []
        for n in names:
            if not c.objExists(n):
                raise ValueError(f"对象不存在: {n}")
            out.append((c.ls(n, long=True) or [n])[0])
        return out
    sel = c.ls(selection=True, long=True) or []
    meshes = []
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


def _combined_bbox(nodes: Sequence[str]) -> Tuple[float, float, float, float, float, float]:
    c = _cmds()
    bb = c.exactWorldBoundingBox(list(nodes))
    return tuple(bb)  # type: ignore[return-value]


def _place_from_bbox(
    xmin: float, ymin: float, zmin: float, xmax: float, ymax: float, zmax: float
) -> Dict[str, Tuple[float, float, float]]:
    cx = (xmin + xmax) * 0.5
    cz = (zmin + zmax) * 0.5
    h = max(ymax - ymin, 0.001)
    hw = max((xmax - xmin) * 0.5, h * 0.12)
    hd = max((zmax - zmin) * 0.5, h * 0.08)
    out: Dict[str, Tuple[float, float, float]] = {}
    for name, _parent, (xf, yf, zf) in _BIPED_LAYOUT:
        out[name] = (cx + xf * hw, ymin + yf * h, cz + zf * hd)
    return out


def _create_joint(name: str, pos: Sequence[float], parent: Optional[str], radius: float) -> str:
    c = _cmds()
    if c.objExists(name):
        try:
            c.delete(name)
        except Exception:
            name = name + "_new"
    c.select(clear=True)
    j = c.joint(name=name, position=list(pos), radius=radius)
    if parent and c.objExists(parent):
        j = c.parent(j, parent)[0]
        c.xform(j, worldSpace=True, translation=list(pos))
    return j


def _orient_hierarchy(root: str) -> None:
    c = _cmds()
    try:
        c.joint(root, edit=True, orientJoint="xyz", secondaryAxisOrient="yup", children=True, zeroScaleOrient=True)
    except Exception:
        pass


def _ctrl_curve(name: str, size: float, shape: str = "circle") -> str:
    c = _cmds()
    if shape == "cube":
        s = size
        pts = [
            (-s, -s, -s), (s, -s, -s), (s, -s, s), (-s, -s, s), (-s, -s, -s),
            (-s, s, -s), (s, s, -s), (s, -s, -s), (s, s, -s), (s, s, s),
            (s, -s, s), (s, s, s), (-s, s, s), (-s, -s, s), (-s, s, s),
            (-s, s, -s),
        ]
        return c.curve(name=name, degree=1, point=pts)
    return c.circle(name=name, radius=size, normal=(0, 1, 0), constructionHistory=False)[0]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@tool(
    name="auto_create_biped_skeleton",
    description=(
        "根据角色网格包围盒快速创建简化双足骨骼（比例启发式）。"
        "需要 ADV 级拓扑精度时请改用 create_skeleton_biped / create_skeleton_biped_game / create_skeleton_ue5。"
    ),
    parameters=obj_schema(
        {
            "names": {"type": "array", "items": {"type": "string"}, "default": []},
            "group_name": {"type": "string", "default": "BindSkeleton"},
            "orient": {"type": "boolean", "default": True},
        }
    ),
    category="rigging",
    destructive=True,
)
def auto_create_biped_skeleton(
    names: Optional[List[str]] = None,
    group_name: str = "BindSkeleton",
    orient: bool = True,
) -> ToolResult:
    try:
        c = _require()
        meshes = _mesh_transforms(names)
    except (RuntimeError, ValueError) as e:
        return ToolResult(ok=False, error=str(e))

    bb = _combined_bbox(meshes)
    height = bb[4] - bb[1]
    radius = max(height / 80.0, 0.2)
    positions = _place_from_bbox(*bb)

    created: List[str] = []
    for name, parent, _frac in _BIPED_LAYOUT:
        j = _create_joint(name, positions[name], parent, radius)
        created.append(j)

    if orient and created:
        _orient_hierarchy(created[0])

    grp = group_name
    if grp:
        if c.objExists(grp):
            try:
                c.delete(grp)
            except Exception:
                grp = grp + "_1"
        grp = c.group(created[0], name=grp)

    return ToolResult(
        ok=True,
        data={
            "group": grp,
            "joints": created,
            "count": len(created),
            "height": round(height, 3),
            "bbox": [round(x, 3) for x in bb],
            "meshes": meshes,
        },
        message=f"已创建 {len(created)} 根双足骨骼（高 {height:.2f}）",
    )


@tool(
    name="auto_create_fk_controls",
    description=(
        "为骨骼链自动生成 FK 控制器（圆环/方框曲线 + parentConstraint）。"
        "joints 为空则用当前选择的 joint。控制器按骨骼命名加 ctrl_ 前缀。"
    ),
    parameters=obj_schema(
        {
            "joints": {"type": "array", "items": {"type": "string"}, "default": []},
            "shape": {
                "type": "string",
                "enum": ["circle", "cube"],
                "default": "circle",
            },
            "scale": {"type": "number", "default": 1.0, "description": "控制器尺寸倍率"},
            "group_name": {"type": "string", "default": "ControlRig"},
        }
    ),
    category="rigging",
    destructive=True,
)
def auto_create_fk_controls(
    joints: Optional[List[str]] = None,
    shape: str = "circle",
    scale: float = 1.0,
    group_name: str = "ControlRig",
) -> ToolResult:
    try:
        c = _require()
    except RuntimeError as e:
        return ToolResult(ok=False, error=str(e))

    jnts = list(joints or [])
    if not jnts:
        jnts = c.ls(selection=True, type="joint", long=True) or []
    if not jnts:
        return ToolResult(ok=False, error="未指定骨骼且无选择")

    # Stable order: roots first
    def depth(n: str) -> int:
        p = c.listRelatives(n, parent=True, fullPath=True) or []
        return 0 if not p else 1 + depth(p[0])

    ordered = sorted(jnts, key=lambda n: (depth(n), n))
    created: List[Dict[str, str]] = []
    ctrl_of: Dict[str, str] = {}
    base_size = height_guess(ordered, c)

    for j in ordered:
        short = j.split("|")[-1]
        pos = c.xform(j, query=True, worldSpace=True, translation=True)
        children = c.listRelatives(j, children=True, type="joint", fullPath=True) or []
        bone_len = base_size
        if children:
            cp = c.xform(children[0], query=True, worldSpace=True, translation=True)
            dist = (
                (pos[0] - cp[0]) ** 2
                + (pos[1] - cp[1]) ** 2
                + (pos[2] - cp[2]) ** 2
            ) ** 0.5
            bone_len = max(dist, base_size * 0.5)
        size = max(bone_len * 0.35 * float(scale), 0.5)
        ctrl_name = f"ctrl_{short}"
        if c.objExists(ctrl_name):
            c.delete(ctrl_name)
        ctrl = _ctrl_curve(ctrl_name, size, shape)
        c.xform(ctrl, worldSpace=True, translation=pos)
        # Match joint orientation
        try:
            rot = c.xform(j, query=True, worldSpace=True, rotation=True)
            c.xform(ctrl, worldSpace=True, rotation=rot)
        except Exception:
            pass
        offset = c.group(ctrl, name=f"{ctrl_name}_offset")
        parent_j = c.listRelatives(j, parent=True, type="joint", fullPath=True)
        if parent_j:
            pctrl = ctrl_of.get(parent_j[0]) or ctrl_of.get(parent_j[0].split("|")[-1])
            if pctrl and c.objExists(pctrl):
                c.parent(offset, pctrl)
        c.parentConstraint(ctrl, j, maintainOffset=True)
        ctrl_of[j] = ctrl
        ctrl_of[short] = ctrl
        created.append({"joint": short, "control": ctrl, "offset": offset})

    grp = ""
    roots = [
        x["offset"]
        for x in created
        if not (c.listRelatives(x["offset"], parent=True) or [])
    ]
    if group_name and roots:
        grp = c.group(roots, name=group_name)

    return ToolResult(
        ok=True,
        data={"group": grp or None, "controls": created, "count": len(created)},
        message=f"已创建 {len(created)} 个 FK 控制器",
    )


def height_guess(joints: List[str], c) -> float:
    ys = []
    for j in joints:
        try:
            ys.append(c.xform(j, query=True, worldSpace=True, translation=True)[1])
        except Exception:
            pass
    if len(ys) < 2:
        return 1.0
    return max((max(ys) - min(ys)) * 0.04, 0.4)


@tool(
    name="auto_bind_skin",
    description=(
        "将网格 Smooth Bind 到骨骼（默认当前选择的 mesh + joint，或传入列表）。"
        "若已有 SkinCage，优先使用 bind_from_skin_cage。"
        "纯 cmds，不依赖 AdvancedSkeleton。"
    ),
    parameters=obj_schema(
        {
            "meshes": {"type": "array", "items": {"type": "string"}, "default": []},
            "joints": {"type": "array", "items": {"type": "string"}, "default": []},
            "max_influences": {"type": "integer", "default": 4},
            "bind_method": {
                "type": "integer",
                "default": 0,
                "description": "0=closestDistance, 1=closestInHierarchy, 2=heatMap, 3=geodesic",
            },
        }
    ),
    category="rigging",
    destructive=True,
)
def auto_bind_skin(
    meshes: Optional[List[str]] = None,
    joints: Optional[List[str]] = None,
    max_influences: int = 4,
    bind_method: int = 0,
) -> ToolResult:
    try:
        c = _require()
    except RuntimeError as e:
        return ToolResult(ok=False, error=str(e))

    mesh_list = list(meshes or [])
    joint_list = list(joints or [])
    if not mesh_list or not joint_list:
        sel_j = c.ls(selection=True, type="joint", long=True) or []
        sel_t = c.ls(selection=True, type="transform", long=True) or []
        sel_m = [
            t
            for t in sel_t
            if c.listRelatives(t, shapes=True, type="mesh", noIntermediate=True)
        ]
        if not mesh_list:
            mesh_list = sel_m
        if not joint_list:
            joint_list = sel_j
    if not mesh_list:
        try:
            mesh_list = _mesh_transforms(None)
        except ValueError:
            pass
    if not joint_list:
        # Prefer newly created biped names
        for n, _p, _f in _BIPED_LAYOUT:
            if c.objExists(n):
                joint_list.append(n)
    if not mesh_list or not joint_list:
        return ToolResult(ok=False, error="需要网格和骨骼（参数或选择）")

    clusters = []
    for mesh in mesh_list:
        if not c.objExists(mesh):
            return ToolResult(ok=False, error=f"网格不存在: {mesh}")
        c.select(joint_list, replace=True)
        c.select(mesh, add=True)
        sc = c.skinCluster(
            toSelectedBones=True,
            bindMethod=int(bind_method),
            normalizeWeights=1,
            maximumInfluences=max(1, int(max_influences)),
            obeyMaxInfluences=True,
            dropoffRate=4.0,
            removeUnusedInfluence=False,
        )
        clusters.append(sc[0] if isinstance(sc, (list, tuple)) else str(sc))
    return ToolResult(
        ok=True,
        data={
            "skinClusters": clusters,
            "meshes": mesh_list,
            "joints": [j.split("|")[-1] for j in joint_list],
        },
        message=f"已蒙皮 {len(mesh_list)} 个网格 → {len(joint_list)} 根骨骼",
    )


@tool(
    name="auto_rig_biped",
    description=(
        "快捷一键：简化双足骨骼 + FK + Smooth Bind（包围盒启发式）。"
        "完整模板管线请用 auto_rig_character（biped/ue5/cat/horse + SkinCage + FK/IK）。"
    ),
    parameters=obj_schema(
        {
            "names": {"type": "array", "items": {"type": "string"}, "default": []},
            "make_controls": {"type": "boolean", "default": True},
            "bind": {"type": "boolean", "default": True},
            "max_influences": {"type": "integer", "default": 4},
        }
    ),
    category="rigging",
    destructive=True,
)
def auto_rig_biped(
    names: Optional[List[str]] = None,
    make_controls: bool = True,
    bind: bool = True,
    max_influences: int = 4,
) -> ToolResult:
    sk = auto_create_biped_skeleton(names=names or [], group_name="BindSkeleton", orient=True)
    if not sk.ok:
        return sk
    joints = (sk.data or {}).get("joints") or []
    meshes = (sk.data or {}).get("meshes") or []
    steps = [sk.message]
    ctrl_data: Any = None
    bind_data: Any = None
    if make_controls:
        cr = auto_create_fk_controls(joints=joints, shape="circle", scale=1.0)
        if cr.ok:
            steps.append(cr.message)
            ctrl_data = cr.data
        else:
            steps.append(f"控制器跳过: {cr.error}")
    if bind:
        bd = auto_bind_skin(meshes=meshes, joints=joints, max_influences=max_influences)
        if bd.ok:
            steps.append(bd.message)
            bind_data = bd.data
        else:
            steps.append(f"蒙皮跳过: {bd.error}")
    return ToolResult(
        ok=True,
        data={
            "skeleton": sk.data,
            "controls": ctrl_data,
            "skin": bind_data,
            "steps": steps,
        },
        message="；".join(steps),
    )
