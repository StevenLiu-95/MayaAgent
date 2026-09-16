"""Optional AdvancedSkeleton (ADV) MEL bridge.

Prefer native tools instead:
  create_skeleton_* / create_skin_cage / bind_from_skin_cage /
  build_fk_ik_controls / auto_rig_character

Only use adv_* when the user explicitly has ADV installed and asks for it.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from maya_agent.tools.registry import ToolResult, obj_schema, tool
from maya_agent.tools._maya import cmds as _cmds, in_maya
from maya_agent.utils.config import get_config

_ADV_FIT_REMOVE = (
    "FitSkeleton",
    "FitSkeletonVisualizers",
    "cylinders",
    "boxes",
    "locators",
    "directions",
    "asRedSG",
    "asRed2SG",
    "asGreenSG",
    "asGreen2SG",
    "asBlueSG",
    "asBlue2SG",
    "asBlackSG",
    "asWhiteSG",
    "asBonesSG",
    "asRed",
    "asRed2",
    "asGreen",
    "asGreen2",
    "asBlue",
    "asBlue2",
    "asBlack",
    "asWhite",
    "asBones",
)

_TEMPLATES = (
    "biped",
    "bipedGame",
    "bipedBendy",
    "UE4",
    "UE5",
    "previs",
    "cat",
    "horse",
    "gorilla",
    "bird",
    "fish",
    "bug",
    "dinosaur",
    "dragon",
    "vehicle",
)


def _mel(cmd: str) -> Any:
    from maya_agent.utils.maya_compat import mel

    return mel().eval(cmd)


def _find_adv_root() -> str:
    cfg = str(get_config().get("maya.advanced_skeleton_path", "") or "").strip()
    env = (
        os.environ.get("ADVANCED_SKELETON_PATH")
        or os.environ.get("MAYAAGENT_ADV_PATH")
        or ""
    ).strip()
    here = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    candidates = [
        cfg,
        env,
        r"D:\桌面\AdvancedSkeleton",
        os.path.join(os.path.dirname(here), "AdvancedSkeleton"),
        os.path.join(here, "AdvancedSkeleton"),
    ]
    if in_maya():
        try:
            for p in _cmds().internalVar(userScriptDir=True), "":
                if p:
                    candidates.append(os.path.join(p, "AdvancedSkeleton"))
        except Exception:
            pass
    for raw in candidates:
        if not raw:
            continue
        root = os.path.normpath(os.path.expanduser(raw))
        if os.path.isfile(os.path.join(root, "AdvancedSkeleton.mel")):
            return root
    return ""


def _adv_mel_path(root: str) -> str:
    return os.path.join(root, "AdvancedSkeleton.mel").replace("\\", "/")


def _ensure_sourced(root: str = "") -> str:
    root = root or _find_adv_root()
    if not root:
        raise RuntimeError(
            "未找到 AdvancedSkeleton。请安装 ADV，或在配置 maya.advanced_skeleton_path "
            "/ 环境变量 ADVANCED_SKELETON_PATH 中指定目录（内含 AdvancedSkeleton.mel）。"
        )
    # whatIs returns sourced path once asScriptLocatorProc exists
    try:
        info = _mel("whatIs asScriptLocatorProc")
        if info and "unknown" not in str(info).lower():
            return root
    except Exception:
        pass
    _mel(f'source "{_adv_mel_path(root)}";')
    return root


def _ensure_ui() -> None:
    c = _cmds()
    if c.optionMenu("asFitFiles", exists=True):
        return
    unit = c.currentUnit(query=True, linear=True)
    if unit != "cm" and unit != "centimeter":
        c.currentUnit(linear="cm")
    _mel("AdvancedSkeleton;")
    if not c.optionMenu("asFitFiles", exists=True):
        raise RuntimeError("AdvancedSkeleton 面板未能打开（缺少 asFitFiles）")


def _set_text_field(name: str, value: str) -> None:
    c = _cmds()
    if c.textField(name, exists=True):
        c.textField(name, edit=True, text=value or "")


def _set_check(name: str, value: bool) -> None:
    c = _cmds()
    if c.checkBox(name, exists=True):
        c.checkBox(name, edit=True, value=bool(value))


def _template_file(root: str, template: str) -> str:
    name = (template or "biped").strip()
    if not name.lower().endswith(".ma"):
        name = name + ".ma"
    path = os.path.join(root, "AdvancedSkeletonFiles", "fitSkeletons", name)
    return os.path.normpath(path)


def _meshes_arg(names: Optional[List[str]]) -> List[str]:
    c = _cmds()
    if names:
        out = []
        for n in names:
            if not c.objExists(n):
                raise ValueError(f"网格不存在: {n}")
            out.append((c.ls(n, long=True) or [n])[0].split("|")[-1])
        return out
    sel = c.ls(selection=True, type="transform") or []
    meshes = []
    for t in sel:
        shapes = c.listRelatives(t, shapes=True, type="mesh", noIntermediate=True) or []
        if shapes:
            meshes.append(t.split("|")[-1])
    if not meshes:
        raise ValueError("未指定网格且当前选择中没有 mesh")
    return meshes


def _set_prep(meshes: List[str], *, game_engine: bool = True) -> None:
    txt = " ".join(meshes)
    _set_text_field("asBodySkinTextField", txt)
    _set_check("asBodyGameEngineCheckBox", game_engine)
    try:
        _mel("asSavePrepInput;")
    except Exception:
        c = _cmds()
        if c.objExists("FitSkeleton"):
            if not c.attributeQuery("objectsSkin", node="FitSkeleton", exists=True):
                _mel("asEnsureFitSkeletonAttributes;")
            c.setAttr("FitSkeleton.objectsSkin", txt, type="string")
            if c.attributeQuery("gameEngine", node="FitSkeleton", exists=True):
                c.setAttr("FitSkeleton.gameEngine", game_engine)


def _unique_short(name: str) -> str:
    return name.split("|")[-1]


def _scene_status() -> Dict[str, Any]:
    c = _cmds()
    def exists(n: str) -> bool:
        return bool(c.objExists(n))

    joints = []
    if exists("FitSkeleton"):
        joints = c.listRelatives("FitSkeleton", allDescendents=True, type="joint") or []
    deform = []
    if exists("DeformSet"):
        try:
            deform = c.sets("DeformSet", query=True) or []
        except Exception:
            pass
    ctrls = []
    if exists("ControlSet"):
        try:
            ctrls = c.sets("ControlSet", query=True) or []
        except Exception:
            pass
    return {
        "adv_ui": bool(c.optionMenu("asFitFiles", exists=True)),
        "FitSkeleton": exists("FitSkeleton"),
        "fit_joints": len(joints),
        "Group": exists("Group"),
        "Main": exists("Main"),
        "DeformSet": len(deform),
        "ControlSet": len(ctrls),
        "skinCage": exists("skinCage"),
        "template": (
            c.getAttr("FitSkeleton.fitSkeletonTemplate")
            if exists("FitSkeleton")
            and c.attributeQuery("fitSkeletonTemplate", node="FitSkeleton", exists=True)
            else ""
        ),
        "objectsSkin": (
            c.getAttr("FitSkeleton.objectsSkin")
            if exists("FitSkeleton")
            and c.attributeQuery("objectsSkin", node="FitSkeleton", exists=True)
            else ""
        ),
    }


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@tool(
    name="adv_rig_status",
    description=(
        "【可选·需安装 ADV】检查 AdvancedSkeleton 是否可用及场景绑定状态。"
        "日常请优先 list_skeleton_templates / create_skeleton_* / auto_rig_character。"
        "做 ADV 自动绑定前先调用。"
    ),
    parameters=obj_schema({}),
    category="rigging",
)
def adv_rig_status() -> ToolResult:
    if not in_maya():
        return ToolResult(ok=False, error="未在 Maya 中运行")
    root = _find_adv_root()
    sourced = False
    if root:
        try:
            info = _mel("whatIs asScriptLocatorProc")
            sourced = bool(info) and "unknown" not in str(info).lower()
        except Exception:
            sourced = False
    data = {
        "adv_root": root or None,
        "sourced": sourced,
        "templates": list(_TEMPLATES),
        "scene": _scene_status() if in_maya() else {},
    }
    if not root:
        return ToolResult(
            ok=False,
            error="未找到 AdvancedSkeleton 安装目录",
            data=data,
        )
    return ToolResult(ok=True, data=data, message=f"ADV 路径: {root}")


@tool(
    name="adv_list_fit_templates",
    description="列出 AdvancedSkeleton 可用的 FitSkeleton 模板（biped / UE5 / cat 等）。",
    parameters=obj_schema({}),
    category="rigging",
)
def adv_list_fit_templates() -> ToolResult:
    root = _find_adv_root()
    if not root:
        return ToolResult(ok=False, error="未找到 AdvancedSkeleton", data={"templates": list(_TEMPLATES)})
    folder = os.path.join(root, "AdvancedSkeletonFiles", "fitSkeletons")
    files = []
    if os.path.isdir(folder):
        files = sorted(f[:-3] for f in os.listdir(folder) if f.lower().endswith(".ma"))
    return ToolResult(
        ok=True,
        data={"directory": folder, "templates": files or list(_TEMPLATES)},
        message=f"{len(files or _TEMPLATES)} 个模板",
    )


@tool(
    name="adv_import_fit_skeleton",
    description=(
        "导入 AdvancedSkeleton FitSkeleton 引导骨架（不是最终绑定关节）。"
        "模板如 biped / bipedGame / UE5。已有 FitSkeleton 时 replace=true 会替换。"
        "下一步通常 adv_auto_place_fit 或手动调关节后 adv_build_rig。"
    ),
    parameters=obj_schema(
        {
            "template": {
                "type": "string",
                "default": "biped",
                "description": "fitSkeletons 模板名，如 biped、bipedGame、UE5",
            },
            "replace": {"type": "boolean", "default": True},
            "open_ui": {
                "type": "boolean",
                "default": True,
                "description": "必要时打开 ADV 面板（AutoPlace/Build 需要）",
            },
        }
    ),
    category="rigging",
    destructive=True,
)
def adv_import_fit_skeleton(
    template: str = "biped",
    replace: bool = True,
    open_ui: bool = True,
) -> ToolResult:
    if not in_maya():
        return ToolResult(ok=False, error="未在 Maya 中运行")
    c = _cmds()
    try:
        root = _ensure_sourced()
        if open_ui:
            _ensure_ui()
    except RuntimeError as e:
        return ToolResult(ok=False, error=str(e))

    ma = _template_file(root, template)
    if not os.path.isfile(ma):
        return ToolResult(ok=False, error=f"模板不存在: {ma}")

    if replace:
        for n in _ADV_FIT_REMOVE:
            if c.objExists(n):
                try:
                    c.delete(n)
                except Exception:
                    pass

    file_path = ma.replace("\\", "/")
    try:
        c.file(file_path, i=True, renameAll=True, renamingPrefix="AdvancedSkeleton", options="v=0")
    except Exception as e:
        return ToolResult(ok=False, error=f"导入失败: {e}")

    if not c.objExists("FitSkeleton"):
        return ToolResult(ok=False, error="导入后未找到 FitSkeleton 节点")

    try:
        _mel("asEnsureFitSkeletonAttributes;")
    except Exception:
        pass
    base = os.path.splitext(os.path.basename(ma))[0]
    if c.attributeQuery("fitSkeletonTemplate", node="FitSkeleton", exists=True):
        c.setAttr("FitSkeleton.fitSkeletonTemplate", base, type="string")
    if c.optionMenu("asFitFiles", exists=True):
        fname = os.path.basename(ma)
        try:
            c.optionMenu("asFitFiles", edit=True, value=fname)
        except Exception:
            pass
    joints = c.listRelatives("FitSkeleton", allDescendents=True, type="joint") or []
    return ToolResult(
        ok=True,
        data={"template": base, "fit_joints": len(joints), "file": ma},
        message=f"已导入 FitSkeleton「{base}」，{len(joints)} 个引导关节",
    )


@tool(
    name="adv_set_skin_meshes",
    description=(
        "设置 ADV Body>Pre 的 Skin 网格（AutoPlace / 部分蒙皮功能依赖此项）。"
        "names 为空则用当前选择中的 mesh transform。"
    ),
    parameters=obj_schema(
        {
            "names": {"type": "array", "items": {"type": "string"}, "default": []},
            "game_engine": {
                "type": "boolean",
                "default": True,
                "description": "勾选 Game Engine（游戏管线常用）",
            },
        }
    ),
    category="rigging",
)
def adv_set_skin_meshes(
    names: Optional[List[str]] = None,
    game_engine: bool = True,
) -> ToolResult:
    if not in_maya():
        return ToolResult(ok=False, error="未在 Maya 中运行")
    try:
        _ensure_sourced()
        _ensure_ui()
        meshes = _meshes_arg(names)
        _set_prep(meshes, game_engine=game_engine)
    except (RuntimeError, ValueError) as e:
        return ToolResult(ok=False, error=str(e))
    return ToolResult(
        ok=True,
        data={"meshes": meshes, "game_engine": game_engine},
        message=f"已设置 Skin: {', '.join(meshes)}",
    )


@tool(
    name="adv_auto_place_fit",
    description=(
        "按 Skin 网格自动缩放并贴合 FitSkeleton 引导关节（ADV AutoPlace/AutoScale）。"
        "必须已导入 FitSkeleton 且已设置 Skin。复杂网格可能失败，此时应手动调 Fit 再 Build。"
    ),
    parameters=obj_schema(
        {
            "mode": {
                "type": "string",
                "enum": ["auto_scale", "auto_place"],
                "default": "auto_scale",
                "description": "auto_scale=按身高缩放；auto_place=扫描网格摆关节（更慢）",
            }
        }
    ),
    category="rigging",
    destructive=True,
)
def adv_auto_place_fit(mode: str = "auto_scale") -> ToolResult:
    if not in_maya():
        return ToolResult(ok=False, error="未在 Maya 中运行")
    c = _cmds()
    try:
        _ensure_sourced()
        _ensure_ui()
    except RuntimeError as e:
        return ToolResult(ok=False, error=str(e))
    if not c.objExists("FitSkeleton"):
        return ToolResult(ok=False, error="没有 FitSkeleton，请先 adv_import_fit_skeleton")
    skin = ""
    if c.textField("asBodySkinTextField", exists=True):
        skin = c.textField("asBodySkinTextField", query=True, text=True) or ""
    if not skin and c.attributeQuery("objectsSkin", node="FitSkeleton", exists=True):
        skin = c.getAttr("FitSkeleton.objectsSkin") or ""
        _set_text_field("asBodySkinTextField", skin)
    if not (skin or "").strip():
        return ToolResult(ok=False, error="未设置 Skin 网格，请先 adv_set_skin_meshes")
    proc = "asFitAutoScale" if mode != "auto_place" else "asFitAutoPlace"
    try:
        _mel(f"{proc};")
    except Exception as e:
        return ToolResult(
            ok=False,
            error=f"{proc} 失败: {e}。可手动调整 Fit 关节后直接 adv_build_rig。",
        )
    return ToolResult(
        ok=True,
        data={"mode": mode, "skin": skin},
        message=f"Fit 已{('自动缩放' if mode != 'auto_place' else '自动贴模')}",
    )


@tool(
    name="adv_build_rig",
    description=(
        "执行 Build AdvancedSkeleton：由 FitSkeleton 生成变形骨骼（DeformSet）"
        "和 FK/IK 控制器（ControlSet）。场景中不能已有名为 Group 的无关物体。"
        "首次构建；若已有 Group 则走 ADV Rebuild。"
    ),
    parameters=obj_schema({}),
    category="rigging",
    destructive=True,
)
def adv_build_rig() -> ToolResult:
    if not in_maya():
        return ToolResult(ok=False, error="未在 Maya 中运行")
    c = _cmds()
    try:
        _ensure_sourced()
        _ensure_ui()
    except RuntimeError as e:
        return ToolResult(ok=False, error=str(e))
    if not c.objExists("FitSkeleton"):
        return ToolResult(ok=False, error="没有 FitSkeleton，请先导入模板")
    unit = c.currentUnit(query=True, linear=True)
    if unit not in ("cm", "centimeter"):
        c.currentUnit(linear="cm")
    try:
        _mel("asReBuildAdvancedSkeleton;")
    except Exception as e:
        return ToolResult(ok=False, error=f"Build 失败: {e}")
    st = _scene_status()
    if not st.get("Group"):
        return ToolResult(
            ok=False,
            error="Build 结束后未找到 Group，可能被对话框取消或命名冲突",
            data=st,
        )
    return ToolResult(
        ok=True,
        data=st,
        message=f"绑定已生成：变形关节 {st.get('DeformSet', 0)}，控制器 {st.get('ControlSet', 0)}",
    )


@tool(
    name="adv_bind_skin",
    description=(
        "将网格蒙皮到 ADV 变形骨骼。mode=smooth：Maya Smooth Bind（max_influences）。"
        "mode=cage：先建 SkinCage 再 copySkinWeights（更接近 ADV 自动权重）。"
        "names 为空则用已设置的 Skin 或当前选择。"
    ),
    parameters=obj_schema(
        {
            "names": {"type": "array", "items": {"type": "string"}, "default": []},
            "mode": {
                "type": "string",
                "enum": ["smooth", "cage"],
                "default": "smooth",
            },
            "max_influences": {"type": "integer", "default": 4},
        }
    ),
    category="rigging",
    destructive=True,
)
def adv_bind_skin(
    names: Optional[List[str]] = None,
    mode: str = "smooth",
    max_influences: int = 4,
) -> ToolResult:
    if not in_maya():
        return ToolResult(ok=False, error="未在 Maya 中运行")
    c = _cmds()
    try:
        _ensure_sourced()
        _ensure_ui()
        meshes = names or []
        if not meshes:
            if c.objExists("FitSkeleton") and c.attributeQuery(
                "objectsSkin", node="FitSkeleton", exists=True
            ):
                raw = (c.getAttr("FitSkeleton.objectsSkin") or "").split()
                meshes = [m for m in raw if c.objExists(m)]
            if not meshes:
                meshes = _meshes_arg([])
        else:
            meshes = _meshes_arg(meshes)
    except (RuntimeError, ValueError) as e:
        return ToolResult(ok=False, error=str(e))

    if not c.objExists("DeformSet"):
        return ToolResult(ok=False, error="没有 DeformSet，请先 adv_build_rig")

    bound: List[str] = []
    if mode == "cage":
        try:
            if not c.objExists("skinCage"):
                _mel("asCreateSkinCage;")
            c.select(meshes, replace=True)
            _mel("asCopySkin;")
            bound = list(meshes)
        except Exception as e:
            return ToolResult(ok=False, error=f"SkinCage 蒙皮失败: {e}")
        return ToolResult(
            ok=True,
            data={"mode": "cage", "meshes": bound, "skinCage": True},
            message=f"已通过 SkinCage 拷贝权重到 {len(bound)} 个网格",
        )

    # Smooth bind to DeformSet (exclude eyes/jaw like ADV)
    try:
        c.select(clear=True)
        _mel("asSelectDeformJoints;")
        joints = c.ls(selection=True, type="joint") or []
        if not joints:
            joints = c.sets("DeformSet", query=True) or []
        if not joints:
            return ToolResult(ok=False, error="DeformSet 为空")
        for mesh in meshes:
            c.select(joints, replace=True)
            c.select(mesh, add=True)
            sc = c.skinCluster(
                toSelectedBones=True,
                bindMethod=0,
                normalizeWeights=1,
                maximumInfluences=max(1, int(max_influences)),
                obeyMaxInfluences=True,
                dropoffRate=4.0,
                removeUnusedInfluence=False,
            )
            bound.append(sc[0] if isinstance(sc, (list, tuple)) else str(sc))
    except Exception as e:
        return ToolResult(ok=False, error=f"Smooth Bind 失败: {e}")
    return ToolResult(
        ok=True,
        data={"mode": "smooth", "skinClusters": bound, "meshes": meshes, "influences": len(joints)},
        message=f"已 Smooth Bind {len(meshes)} 个网格 → {len(joints)} 根变形骨骼",
    )


@tool(
    name="adv_create_controller",
    description=(
        "调用 ADV asCreateController 在指定 Fit 关节上生成控制器"
        "（type: FK/IK/Pole/Root/COG/Bend 等）。通常 Build 已批量创建，此工具用于补控。"
        "需要已 Build（存在 Main、对应 icon 曲线）。"
    ),
    parameters=obj_schema(
        {
            "ctrl_type": {
                "type": "string",
                "default": "FK",
                "description": "FK / IK / Pole / Root / Bend / Roll 等",
            },
            "name": {"type": "string", "description": "如 Shoulder、Elbow、Hip"},
            "side": {
                "type": "string",
                "default": "_M",
                "description": "_M / _L / _R",
            },
            "fit_joint": {
                "type": "string",
                "description": "Fit 关节名，如 Shoulder、Hip",
            },
        },
        required=["name", "fit_joint"],
    ),
    category="rigging",
    destructive=True,
)
def adv_create_controller(
    ctrl_type: str = "FK",
    name: str = "",
    side: str = "_M",
    fit_joint: str = "",
) -> ToolResult:
    if not in_maya():
        return ToolResult(ok=False, error="未在 Maya 中运行")
    c = _cmds()
    try:
        _ensure_sourced()
    except RuntimeError as e:
        return ToolResult(ok=False, error=str(e))
    if not c.objExists("Main"):
        return ToolResult(ok=False, error="未 Build，缺少 Main")
    fj = fit_joint.strip()
    if not c.objExists(fj):
        return ToolResult(ok=False, error=f"Fit 关节不存在: {fj}")
    side = side if side.startswith("_") else f"_{side}"
    try:
        _mel(f'asCreateController "{ctrl_type}" "{name}" "{side}" "{fj}";')
    except Exception as e:
        return ToolResult(ok=False, error=str(e))
    ctrl = f"{ctrl_type}{name}{side}"
    return ToolResult(
        ok=True,
        data={"controller": ctrl if c.objExists(ctrl) else None, "type": ctrl_type},
        message=f"已创建控制器 {ctrl}" if c.objExists(ctrl) else "已调用 asCreateController",
    )


@tool(
    name="adv_auto_rig",
    description=(
        "【可选·需安装 ADV】一键 ADV 绑定。"
        "日常请优先 auto_rig_character（原生，不依赖 ADV）。"
        "auto_place 失败时仍会尝试 Build（引导骨架保持默认比例）。"
    ),
    parameters=obj_schema(
        {
            "names": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": "角色网格 transform",
            },
            "template": {"type": "string", "default": "biped"},
            "bind_mode": {
                "type": "string",
                "enum": ["smooth", "cage", "none"],
                "default": "smooth",
            },
            "auto_place": {"type": "boolean", "default": True},
            "game_engine": {"type": "boolean", "default": True},
            "max_influences": {"type": "integer", "default": 4},
        }
    ),
    category="rigging",
    destructive=True,
)
def adv_auto_rig(
    names: Optional[List[str]] = None,
    template: str = "biped",
    bind_mode: str = "smooth",
    auto_place: bool = True,
    game_engine: bool = True,
    max_influences: int = 4,
) -> ToolResult:
    if not in_maya():
        return ToolResult(ok=False, error="未在 Maya 中运行")
    steps: List[str] = []
    warnings: List[str] = []

    r = adv_import_fit_skeleton(template=template, replace=True, open_ui=True)
    if not r.ok:
        return r
    steps.append(r.message)

    r = adv_set_skin_meshes(names=names or [], game_engine=game_engine)
    if not r.ok:
        return r
    steps.append(r.message)
    meshes = (r.data or {}).get("meshes") or []

    if auto_place:
        r = adv_auto_place_fit(mode="auto_scale")
        if r.ok:
            steps.append(r.message)
        else:
            warnings.append(r.error or "AutoPlace 失败，使用默认 Fit 比例继续 Build")

    r = adv_build_rig()
    if not r.ok:
        r.data = dict(r.data or {})
        r.data.update({"steps": steps, "warnings": warnings})
        return r
    steps.append(r.message)

    if bind_mode and bind_mode != "none":
        r = adv_bind_skin(names=meshes, mode=bind_mode, max_influences=max_influences)
        if not r.ok:
            warnings.append(r.error or "蒙皮失败")
        else:
            steps.append(r.message)

    st = _scene_status()
    return ToolResult(
        ok=True,
        data={"steps": steps, "warnings": warnings, "scene": st, "meshes": meshes},
        message="ADV 自动绑定完成"
        + (f"（{len(warnings)} 条警告）" if warnings else ""),
    )
