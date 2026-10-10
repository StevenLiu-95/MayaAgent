"""AdvancedSkeleton (ADV) MEL bridge for Maya Agent.

When AdvancedSkeleton is installed, ``adv_*`` tools are exposed to the LLM.
Quick path: ``adv_rig_status`` → ``adv_auto_rig`` (or ``adv_next_step`` stepwise).

Native alternatives (no ADV): create_skeleton_* / create_skin_cage /
bind_from_skin_cage / build_fk_ik_controls / auto_rig_character.
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


def adv_tools_available() -> bool:
    """Whether adv_* tools should be exposed to the LLM (ADV install found)."""
    return bool(_find_adv_root())


def filter_system_prompt_adv(text: str) -> str:
    """Strip AdvancedSkeleton guidance when ADV tools are unavailable."""
    if adv_tools_available():
        return text
    lines = text.splitlines(keepends=True)
    out: List[str] = []
    skipping = False
    for line in lines:
        stripped = line.lstrip()
        if not skipping and (
            stripped.startswith("## AdvancedSkeleton")
            or stripped.startswith("# AdvancedSkeleton")
            or stripped.startswith("# ADV")
        ):
            skipping = True
            continue
        if skipping:
            if stripped.startswith("## ") or (
                stripped.startswith("# ")
                and not stripped.startswith("# AdvancedSkeleton")
                and not stripped.startswith("# ADV")
            ):
                skipping = False
                out.append(line)
            continue
        if stripped.startswith("|") and ("AdvancedSkeleton" in line or "ADV" in line):
            continue
        out.append(line)
    return "".join(out)


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


def _skin_meshes_configured() -> List[str]:
    c = _cmds()
    raw = ""
    if c.textField("asBodySkinTextField", exists=True):
        raw = c.textField("asBodySkinTextField", query=True, text=True) or ""
    if not raw and c.objExists("FitSkeleton"):
        if c.attributeQuery("objectsSkin", node="FitSkeleton", exists=True):
            raw = c.getAttr("FitSkeleton.objectsSkin") or ""
    names = [m for m in str(raw).split() if m and c.objExists(m)]
    return names


def _recommend_next(scene: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return the single next ADV action for the current scene state."""
    st = scene if scene is not None else (_scene_status() if in_maya() else {})
    has_fit = bool(st.get("FitSkeleton"))
    has_group = bool(st.get("Group"))
    deform_n = int(st.get("DeformSet") or 0)
    skin_meshes = _skin_meshes_configured() if in_maya() else []
    objects_skin = (st.get("objectsSkin") or "").strip()

    if not has_fit:
        return {
            "action": "adv_import_fit_skeleton",
            "args": {"template": "biped", "replace": True},
            "reason": "场景尚无 FitSkeleton，先导入引导骨架",
            "or_oneshot": "adv_auto_rig",
        }
    if not objects_skin and not skin_meshes:
        return {
            "action": "adv_set_skin_meshes",
            "args": {"names": [], "game_engine": True},
            "reason": "未设置 Skin 网格（可用当前选择）",
            "or_oneshot": "adv_auto_rig",
        }
    if not has_group or deform_n <= 0:
        # Prefer auto_scale if fit looks unplaced; always safe to suggest place then build
        if not has_group:
            return {
                "action": "adv_auto_place_fit",
                "args": {"mode": "auto_scale"},
                "reason": "已有 Fit+Skin，建议先 AutoScale，再 adv_build_rig",
                "after": "adv_build_rig",
                "or_oneshot": "adv_auto_rig",
            }
        return {
            "action": "adv_build_rig",
            "args": {},
            "reason": "Fit 已就绪但未 Build（缺 Group/DeformSet）",
            "or_oneshot": "adv_auto_rig",
        }
    # Built — check if meshes already skinned
    need_bind = False
    if in_maya() and skin_meshes:
        c = _cmds()
        for m in skin_meshes:
            hist = c.listHistory(m) or []
            if not (c.ls(hist, type="skinCluster") or []):
                need_bind = True
                break
    elif in_maya() and objects_skin:
        need_bind = True
    if need_bind:
        return {
            "action": "adv_bind_skin",
            "args": {"mode": "cage", "max_influences": 4},
            "reason": "已 Build，网格尚未蒙皮；推荐 cage 模式",
            "or_oneshot": None,
        }
    return {
        "action": "done",
        "args": {},
        "reason": "ADV 绑定已就绪（Fit + Group/DeformSet + 蒙皮）",
        "or_oneshot": None,
    }


