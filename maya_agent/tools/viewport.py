"""Viewport capture tools for vision-capable models."""

from __future__ import annotations

import glob
import os
import tempfile
from typing import Callable, List, Optional, Tuple

from maya_agent.llm.image_codec import attachment_from_raw_file
from maya_agent.tools._maya import cmds as _cmds
from maya_agent.tools.registry import ToolResult, obj_schema, tool
from maya_agent.utils.logger import get_logger

log = get_logger("maya_agent.tools.viewport")

_DEFAULT_W = 1280
_DEFAULT_H = 720


def _resolve_model_panel(panel: str = "") -> str:
    c = _cmds()
    if panel:
        try:
            if c.getPanel(typeOf=panel) == "modelPanel":
                return panel
        except Exception:
            pass
    focus = c.getPanel(withFocus=True) or ""
    if focus:
        try:
            if c.getPanel(typeOf=focus) == "modelPanel":
                return focus
        except Exception:
            pass
    panels = c.getPanel(type="modelPanel") or []
    if not panels:
        raise RuntimeError("未找到可用的模型视口（modelPanel）")
    return panels[0]


def _playblast_still(
    width: int,
    height: int,
    *,
    show_ornaments: bool,
    panel: str,
) -> str:
    """Capture one frame via playblast; return path to the image file."""
    c = _cmds()
    tmp_dir = tempfile.mkdtemp(prefix="mayaagent_vp_")
    stem = os.path.join(tmp_dir, "viewport")
    frame = float(c.currentTime(query=True))
    kwargs = dict(
        filename=stem,
        format="image",
        compression="jpg",
        width=int(width),
        height=int(height),
        forceOverwrite=True,
        showOrnaments=bool(show_ornaments),
        viewer=False,
        frame=[frame],
        percent=100,
        quality=85,
        clearCache=True,
    )
    # Prefer named panel; fall back if the flag is unsupported on this Maya build
    attempts = [
        dict(kwargs, editorPanelName=panel, offScreen=True),
        dict(kwargs, editorPanelName=panel),
        dict(kwargs, offScreen=True),
        dict(kwargs),
    ]
    path = None
    last_err = None
    for attempt in attempts:
        try:
            path = c.playblast(**attempt)
            break
        except Exception as e:
            last_err = e
            log.debug("playblast attempt failed: %s", e)
    if not path and last_err:
        raise RuntimeError(f"playblast 失败: {last_err}")

    found = _find_playblast_file(stem, path)
    if not found:
        raise RuntimeError("playblast 未生成图像文件")
    return found


def _find_playblast_file(stem: str, playblast_return) -> Optional[str]:
    candidates: List[str] = []
    if isinstance(playblast_return, str) and playblast_return:
        candidates.append(playblast_return.replace("\\", "/"))
    for pattern in (
        stem + ".*",
        stem + ".*.*",
        stem + "*.jpg",
        stem + "*.jpeg",
        stem + "*.png",
        os.path.dirname(stem) + "/*",
    ):
        candidates.extend(glob.glob(pattern))
    files = []
    for p in candidates:
        if not p or not os.path.isfile(p):
            continue
        low = p.lower()
        if low.endswith((".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp")):
            files.append(p)
    if not files:
        return None
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return files[0]


def _grab_m3dview_fallback() -> str:
    """Fallback: read active 3d view color buffer to a temp PNG."""
    import maya.OpenMaya as om
    import maya.OpenMayaUI as omui

    view = omui.M3dView.active3dView()
    img = om.MImage()
    view.readColorBuffer(img, True)
    tmp = tempfile.NamedTemporaryFile(prefix="mayaagent_vp_", suffix=".png", delete=False)
    tmp.close()
    img.writeToFile(tmp.name, "png")
    if not os.path.isfile(tmp.name) or os.path.getsize(tmp.name) < 32:
        raise RuntimeError("M3dView 截图失败")
    return tmp.name


def _with_camera(panel: str, camera: str):
    """Context-like pair: (previous_camera or None, restore_fn)."""
    c = _cmds()
    if not camera:
        return None, (lambda: None)
    if not c.objExists(camera):
        raise RuntimeError(f"相机不存在: {camera}")
    prev = c.modelEditor(panel, query=True, camera=True)
    # lookThru(camera, panel=...) — panel 必须是关键字，不能当物体名
    c.lookThru(camera, panel=panel)

    def _restore():
        try:
            if prev:
                c.lookThru(prev, panel=panel)
        except Exception:
            pass

    return prev, _restore


