"""FK / IK / Pole control rig builder (no AdvancedSkeleton)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from maya_agent.tools.registry import ToolResult, obj_schema, tool
from maya_agent.tools.skeleton_templates import template_payload
from maya_agent.tools.skeleton_templates.builder import build_skeleton
from maya_agent.tools._maya import cmds as _cmds, in_maya


def _require():
    if not in_maya():
        raise RuntimeError("未在 Maya 中运行")
    return _cmds()


def _short(n: str) -> str:
    return n.split("|")[-1]


def _unique(name: str) -> str:
    c = _cmds()
    if not c.objExists(name):
        return name
    i = 1
    while c.objExists(f"{name}{i}"):
        i += 1
    return f"{name}{i}"


def _ensure_set(name: str) -> str:
    c = _cmds()
    if c.objExists(name):
        return name
    return c.sets(name=name, empty=True)


def _add_to_set(set_name: str, nodes: Sequence[str]) -> None:
    c = _cmds()
    s = _ensure_set(set_name)
    for n in nodes:
        if c.objExists(n):
            try:
                c.sets(n, add=s)
            except Exception:
                pass


def _curve_ctrl(name: str, size: float, shape: str = "circle") -> str:
    c = _cmds()
    name = _unique(name)
    if shape == "cube":
        s = size
        pts = [
            (-s, -s, -s), (s, -s, -s), (s, -s, s), (-s, -s, s), (-s, -s, -s),
            (-s, s, -s), (s, s, -s), (s, -s, -s), (s, s, -s), (s, s, s),
            (s, -s, s), (s, s, s), (-s, s, s), (-s, -s, s), (-s, s, s),
            (-s, s, -s),
        ]
        return c.curve(name=name, degree=1, point=pts)
    if shape == "diamond":
        s = size
        pts = [(0, s, 0), (s, 0, 0), (0, -s, 0), (-s, 0, 0), (0, s, 0)]
        return c.curve(name=name, degree=1, point=pts)
    if shape == "sphere":
        # two circles
        a = c.circle(name=name, radius=size, normal=(0, 1, 0), ch=False)[0]
        b = c.circle(radius=size, normal=(1, 0, 0), ch=False)[0]
        c.parent(c.listRelatives(b, shapes=True)[0], a, shape=True, relative=True)
        c.delete(b)
        return a
    return c.circle(name=name, radius=size, normal=(0, 1, 0), constructionHistory=False)[0]


def _make_fk_control(joint: str, size: float) -> Dict[str, str]:
    c = _cmds()
    short = _short(joint)
    base = short  # e.g. Shoulder_R
    ctrl = _curve_ctrl(f"FK{base}", size, "circle")
    pos = c.xform(joint, q=True, ws=True, t=True)
    rot = c.xform(joint, q=True, ws=True, rotation=True)
    c.xform(ctrl, ws=True, t=pos, rotation=rot)
    extra = c.group(ctrl, name=_unique(f"FKExtra{base}"))
    offset = c.group(extra, name=_unique(f"FKOffset{base}"))
    c.parentConstraint(ctrl, joint, maintainOffset=True)
    return {"joint": short, "control": ctrl, "extra": extra, "offset": offset}


def _pole_position(a: str, b: str, c_j: str, distance: float) -> Tuple[float, float, float]:
    """Place pole vector from triangle ABC (shoulder-elbow-wrist)."""
    cmds = _cmds()
    pa = cmds.xform(a, q=True, ws=True, t=True)
    pb = cmds.xform(b, q=True, ws=True, t=True)
    pc = cmds.xform(c_j, q=True, ws=True, t=True)
    # mid AC
    mid = ((pa[0] + pc[0]) * 0.5, (pa[1] + pc[1]) * 0.5, (pa[2] + pc[2]) * 0.5)
    # vector mid -> B
    vx, vy, vz = pb[0] - mid[0], pb[1] - mid[1], pb[2] - mid[2]
    length = (vx * vx + vy * vy + vz * vz) ** 0.5
    if length < 1e-6:
        vx, vy, vz = 0.0, 0.0, 1.0
        length = 1.0
    scale = distance / length
    return (pb[0] + vx * scale, pb[1] + vy * scale, pb[2] + vz * scale)


def _create_ik_limb(
    start: str, mid: str, end: str, *, side_tag: str, limb: str
) -> Optional[Dict[str, str]]:
    c = _cmds()
    for n in (start, mid, end):
        if not c.objExists(n):
            return None
    ik_name = _unique(f"IK{limb}{side_tag}")
    handle = c.ikHandle(
        name=_unique(f"ikHandle{limb}{side_tag}"),
        startJoint=start,
        endEffector=end,
        solver="ikRPsolver",
    )
    handle_node = handle[0]
    # IK control at end
    size = max(
        (
            sum(
                (c.xform(start, q=True, ws=True, t=True)[i] - c.xform(end, q=True, ws=True, t=True)[i]) ** 2
                for i in range(3)
            )
            ** 0.5
        )
        * 0.15,
        0.5,
    )
    ik_ctrl = _curve_ctrl(ik_name, size, "cube")
    epos = c.xform(end, q=True, ws=True, t=True)
    c.xform(ik_ctrl, ws=True, t=epos)
    ik_extra = c.group(ik_ctrl, name=_unique(f"IKExtra{limb}{side_tag}"))
    ik_offset = c.group(ik_extra, name=_unique(f"IKOffset{limb}{side_tag}"))
    c.parentConstraint(ik_ctrl, handle_node, maintainOffset=True)
    # Pole
    pole_pos = _pole_position(start, mid, end, size * 4)
    pole = _curve_ctrl(f"Pole{limb}{side_tag}", size * 0.5, "diamond")
    c.xform(pole, ws=True, t=pole_pos)
    pole_extra = c.group(pole, name=_unique(f"PoleExtra{limb}{side_tag}"))
    pole_offset = c.group(pole_extra, name=_unique(f"PoleOffset{limb}{side_tag}"))
    c.poleVectorConstraint(pole, handle_node)
    # Hide handle
    try:
        c.setAttr(f"{handle_node}.v", 0)
    except Exception:
        pass
    return {
        "ik_control": ik_ctrl,
        "ik_offset": ik_offset,
        "pole": pole,
        "pole_offset": pole_offset,
        "handle": handle_node,
        "start": start,
        "mid": mid,
        "end": end,
    }


def _find_limb_triples() -> List[Tuple[str, str, str, str, str]]:
    """Return list of (start, mid, end, side_tag, limb_name)."""
    c = _cmds()
    triples = []
    for side, tag in (("_R", "_R"), ("_L", "_L")):
        for start, mid, end, limb in (
            (f"Shoulder{side}", f"Elbow{side}", f"Wrist{side}", "Arm"),
            (f"UpperArm{side}", f"LowerArm{side}", f"Hand{side}", "Arm"),
            (f"Hip{side}", f"Knee{side}", f"Ankle{side}", "Leg"),
            (f"Thigh{side}", f"Calf{side}", f"Foot{side}", "Leg"),
        ):
            if c.objExists(start) and c.objExists(mid) and c.objExists(end):
                triples.append((start, mid, end, tag, limb))
    return triples


@tool(
    name="build_fk_ik_controls",
    description=(
        "为变形骨骼自动生成 FK 控制器（Offset/Extra/FK 层级）以及手臂/腿的 RP-IK + Pole。"
        "纯 cmds，不依赖 AdvancedSkeleton。root_joint 默认 Root_M。"
    ),
    parameters=obj_schema(
        {
            "root_joint": {"type": "string", "default": "Root_M"},
            "include_ik": {"type": "boolean", "default": True},
            "include_fk": {"type": "boolean", "default": True},
            "scale": {"type": "number", "default": 1.0},
            "group_name": {"type": "string", "default": "MotionSystem"},
        }
    ),
    category="rigging",
    destructive=True,
)
def build_fk_ik_controls(
    root_joint: str = "Root_M",
    include_ik: bool = True,
    include_fk: bool = True,
    scale: float = 1.0,
    group_name: str = "MotionSystem",
) -> ToolResult:
    try:
        c = _require()
    except RuntimeError as e:
        return ToolResult(ok=False, error=str(e))

    root = root_joint if c.objExists(root_joint) else ""
    if not root:
        cands = c.ls("Root*", type="joint") or []
        if not cands:
            return ToolResult(ok=False, error="找不到 Root_M 或 root_joint")
        root = cands[0]

    joints = [root] + (
        c.listRelatives(root, allDescendents=True, type="joint", fullPath=False) or []
    )
    # size from height
    ys = []
    for j in joints:
        try:
            ys.append(c.xform(j, q=True, ws=True, t=True)[1])
        except Exception:
            pass
    height = (max(ys) - min(ys)) if len(ys) >= 2 else 10.0
    base_size = max(height * 0.04 * float(scale), 0.3)

    motion = _unique(group_name) if group_name else ""
    if motion and not c.objExists(motion):
        motion = c.group(empty=True, name=motion)

    # Main / Root controls
    main = _curve_ctrl("Main", base_size * 3, "circle")
    rpos = c.xform(root, q=True, ws=True, t=True)
    c.xform(main, ws=True, t=(rpos[0], 0, rpos[2]))
    main_off = c.group(main, name=_unique("Main_offset"))
    root_ctrl = _curve_ctrl("Root_ctrl", base_size * 1.5, "cube")
    c.xform(root_ctrl, ws=True, t=rpos)
    root_off = c.group(root_ctrl, name=_unique("Root_ctrl_offset"))
    c.parent(root_off, main)
    try:
        c.parentConstraint(root_ctrl, root, maintainOffset=True)
    except Exception:
        pass

    fk_list: List[Dict[str, str]] = []
    if include_fk:
        skip = {root, _short(root)}
        # When IK is on, skip limb joints to avoid parentConstraint vs ikHandle fight
        ik_joint_skip = set()
        if include_ik:
            for start, mid, end, _tag, _limb in _find_limb_triples():
                ik_joint_skip.update({_short(start), _short(mid), _short(end)})
        # Skip end helpers & tips for cleaner FK
        for j in joints:
            sn = _short(j)
            if sn in skip or sn in ik_joint_skip:
                continue
            if any(x in sn for x in ("End", "Heel", "Eye", "Cup")):
                continue
            kids = c.listRelatives(j, children=True, type="joint") or []
            bone_len = base_size * 2
            if kids:
                bone_len = max(
                    sum(
                        (c.xform(j, q=True, ws=True, t=True)[i] - c.xform(kids[0], q=True, ws=True, t=True)[i]) ** 2
                        for i in range(3)
                    )
                    ** 0.5,
                    base_size,
                )
            size = max(bone_len * 0.3 * float(scale), 0.2)
            try:
                info = _make_fk_control(j, size)
                fk_list.append(info)
            except Exception:
                continue
        # Parent FK offsets to follow hierarchy
        ctrl_of = {f["joint"]: f["control"] for f in fk_list}
        for f in fk_list:
            j = f["joint"]
            par = c.listRelatives(j, parent=True, type="joint") or []
            if not par:
                try:
                    c.parent(f["offset"], root_ctrl)
                except Exception:
                    pass
                continue
            pj = _short(par[0])
            if pj in ctrl_of:
                try:
                    c.parent(f["offset"], ctrl_of[pj])
                except Exception:
                    pass
            elif pj == _short(root):
                try:
                    c.parent(f["offset"], root_ctrl)
                except Exception:
                    pass

    ik_list: List[Dict[str, str]] = []
    if include_ik:
        for start, mid, end, tag, limb in _find_limb_triples():
            info = _create_ik_limb(start, mid, end, side_tag=tag, limb=limb)
            if info:
                ik_list.append(info)
                try:
                    c.parent(info["ik_offset"], main)
                    c.parent(info["pole_offset"], main)
                except Exception:
                    pass

    if motion:
        try:
            c.parent(main_off, motion)
        except Exception:
            pass

    controls = [main, root_ctrl] + [f["control"] for f in fk_list] + [i["ik_control"] for i in ik_list] + [i["pole"] for i in ik_list]
    _add_to_set("ControlSet", controls)
    _add_to_set("DeformSet", joints)

    return ToolResult(
        ok=True,
        data={
            "group": motion or None,
            "main": main,
            "root_control": root_ctrl,
            "fk": fk_list,
            "ik": ik_list,
            "control_count": len(controls),
        },
        message=f"已生成控制器：FK {len(fk_list)}，IK肢 {len(ik_list)}，总控 Main/Root",
    )


@tool(
    name="auto_rig_character",
    description=(
        "一键原生绑定管线（不依赖 AdvancedSkeleton）："
        "创建骨架模板 → 可选 SkinCage → 绑定网格 → 生成 FK/IK 控制器。"
        "skeleton_type 见 list_skeleton_templates（如 biped / ue5 / cat / dragon …）。"
    ),
    parameters=obj_schema(
        {
            "skeleton_type": {
                "type": "string",
                "default": "biped",
                "description": (
                    "模板 id：biped / biped_game / biped_bendy / ue5 / ue4 / previs / "
                    "cat / horse / gorilla / bird / fish / bug / dinosaur / dragon / vehicle"
                ),
            },
            "meshes": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": "角色网格；空则用当前选择",
            },
            "fit_to_meshes": {"type": "boolean", "default": True},
            "with_cage": {"type": "boolean", "default": True},
            "with_bind": {"type": "boolean", "default": True},
            "with_controls": {"type": "boolean", "default": True},
            "include_ik": {"type": "boolean", "default": True},
        }
    ),
    category="rigging",
    destructive=True,
)
def auto_rig_character(
    skeleton_type: str = "biped",
    meshes: Optional[List[str]] = None,
    fit_to_meshes: bool = True,
    with_cage: bool = True,
    with_bind: bool = True,
    with_controls: bool = True,
    include_ik: bool = True,
) -> ToolResult:
    try:
        c = _require()
        joints, needs_mirror, label = template_payload(skeleton_type)
    except RuntimeError as e:
        return ToolResult(ok=False, error=str(e))
    except (KeyError, ValueError) as e:
        return ToolResult(ok=False, error=str(e))

    mesh_list = list(meshes or [])
    fit = mesh_list if fit_to_meshes else None
    if fit_to_meshes and not mesh_list:
        fit = []  # selection

    try:
        sk = build_skeleton(
            joints,
            root_group="DeformationSystem",
            needs_mirror=needs_mirror,
            orient=False,
            fit_meshes=fit,
        )
    except Exception as e:
        return ToolResult(ok=False, error=f"创建骨架失败: {e}")

    out: Dict[str, Any] = {"skeleton": sk, "template": skeleton_type, "label": label}
    root = sk.get("root") or "Root_M"

    cage_data = None
    if with_cage:
        from maya_agent.tools.skin_cage import create_skin_cage

        cage_res = create_skin_cage(root_joint=root, radius_scale=1.0)
        out["skin_cage"] = {"ok": cage_res.ok, "data": cage_res.data, "error": cage_res.error}
        if cage_res.ok:
            cage_data = cage_res.data

    if with_bind:
        from maya_agent.tools.skin_cage import bind_from_skin_cage

        if not mesh_list:
            # selection or from fit
            mesh_list = (sk.get("meshes") or [])[:]
        cage_name = ""
        if cage_data:
            cage_name = cage_data.get("cage") or ""
        bind_res = bind_from_skin_cage(
            meshes=mesh_list,
            cage=cage_name,
            influences=sk.get("joints") or [],
        )
        out["bind"] = {"ok": bind_res.ok, "data": bind_res.data, "error": bind_res.error}
        if not bind_res.ok:
            return ToolResult(ok=False, error=bind_res.error or "绑定失败", data=out)

    if with_controls:
        ctrl_res = build_fk_ik_controls(
            root_joint=root, include_ik=include_ik, include_fk=True
        )
        out["controls"] = {"ok": ctrl_res.ok, "data": ctrl_res.data, "error": ctrl_res.error}
        if not ctrl_res.ok:
            return ToolResult(ok=False, error=ctrl_res.error or "控制器失败", data=out)

    return ToolResult(
        ok=True,
        data=out,
        message=(
            f"一键绑定完成「{label}」：骨骼 {sk.get('count')}，"
            f"cage={'是' if cage_data else '否'}，"
            f"bind={'是' if with_bind else '否'}，controls={'是' if with_controls else '否'}"
        ),
    )