def _workflow_checklist() -> List[Dict[str, str]]:
    return [
        {"step": 1, "tool": "adv_rig_status", "note": "确认 ADV 可用与场景阶段"},
        {"step": 2, "tool": "adv_auto_rig", "note": "一键：导入Fit→设Skin→AutoScale→Build→蒙皮"},
        {
            "step": "2alt",
            "tool": "adv_next_step",
            "note": "分步：每次执行下一必要步骤，便于中途调 Fit",
        },
        {
            "step": 3,
            "tool": "adv_create_controller",
            "note": "可选：Build 后补 FK/IK/Pole 控制器",
        },
    ]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@tool(
    name="adv_rig_status",
    description=(
        "检查 AdvancedSkeleton 是否可用、场景绑定阶段，并返回下一步推荐动作（next）。"
        "开始 ADV 绑定前先调用；也可在中途用来决定调用 adv_next_step 还是 adv_auto_rig。"
    ),
    parameters=obj_schema({}),
    category="adv",
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
    scene = _scene_status()
    next_action = _recommend_next(scene) if root else None
    data = {
        "available": bool(root),
        "adv_root": root or None,
        "sourced": sourced,
        "templates": list(_TEMPLATES),
        "scene": scene,
        "next": next_action,
        "workflow": _workflow_checklist(),
        "oneshot": "adv_auto_rig",
        "hint": (
            "完整角色绑定优先 adv_auto_rig；需要手动调 Fit 时用 adv_next_step 分步。"
            if root
            else "未找到 ADV：在设置中填写 AdvancedSkeleton 路径，或改用 auto_rig_character。"
        ),
    }
    if not root:
        return ToolResult(
            ok=False,
            error="未找到 AdvancedSkeleton 安装目录（设置 maya.advanced_skeleton_path）",
            data=data,
        )
    nxt = (next_action or {}).get("action", "?")
    return ToolResult(
        ok=True,
        data=data,
        message=f"ADV 可用：{root}；下一步 → {nxt}",
    )


@tool(
    name="adv_list_fit_templates",
    description=(
        "列出 AdvancedSkeleton FitSkeleton 模板（biped / bipedGame / UE5 / cat / dragon 等）。"
        "选模板后交给 adv_import_fit_skeleton 或 adv_auto_rig(template=...)."
    ),
    parameters=obj_schema({}),
    category="adv",
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
        "ADV 流程第1步：导入 FitSkeleton 引导骨架（非最终变形骨）。"
        "模板 biped / bipedGame / UE5 / cat 等。replace=true 替换已有 Fit。"
        "完成后通常 adv_set_skin_meshes → adv_auto_place_fit → adv_build_rig；"
        "或直接用 adv_auto_rig / adv_next_step。"
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
    category="adv",
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
        "ADV 流程第2步：设置 Body>Pre 的 Skin 网格（AutoPlace / 蒙皮依赖）。"
        "names 为空则用当前选择中的 mesh transform。游戏角色保持 game_engine=true。"
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
    category="adv",
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
        "ADV 流程第3步：按 Skin 网格 AutoScale/AutoPlace Fit 引导关节。"
        "需已有 FitSkeleton + Skin。失败时可让用户手动调 Fit，再 adv_build_rig。"
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
    category="adv",
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
        "ADV 流程第4步：Build —— 由 FitSkeleton 生成变形骨（DeformSet）"
        "与 FK/IK 控制器（ControlSet）。场景勿有无关的 Group 节点命名冲突。"
        "已有 Group 时走 Rebuild。完成后可用 adv_bind_skin。"
    ),
    parameters=obj_schema({}),
    category="adv",
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
        "ADV 流程第5步：把网格蒙皮到 DeformSet。"
        "mode=cage：ADV SkinCage 拷权（推荐，更接近 ADV 自动权重）；"
        "mode=smooth：Maya Smooth Bind。names 空则用已设 Skin / 当前选择。"
    ),
    parameters=obj_schema(
        {
            "names": {"type": "array", "items": {"type": "string"}, "default": []},
            "mode": {
                "type": "string",
                "enum": ["smooth", "cage"],
                "default": "cage",
            },
            "max_influences": {"type": "integer", "default": 4},
        }
    ),
    category="adv",
    destructive=True,
)
def adv_bind_skin(
    names: Optional[List[str]] = None,
    mode: str = "cage",
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
    warnings: List[str] = []
    if mode == "cage":
        try:
            if not c.objExists("skinCage"):
                _mel("asCreateSkinCage;")
            c.select(meshes, replace=True)
            _mel("asCopySkin;")
            bound = list(meshes)
            return ToolResult(
                ok=True,
                data={"mode": "cage", "meshes": bound, "skinCage": True},
                message=f"已通过 SkinCage 拷贝权重到 {len(bound)} 个网格",
            )
        except Exception as e:
            warnings.append(f"SkinCage 失败，回退 Smooth Bind: {e}")
            mode = "smooth"

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
        return ToolResult(ok=False, error=f"Smooth Bind 失败: {e}", data={"warnings": warnings})
    return ToolResult(
        ok=True,
        data={
            "mode": "smooth",
            "skinClusters": bound,
            "meshes": meshes,
            "influences": len(joints),
            "warnings": warnings,
        },
        message=f"已 Smooth Bind {len(meshes)} 个网格 → {len(joints)} 根变形骨骼"
        + (f"（{len(warnings)} 警告）" if warnings else ""),
    )


@tool(
    name="adv_create_controller",
    description=(
        "ADV 补控制器：asCreateController（FK/IK/Pole/Root/Bend 等）。"
        "Build 通常已批量生成；仅在缺失或定制时调用。需已有 Main。"
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
    category="adv",
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
    name="adv_next_step",
    description=(
        "ADV 智能下一步：根据场景状态自动执行下一必要步骤"
        "（导入Fit / 设Skin / AutoScale / Build / 蒙皮）。"
        "适合需要中途微调 Fit 的分步绑定；完整一键请用 adv_auto_rig。"
        "可先 adv_rig_status 查看 next，再反复调用本工具直到 action=done。"
    ),
    parameters=obj_schema(
        {
            "template": {
                "type": "string",
                "default": "biped",
                "description": "仅在尚无 FitSkeleton 时用于导入",
            },
            "meshes": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": "设 Skin 时用；空则当前选择",
            },
            "bind_mode": {
                "type": "string",
                "enum": ["smooth", "cage"],
                "default": "cage",
            },
            "place_mode": {
                "type": "string",
                "enum": ["auto_scale", "auto_place"],
                "default": "auto_scale",
            },
            "game_engine": {"type": "boolean", "default": True},
            "max_influences": {"type": "integer", "default": 4},
            "skip_place": {
                "type": "boolean",
                "default": False,
                "description": "True 时跳过 AutoPlace，直接 Build（Fit 已手调好）",
            },
        }
    ),
    category="adv",
    destructive=True,
)
def adv_next_step(
    template: str = "biped",
    meshes: Optional[List[str]] = None,
    bind_mode: str = "cage",
    place_mode: str = "auto_scale",
    game_engine: bool = True,
    max_influences: int = 4,
    skip_place: bool = False,
) -> ToolResult:
    if not in_maya():
        return ToolResult(ok=False, error="未在 Maya 中运行")
    if not _find_adv_root():
        return ToolResult(
            ok=False,
            error="未找到 AdvancedSkeleton，请在设置中配置路径或改用 auto_rig_character",
        )

    scene = _scene_status()
    plan = _recommend_next(scene)
    action = plan.get("action") or "done"

    if action == "done":
        return ToolResult(
            ok=True,
            data={"action": "done", "scene": scene, "next": plan},
            message=plan.get("reason") or "ADV 绑定已完成",
        )

    if action == "adv_import_fit_skeleton":
        r = adv_import_fit_skeleton(template=template, replace=True, open_ui=True)
    elif action == "adv_set_skin_meshes":
        r = adv_set_skin_meshes(names=meshes or [], game_engine=game_engine)
    elif action == "adv_auto_place_fit":
        if skip_place:
            r = adv_build_rig()
            action = "adv_build_rig"
        else:
            place = adv_auto_place_fit(mode=place_mode)
            warnings: List[str] = []
            if not place.ok:
                warnings.append(place.error or "AutoPlace 失败，使用默认 Fit 比例继续 Build")
            build = adv_build_rig()
            return ToolResult(
                ok=build.ok,
                data={
                    "action": "adv_auto_place_fit+adv_build_rig",
                    "place": place.data,
                    "build": build.data,
                    "next": _recommend_next(),
                    "warnings": warnings
                    + ([] if build.ok else [build.error or "Build 失败"]),
                },
                message=(
                    f"{place.message or 'AutoPlace 跳过'} → {build.message}"
                    if build.ok
                    else (build.error or "Build 失败")
                ),
                error=build.error if not build.ok else "",
            )
    elif action == "adv_build_rig":
        r = adv_build_rig()
    elif action == "adv_bind_skin":
        r = adv_bind_skin(
            names=meshes or [],
            mode=bind_mode,
            max_influences=max_influences,
        )
    else:
        return ToolResult(ok=False, error=f"未知下一步: {action}", data={"plan": plan})

    if not r.ok:
        r.data = dict(r.data or {})
        r.data.update({"action": action, "plan": plan, "next": _recommend_next()})
        return r

    nxt = _recommend_next()
    return ToolResult(
        ok=True,
        data={
            "action": action,
            "result": r.data,
            "next": nxt,
            "scene": _scene_status(),
        },
        message=f"已执行 {action}：{r.message}；下一步 → {nxt.get('action')}",
    )


@tool(
    name="adv_auto_rig",
    description=(
        "【推荐】一键 AdvancedSkeleton 完整绑定："
        "导入 Fit → 设 Skin → AutoScale → Build → 蒙皮（默认 cage）。"
        "用户要 ADV / Advanced Skeleton / 完整控制器绑定时优先本工具。"
        "names 空则用当前选择。auto_place 失败仍会继续 Build。"
        "需中途手调 Fit 时改用 adv_next_step。"
    ),
    parameters=obj_schema(
        {
            "names": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": "角色网格 transform；空=当前选择",
            },
            "template": {
                "type": "string",
                "default": "biped",
                "description": "Fit 模板：biped / bipedGame / UE5 / cat / dragon 等",
            },
            "bind_mode": {
                "type": "string",
                "enum": ["smooth", "cage", "none"],
                "default": "cage",
            },
            "auto_place": {"type": "boolean", "default": True},
            "game_engine": {"type": "boolean", "default": True},
            "max_influences": {"type": "integer", "default": 4},
        }
    ),
    category="adv",
    destructive=True,
)
def adv_auto_rig(
    names: Optional[List[str]] = None,
    template: str = "biped",
    bind_mode: str = "cage",
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