def _maybe_frame(
    panel: str, names: Optional[List[str]], frame_selection: bool
) -> Tuple[Optional[list], Callable[[], None]]:
    c = _cmds()
    prev_sel = c.ls(selection=True, long=True) or []
    targets = [n for n in (names or []) if n and c.objExists(n)]
    if frame_selection and not targets:
        targets = list(prev_sel)
    if not targets:
        return None, (lambda: None)

    def _restore():
        try:
            if prev_sel:
                c.select(prev_sel, replace=True)
            else:
                c.select(clear=True)
        except Exception:
            pass

    try:
        c.select(targets, replace=True)
        # viewFit 的位置参数是「要取景的物体」；面板用 panel= 指定
        c.viewFit(targets, animate=False, panel=panel)
    except Exception as e:
        _restore()
        raise RuntimeError(f"取景失败: {e}") from e
    return targets, _restore


@tool(
    name="capture_viewport",
    description=(
        "截取当前 Maya 模型视口画面，供视觉模型分析场景外观、布局、比例与问题。"
        "仅当当前模型支持视觉输入时可用。"
        "在需要「看看场景长什么样」、核对造型/布线外观、检查绑定姿势、对比参考图时调用；"
        "截图会自动附到对话中供你查看，无需用户手动贴图。"
    ),
    parameters=obj_schema(
        {
            "width": {
                "type": "integer",
                "default": _DEFAULT_W,
                "description": "截图宽度，默认 1280",
            },
            "height": {
                "type": "integer",
                "default": _DEFAULT_H,
                "description": "截图高度，默认 720",
            },
            "camera": {
                "type": "string",
                "default": "",
                "description": "可选相机名；空则使用当前视口相机，截完后恢复",
            },
            "panel": {
                "type": "string",
                "default": "",
                "description": "可选 modelPanel 名；空则取焦点/首个模型面板",
            },
            "frame_objects": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": "可选：截图前对这些物体 viewFit（临时改选择，截完恢复）",
            },
            "frame_selection": {
                "type": "boolean",
                "default": False,
                "description": "若为 true 且未指定 frame_objects，则对当前选择取景",
            },
            "show_ornaments": {
                "type": "boolean",
                "default": False,
                "description": "是否显示 HUD/分辨率门等装饰",
            },
            "note": {
                "type": "string",
                "default": "",
                "description": "可选说明，便于记录本次截图意图（如「检查手臂穿模」）",
            },
        }
    ),
    category="scene",
    requires_vision=True,
)
def capture_viewport(
    width: int = _DEFAULT_W,
    height: int = _DEFAULT_H,
    camera: str = "",
    panel: str = "",
    frame_objects: Optional[List[str]] = None,
    frame_selection: bool = False,
    show_ornaments: bool = False,
    note: str = "",
) -> ToolResult:
    c = _cmds()
    width = max(320, min(int(width or _DEFAULT_W), 1920))
    height = max(240, min(int(height or _DEFAULT_H), 1080))

    panel_name = _resolve_model_panel(panel or "")
    _prev_cam, restore_cam = _with_camera(panel_name, (camera or "").strip())
    del _prev_cam
    framed, restore_sel = _maybe_frame(
        panel_name, frame_objects, bool(frame_selection)
    )

    image_path = ""
    capture_method = "playblast"
    try:
        # Force a refresh so the buffer matches the current lookThru / viewFit
        try:
            c.refresh(force=True)
        except Exception:
            pass
        try:
            image_path = _playblast_still(
                width,
                height,
                show_ornaments=show_ornaments,
                panel=panel_name,
            )
        except Exception as e:
            log.warning("playblast capture failed, trying M3dView: %s", e)
            capture_method = "m3dview"
            image_path = _grab_m3dview_fallback()
    finally:
        restore_sel()
        restore_cam()

    try:
        attachment = attachment_from_raw_file(image_path)
        attachment.name = attachment.name or "viewport.jpg"
    except Exception as e:
        return ToolResult(ok=False, error=f"截图编码失败: {e}")
    finally:
        _cleanup_capture(image_path)

    cam_now = ""
    try:
        cam_now = c.modelEditor(panel_name, query=True, camera=True) or ""
    except Exception:
        pass

    data = {
        "panel": panel_name,
        "camera": cam_now or (camera or ""),
        "width": width,
        "height": height,
        "method": capture_method,
        "framed": framed or [],
    }
    msg = "视口截图已完成"
    if note:
        msg = f"{msg}：{note}"
    return ToolResult(
        ok=True,
        data=data,
        message=msg,
        images=[attachment],
    )


def _cleanup_capture(path: str) -> None:
    if not path:
        return
    try:
        parent = os.path.dirname(path)
        if os.path.isfile(path):
            os.remove(path)
        # remove empty temp dir created for playblast
        if parent and os.path.isdir(parent) and "mayaagent_vp_" in parent:
            for leftover in glob.glob(os.path.join(parent, "*")):
                try:
                    os.remove(leftover)
                except Exception:
                    pass
            try:
                os.rmdir(parent)
            except Exception:
                pass
    except Exception:
        pass
