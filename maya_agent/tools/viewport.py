"""Viewport capture tools for vision-capable models."""

from __future__ import annotations

import glob
import math
import os
import tempfile
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from maya_agent.llm.base import ImageAttachment
from maya_agent.llm.image_codec import MAX_IMAGES, attachment_from_raw_file
from maya_agent.tools._maya import cmds as _cmds
from maya_agent.tools.registry import ToolResult, obj_schema, tool
from maya_agent.utils.logger import get_logger
from maya_agent.utils.paths import agent_temp_subdir

log = get_logger("maya_agent.tools.viewport")


def _viewport_temp_dir() -> str:
    """Directory for playblast / M3dView capture temps under the agent temp root."""
    return str(agent_temp_subdir("viewport"))

_DEFAULT_W = 1280
_DEFAULT_H = 720
_MULTI_W = 960
_MULTI_H = 540
_EMPTY_VARIANCE = 12.0  # below → mostly flat / empty frame
_LOW_COVERAGE = 0.22  # subject angular/ortho size vs FOV; below → warn

_MODEL_EDITOR_OVERLAYS = (
    "joints",
    "ikHandles",
    "locators",
    "nurbsCurves",
    "cv",
    "hulls",
    "deformers",
    "cameras",
    "lights",
    "grid",
    "manipulators",
    "selectionHiliteDisplay",
)

_VIEW_CAMERA_ALIASES: Dict[str, List[str]] = {
    "persp": ["persp"],
    "front": ["front"],
    "back": ["back"],
    "side": ["side"],
    "right": ["side", "right"],
    "left": ["left"],
    "top": ["top"],
    "bottom": ["bottom"],
}
_DEFAULT_MULTI_VIEWS = ["persp", "front", "side", "top"]
_VIEW_EYE_OFFSET: Dict[str, Tuple[float, float, float]] = {
    "persp": (1.0, 0.7, 1.0),
    "front": (0.0, 0.0, 1.0),
    "back": (0.0, 0.0, -1.0),
    "side": (1.0, 0.0, 0.0),
    "right": (1.0, 0.0, 0.0),
    "left": (-1.0, 0.0, 0.0),
    "top": (0.0, 1.0, 0.0),
    "bottom": (0.0, -1.0, 0.0),
}


# ---------------------------------------------------------------------------
# Panel / capture primitives
# ---------------------------------------------------------------------------


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


def _focus_model_panel(panel: str) -> None:
    if not panel:
        return
    c = _cmds()
    try:
        c.setFocus(panel)
    except Exception:
        pass


def _set_panel_camera(panel: str, camera: str) -> None:
    c = _cmds()
    if not panel or not camera:
        raise RuntimeError("panel/camera 不能为空")
    try:
        c.modelEditor(panel, edit=True, camera=camera)
        return
    except Exception as e1:
        try:
            c.lookThru(camera, panel)
            return
        except Exception:
            pass
        try:
            c.setFocus(panel)
            c.lookThru(camera)
            return
        except Exception as e3:
            raise RuntimeError(
                f"无法将相机 {camera} 切到面板 {panel}: {e1}; {e3}"
            ) from e3


def _with_camera(panel: str, camera: str):
    c = _cmds()
    if not camera:
        return None, (lambda: None)
    if not c.objExists(camera):
        raise RuntimeError(f"相机不存在: {camera}")
    prev = ""
    try:
        prev = c.modelEditor(panel, query=True, camera=True) or ""
    except Exception:
        prev = ""
    _set_panel_camera(panel, camera)

    def _restore():
        if prev:
            try:
                _set_panel_camera(panel, prev)
            except Exception:
                pass

    return prev, _restore


def _playblast_still(
    width: int,
    height: int,
    *,
    show_ornaments: bool,
    panel: str,
) -> str:
    c = _cmds()
    tmp_dir = tempfile.mkdtemp(prefix="mayaagent_vp_", dir=_viewport_temp_dir())
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
    import maya.OpenMaya as om
    import maya.OpenMayaUI as omui

    view = omui.M3dView.active3dView()
    img = om.MImage()
    view.readColorBuffer(img, True)
    tmp = tempfile.NamedTemporaryFile(
        prefix="mayaagent_vp_",
        suffix=".png",
        delete=False,
        dir=_viewport_temp_dir(),
    )
    tmp.close()
    img.writeToFile(tmp.name, "png")
    if not os.path.isfile(tmp.name) or os.path.getsize(tmp.name) < 32:
        raise RuntimeError("M3dView 截图失败")
    return tmp.name


def _cleanup_capture(path: str) -> None:
    if not path:
        return
    try:
        parent = os.path.dirname(path)
        if os.path.isfile(path):
            os.remove(path)
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


def _capture_panel_image(
    panel: str,
    width: int,
    height: int,
    *,
    show_ornaments: bool = False,
) -> Tuple[str, str]:
    c = _cmds()
    try:
        c.refresh(force=True)
    except Exception:
        pass
    try:
        return (
            _playblast_still(
                width, height, show_ornaments=show_ornaments, panel=panel
            ),
            "playblast",
        )
    except Exception as e:
        log.warning("playblast capture failed, trying M3dView: %s", e)
        return _grab_m3dview_fallback(), "m3dview"


# ---------------------------------------------------------------------------
# BBox / camera metadata / empty-frame detection
# ---------------------------------------------------------------------------


def _resolve_frame_targets(
    frame_objects: Optional[List[str]],
    frame_selection: bool,
) -> List[str]:
    c = _cmds()
    targets = [n for n in (frame_objects or []) if n and c.objExists(n)]
    if not targets and frame_selection:
        targets = c.ls(selection=True, long=True) or []
    return targets


def _scene_mesh_transforms() -> List[str]:
    c = _cmds()
    meshes = c.ls(type="mesh", long=True) or []
    out: List[str] = []
    for m in meshes:
        parents = c.listRelatives(m, parent=True, fullPath=True) or []
        out.append(parents[0] if parents else m)
    return list(dict.fromkeys(out))


def _world_bbox(objects: Optional[Sequence[str]] = None) -> Optional[Dict[str, Any]]:
    c = _cmds()
    targets = [n for n in (objects or []) if n and c.objExists(n)]
    if not targets:
        targets = _scene_mesh_transforms()
    if not targets:
        return None
    try:
        bb = c.exactWorldBoundingBox(targets)
    except Exception:
        return None
    size = [
        float(bb[3] - bb[0]),
        float(bb[4] - bb[1]),
        float(bb[5] - bb[2]),
    ]
    center = [
        0.5 * (bb[0] + bb[3]),
        0.5 * (bb[1] + bb[4]),
        0.5 * (bb[2] + bb[5]),
    ]
    return {
        "min": [float(bb[0]), float(bb[1]), float(bb[2])],
        "max": [float(bb[3]), float(bb[4]), float(bb[5])],
        "center": center,
        "size": size,
        "diagonal": float(math.sqrt(sum(s * s for s in size))),
        "object_count": len(targets),
    }


def _camera_shape(camera: str) -> str:
    c = _cmds()
    if not camera or not c.objExists(camera):
        return ""
    try:
        if c.nodeType(camera) == "camera":
            return camera
    except Exception:
        pass
    shapes = c.listRelatives(camera, shapes=True, type="camera", fullPath=True) or []
    return shapes[0] if shapes else ""


def _camera_meta(camera: str) -> Dict[str, Any]:
    c = _cmds()
    meta: Dict[str, Any] = {"camera": camera or ""}
    if not camera or not c.objExists(camera):
        return meta
    shape = _camera_shape(camera)
    meta["shape"] = shape
    try:
        meta["position"] = [float(x) for x in c.xform(camera, q=True, ws=True, t=True)]
        meta["rotation"] = [float(x) for x in c.xform(camera, q=True, ws=True, ro=True)]
    except Exception:
        pass
    if not shape:
        return meta
    for attr, key in (
        ("nearClipPlane", "near_clip"),
        ("farClipPlane", "far_clip"),
        ("focalLength", "focal_length"),
        ("orthographic", "orthographic"),
        ("orthographicWidth", "orthographic_width"),
        ("horizontalFilmAperture", "film_aperture_h"),
        ("verticalFilmAperture", "film_aperture_v"),
    ):
        try:
            if c.attributeQuery(attr, node=shape, exists=True):
                val = c.getAttr(f"{shape}.{attr}")
                meta[key] = bool(val) if attr == "orthographic" else float(val)
        except Exception:
            pass
    return meta


def _analyze_image_emptiness(path: str) -> Dict[str, Any]:
    """Detect near-solid / empty frames via sampled pixel variance."""
    info: Dict[str, Any] = {
        "mostly_empty": False,
        "variance": None,
        "sample_count": 0,
    }
    try:
        from maya_agent.utils.maya_compat import import_qt

        _QtCore, QtGui, _QtWidgets, _ = import_qt()
        image = QtGui.QImage(path)
        if image.isNull():
            return info
        w, h = image.width(), image.height()
        step = max(1, min(w, h) // 32)
        vals: List[float] = []
        y = 0
        while y < h:
            x = 0
            while x < w:
                col = image.pixelColor(x, y)
                # luma
                vals.append(0.2126 * col.red() + 0.7152 * col.green() + 0.0722 * col.blue())
                x += step
            y += step
        if not vals:
            return info
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        info["variance"] = round(var, 2)
        info["sample_count"] = len(vals)
        info["mean_luma"] = round(mean, 2)
        info["mostly_empty"] = var < _EMPTY_VARIANCE
    except Exception as e:
        log.debug("empty-frame analysis skipped: %s", e)
    return info


def _clip_warning(cam_meta: Dict[str, Any], bbox: Optional[Dict[str, Any]]) -> str:
    if not bbox or not cam_meta:
        return ""
    far = cam_meta.get("far_clip")
    pos = cam_meta.get("position")
    if far is None or not pos:
        return ""
    center = bbox["center"]
    diag = float(bbox.get("diagonal") or 0)
    dist = math.sqrt(
        (pos[0] - center[0]) ** 2
        + (pos[1] - center[1]) ** 2
        + (pos[2] - center[2]) ** 2
    )
    # Content beyond far plane (camera to far edge of bbox)
    if dist + diag * 0.5 > float(far) * 0.95:
        return (
            f"场景尺度可能超出相机远裁剪面（相机距中心≈{dist:.0f}，"
            f"bbox对角≈{diag:.0f}，farClip≈{far:.0f}），内容可能被裁掉"
        )
    return ""


def _subject_coverage(cam_meta: Dict[str, Any], bbox: Optional[Dict[str, Any]]) -> Optional[float]:
    """Estimate how much of the frame the bbox occupies (0–1)."""
    if not bbox or not cam_meta:
        return None
    pos = cam_meta.get("position")
    center = bbox.get("center")
    diag = float(bbox.get("diagonal") or 0)
    if not pos or not center or diag <= 0:
        return None
    dist = math.sqrt(
        (pos[0] - center[0]) ** 2
        + (pos[1] - center[1]) ** 2
        + (pos[2] - center[2]) ** 2
    )
    radius = 0.5 * diag
    if cam_meta.get("orthographic"):
        ow = float(cam_meta.get("orthographic_width") or 0) or 1.0
        return max(0.0, min(1.0, (max(bbox.get("size") or [diag])) / ow))
    if dist < 1e-6:
        return 1.0
    fl = float(cam_meta.get("focal_length") or 35.0)
    h_ap = float(cam_meta.get("film_aperture_h") or 1.417)
    h_mm = h_ap * 25.4
    hfov = 2.0 * math.atan((h_mm * 0.5) / max(fl, 1e-3))
    angular = 2.0 * math.atan(radius / dist)
    if hfov <= 1e-6:
        return None
    return max(0.0, min(1.0, angular / hfov))


def _coverage_warning(coverage: Optional[float]) -> str:
    if coverage is None:
        return ""
    if coverage < _LOW_COVERAGE:
        return (
            f"主体偏小（估计占画面 {coverage:.0%}），透视距离可能过大；"
            "可减小机位距离或只对目标物体取景"
        )
    return ""


def _persp_fit_distance(bbox: Dict[str, Any], shape: str, margin: float) -> float:
    """Distance so the bbox bounding-sphere fills the perspective FOV."""
    c = _cmds()
    radius = 0.5 * max(float(bbox.get("diagonal") or 1.0), 1.0)
    fl = 35.0
    h_ap = 1.417
    try:
        if c.attributeQuery("focalLength", node=shape, exists=True):
            fl = float(c.getAttr(f"{shape}.focalLength") or 35.0)
        if c.attributeQuery("horizontalFilmAperture", node=shape, exists=True):
            h_ap = float(c.getAttr(f"{shape}.horizontalFilmAperture") or 1.417)
    except Exception:
        pass
    hfov = 2.0 * math.atan((h_ap * 25.4 * 0.5) / max(fl, 1e-3))
    half = max(hfov * 0.5, 1e-4)
    dist = radius / math.sin(half)
    return max(dist * (1.0 + max(margin, 0.0)), radius * 1.2)


def _ensure_far_clip_covers(
    camera: str,
    bbox: Optional[Dict[str, Any]],
    *,
    margin: float = 1.5,
) -> Optional[float]:
    """Expand far clip if needed; return previous far clip or None."""
    c = _cmds()
    shape = _camera_shape(camera)
    if not shape or not bbox:
        return None
    try:
        prev = float(c.getAttr(f"{shape}.farClipPlane"))
        pos = c.xform(camera, q=True, ws=True, t=True)
        center = bbox["center"]
        diag = float(bbox.get("diagonal") or 1.0)
        dist = math.sqrt(
            (pos[0] - center[0]) ** 2
            + (pos[1] - center[1]) ** 2
            + (pos[2] - center[2]) ** 2
        )
        need = max((dist + diag) * margin, diag * 2.0, 10.0)
        if need > prev:
            if c.getAttr(f"{shape}.farClipPlane", lock=True):
                c.setAttr(f"{shape}.farClipPlane", lock=False)
            c.setAttr(f"{shape}.farClipPlane", need)
            return prev
    except Exception as e:
        log.debug("far clip adjust skipped: %s", e)
    return None


# ---------------------------------------------------------------------------
# Look-at / framed multi-view cameras
# ---------------------------------------------------------------------------


def _aim_camera(
    camera: str,
    eye: Sequence[float],
    target: Sequence[float],
    up: Sequence[float] = (0.0, 1.0, 0.0),
) -> None:
    c = _cmds()
    c.xform(camera, ws=True, translation=list(eye))
    loc = c.spaceLocator(name="MayaAgent_aim_loc")[0]
    try:
        c.xform(loc, ws=True, translation=list(target))
        # Choose stable world-up for near-vertical looks
        up_vec = list(up)
        world_up = up_vec
        aim = [
            target[0] - eye[0],
            target[1] - eye[1],
            target[2] - eye[2],
        ]
        if abs(aim[1]) > abs(aim[0]) and abs(aim[1]) > abs(aim[2]):
            world_up = [0.0, 0.0, 1.0]
        cons = c.aimConstraint(
            loc,
            camera,
            aimVector=(0, 0, -1),
            upVector=(0, 1, 0),
            worldUpType="vector",
            worldUpVector=world_up,
        )
        if cons:
            c.delete(cons)
    finally:
        if c.objExists(loc):
            c.delete(loc)


def _apply_camera_pose(
    camera: str,
    *,
    eye: Optional[Sequence[float]] = None,
    look_at: Optional[Sequence[float]] = None,
    up: Optional[Sequence[float]] = None,
    focal_length: Optional[float] = None,
) -> None:
    c = _cmds()
    if eye is not None and look_at is not None:
        _aim_camera(camera, eye, look_at, up or (0.0, 1.0, 0.0))
    elif eye is not None:
        c.xform(camera, ws=True, translation=list(eye))
    if focal_length is not None:
        shape = _camera_shape(camera)
        if shape and c.attributeQuery("focalLength", node=shape, exists=True):
            if c.getAttr(f"{shape}.focalLength", lock=True):
                c.setAttr(f"{shape}.focalLength", lock=False)
            c.setAttr(f"{shape}.focalLength", float(focal_length))


def _ortho_width_for_view(
    view: str,
    bbox: Dict[str, Any],
    aspect: float,
    margin: float,
) -> float:
    sx, sy, sz = bbox["size"]
    key = view if view in _VIEW_EYE_OFFSET else "persp"
    # Horizontal / vertical scene extents in the camera image plane
    if key in ("front", "back"):
        horiz, vert = sx, sy
    elif key in ("side", "right", "left"):
        horiz, vert = sz, sy
    elif key in ("top", "bottom"):
        horiz, vert = sx, sz
    else:
        horiz = vert = max(sx, sy, sz)
    # Fit both axes into the film (width is orthographicWidth = horizontal FOV size)
    width_for_vert = vert * max(aspect, 0.1)
    return max(horiz, width_for_vert, 0.1) * (1.0 + max(margin, 0.0))


def _create_framed_view_camera(
    view: str,
    bbox: Dict[str, Any],
    *,
    aspect: float,
    margin: float = 0.08,
) -> str:
    """Always create a temporary camera framed to ``bbox`` for reliable multi-view."""
    c = _cmds()
    key = view if view in _VIEW_EYE_OFFSET else "persp"
    ox, oy, oz = _VIEW_EYE_OFFSET[key]
    length = math.sqrt(ox * ox + oy * oy + oz * oz) or 1.0
    ox, oy, oz = ox / length, oy / length, oz / length
    center = bbox["center"]
    diag = max(float(bbox.get("diagonal") or 1.0), 1.0)
    cam_nodes = c.camera(name=f"MayaAgent_{key}_cam")
    cam = cam_nodes[0] if isinstance(cam_nodes, (list, tuple)) else cam_nodes
    shape = _camera_shape(cam)
    if key == "persp":
        try:
            c.setAttr(f"{shape}.focalLength", 35.0)
        except Exception:
            pass
        dist = _persp_fit_distance(bbox, shape, margin) if shape else diag * 1.6
    else:
        dist = diag * 2.0
    eye = (
        center[0] + ox * dist,
        center[1] + oy * dist,
        center[2] + oz * dist,
    )
    _aim_camera(cam, eye, center)
    far = dist + diag * 2.0
    near = max(0.01, dist * 0.001)
    if shape:
        try:
            c.setAttr(f"{shape}.nearClipPlane", near)
            c.setAttr(f"{shape}.farClipPlane", far)
        except Exception:
            pass
        if key != "persp":
            width = _ortho_width_for_view(key, bbox, aspect, margin)
            try:
                c.setAttr(f"{shape}.orthographic", 1)
                c.setAttr(f"{shape}.orthographicWidth", width)
            except Exception:
                pass
    return cam


def _normalize_views(views: Optional[List[str]], max_n: int) -> List[str]:
    raw = [str(v).strip().lower() for v in (views or []) if str(v).strip()]
    if not raw:
        raw = list(_DEFAULT_MULTI_VIEWS)
    alias_map = {"right": "side"}
    out: List[str] = []
    seen = set()
    for v in raw:
        v = alias_map.get(v, v)
        if v in seen:
            continue
        if v not in _VIEW_EYE_OFFSET and v not in _VIEW_CAMERA_ALIASES:
            continue
        seen.add(v)
        out.append(v)
        if len(out) >= max_n:
            break
    return out


def _maybe_frame(
    panel: str,
    names: Optional[List[str]],
    frame_selection: bool,
    *,
    fit_scene_if_empty: bool = True,
) -> Tuple[Optional[list], Callable[[], None], bool]:
    """
    Returns (framed_targets, restore_fn, did_frame).
    When no explicit targets and frame_selection, fits current selection;
    if still empty and fit_scene_if_empty, fits whole scene.
    """
    c = _cmds()
    prev_sel = c.ls(selection=True, long=True) or []
    targets = _resolve_frame_targets(names, frame_selection)
    did_frame = False

    def _restore():
        try:
            if prev_sel:
                c.select(prev_sel, replace=True)
            else:
                c.select(clear=True)
        except Exception:
            pass

    if not targets:
        if not (frame_selection and fit_scene_if_empty):
            return None, (lambda: None), False
        # Fit all geometry
        try:
            _focus_model_panel(panel)
            c.viewFit(animate=False)
            did_frame = True
        except Exception:
            pass
        return [], _restore if did_frame else (lambda: None), did_frame

    try:
        c.select(targets, replace=True)
        _focus_model_panel(panel)
        c.viewFit(targets, animate=False)
        did_frame = True
    except Exception as e:
        _restore()
        raise RuntimeError(f"取景失败: {e}") from e
    return targets, _restore, did_frame


_DISPLAY_MODE_MAP = {
    "smooth": "smoothShaded",
    "smoothshaded": "smoothShaded",
    "shaded": "smoothShaded",
    "wireframe": "wireframe",
    "wire": "wireframe",
    "flat": "flatShaded",
    "flatshaded": "flatShaded",
    "boundingbox": "boundingBox",
    "points": "points",
}


def _apply_viewport_display(
    panel: str,
    *,
    display_mode: str = "",
    show_only: Optional[List[str]] = None,
    shadows: Optional[bool] = None,
    hide_joints: bool = False,
    hide_controls: bool = False,
    mesh_only: bool = False,
) -> Callable[[], None]:
    """Temporarily change display appearance / isolate / shadows; returns restore fn."""
    c = _cmds()
    restore_editor: List[Tuple[str, Any]] = []
    prev_sel = c.ls(selection=True, long=True) or []
    isolate_on = False
    vis_restore: List[Tuple[str, bool]] = []

    overlay_off: List[str] = []
    if mesh_only:
        overlay_off = list(_MODEL_EDITOR_OVERLAYS)
    else:
        if hide_joints:
            overlay_off.extend(["joints", "ikHandles"])
        if hide_controls:
            overlay_off.extend(["nurbsCurves", "cv", "hulls", "locators", "manipulators"])
    for flag in dict.fromkeys(overlay_off):
        try:
            prev = c.modelEditor(panel, query=True, **{flag: True})
            c.modelEditor(panel, edit=True, **{flag: False})
            restore_editor.append((flag, prev))
        except Exception as e:
            log.debug("modelEditor %s skip: %s", flag, e)

    if display_mode:
        mode = _DISPLAY_MODE_MAP.get(str(display_mode).lower(), str(display_mode))
        try:
            prev = c.modelEditor(panel, query=True, displayAppearance=True)
            c.modelEditor(panel, edit=True, displayAppearance=mode)
            restore_editor.append(("displayAppearance", prev))
        except Exception as e:
            log.debug("displayAppearance skip: %s", e)

    if shadows is not None:
        try:
            prev = c.modelEditor(panel, query=True, shadows=True)
            c.modelEditor(panel, edit=True, shadows=bool(shadows))
            restore_editor.append(("shadows", prev))
        except Exception as e:
            log.debug("shadows skip: %s", e)

    only = [n for n in (show_only or []) if n and c.objExists(n)]
    if only:
        try:
            c.select(only, replace=True)
            c.isolateSelect(panel, state=1)
            isolate_on = True
        except Exception:
            # Fallback: hide other mesh transforms
            try:
                keep = set()
                for n in only:
                    keep.add(n)
                    for d in c.listRelatives(n, allDescendents=True, fullPath=True) or []:
                        keep.add(d)
                for mesh in c.ls(type="mesh", long=True) or []:
                    parents = c.listRelatives(mesh, parent=True, fullPath=True) or []
                    tr = parents[0] if parents else mesh
                    if tr in keep or any(tr.startswith(k + "|") or k.startswith(tr) for k in keep):
                        continue
                    try:
                        vis = bool(c.getAttr(f"{tr}.visibility"))
                        if vis:
                            c.setAttr(f"{tr}.visibility", 0)
                            vis_restore.append((tr, True))
                    except Exception:
                        pass
            except Exception as e:
                log.debug("show_only fallback failed: %s", e)

    def _restore() -> None:
        if isolate_on:
            try:
                c.isolateSelect(panel, state=0)
            except Exception:
                pass
        for node, vis in vis_restore:
            try:
                if c.objExists(node):
                    c.setAttr(f"{node}.visibility", 1 if vis else 0)
            except Exception:
                pass
        for key, val in restore_editor:
            try:
                c.modelEditor(panel, edit=True, **{key: val})
            except Exception:
                pass
        try:
            if prev_sel:
                c.select(prev_sel, replace=True)
            else:
                c.select(clear=True)
        except Exception:
            pass

    return _restore


def _finish_capture(
    *,
    image_path: str,
    attachment_name: str,
    panel: str,
    camera: str,
    width: int,
    height: int,
    method: str,
    framed: Optional[List[str]],
    did_frame: bool,
    note: str,
    extra: Optional[Dict[str, Any]] = None,
) -> ToolResult:
    try:
        attachment = attachment_from_raw_file(image_path)
        attachment.name = attachment.name or attachment_name
    except Exception as e:
        return ToolResult(ok=False, error=f"截图编码失败: {e}")
    finally:
        emptiness = _analyze_image_emptiness(image_path)
        _cleanup_capture(image_path)

    bbox = _world_bbox(framed if framed else None)
    extra = extra or {}
    cam_meta = extra.pop("camera_meta_at_capture", None) or _camera_meta(camera)
    warnings: List[str] = []
    if emptiness.get("mostly_empty"):
        warnings.append(
            "画面几乎无内容（像素方差过低），可能被裁剪面裁掉或相机未对准场景"
        )
    clip_w = _clip_warning(cam_meta, bbox)
    if clip_w:
        warnings.append(clip_w)
    coverage = _subject_coverage(cam_meta, bbox)
    cov_w = _coverage_warning(coverage)
    if cov_w:
        warnings.append(cov_w)
    if isinstance(emptiness, dict) and coverage is not None:
        emptiness = dict(emptiness)
        emptiness["subject_coverage"] = round(coverage, 3)

    data: Dict[str, Any] = {
        "panel": panel,
        "camera": camera,
        "width": width,
        "height": height,
        "method": method,
        "framed": framed or [],
        "did_frame": bool(did_frame),
        "camera_meta": cam_meta,
        "scene_bbox": bbox,
        "image_stats": emptiness,
        "warnings": warnings,
    }
    if extra:
        data.update(extra)
    for item in data.get("ignored") or []:
        text = str(item)
        if text and text not in warnings:
            warnings.append(text)
    data["warnings"] = warnings

    msg = "视口截图已完成"
    if note:
        msg = f"{msg}：{note}"
    if warnings:
        msg = f"{msg} ⚠ " + "；".join(warnings)

    return ToolResult(
        ok=True,
        data=data,
        message=msg,
        images=[attachment],
    )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool(
    name="capture_viewport",
    description=(
        "截取当前 Maya 模型视口（单视角）。"
        "机位优先级：camera_position/look_at 一定生效，此时不会再 viewFit（避免覆盖机位）；"
        "frame_objects 在显式机位下只用于 bbox/远裁剪。"
        "hide_joints / hide_controls / mesh_only 可关掉骨骼与控制器叠加（形变 QC 建议 mesh_only=true）。"
        "返回 camera_meta（截图当时）、requested/applied 机位、subject_coverage；被忽略的参数会进 warnings。"
    ),
    parameters=obj_schema(
        {
            "width": {"type": "integer", "default": _DEFAULT_W},
            "height": {"type": "integer", "default": _DEFAULT_H},
            "camera": {
                "type": "string",
                "default": "",
                "description": "可选相机名；空则用当前视口相机",
            },
            "panel": {"type": "string", "default": ""},
            "frame_objects": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": "截图前对这些物体取景",
            },
            "frame_selection": {
                "type": "boolean",
                "default": True,
                "description": "未指定 frame_objects 时：对当前选择取景；无选择则取景整场景",
            },
            "show_only": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": "只显示这些对象/组（isolate）；空则显示全部",
            },
            "display_mode": {
                "type": "string",
                "default": "",
                "description": "smoothShaded / wireframe / flatShaded；空则保持当前",
            },
            "shadows": {
                "type": "boolean",
                "description": "可选：视口阴影开关",
            },
            "camera_position": {
                "type": "array",
                "items": {"type": "number"},
                "description": "可选世界坐标眼点 [x,y,z]；需配合 look_at",
            },
            "look_at": {
                "type": "array",
                "items": {"type": "number"},
                "description": "可选世界坐标看向点 [x,y,z]",
            },
            "up_vector": {
                "type": "array",
                "items": {"type": "number"},
                "default": [0, 1, 0],
                "description": "look_at 时的上方向",
            },
            "focal_length": {
                "type": "number",
                "description": "可选焦距（mm）",
            },
            "margin": {
                "type": "number",
                "default": 0.08,
                "description": "取景余量（相对），默认 0.08",
            },
            "auto_extend_far_clip": {
                "type": "boolean",
                "default": True,
                "description": "若场景超出 farClip 则临时扩大远裁剪面（截完恢复）",
            },
            "show_ornaments": {"type": "boolean", "default": False},
            "hide_joints": {
                "type": "boolean",
                "default": True,
                "description": "截图时隐藏关节显示（不影响场景，截完恢复）",
            },
            "hide_controls": {
                "type": "boolean",
                "default": True,
                "description": "截图时隐藏曲线控制器/locator",
            },
            "mesh_only": {
                "type": "boolean",
                "default": False,
                "description": "只显示网格：关掉关节、IK、曲线、灯光等视口叠加",
            },
            "note": {"type": "string", "default": ""},
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
    frame_selection: bool = True,
    show_only: Optional[List[str]] = None,
    display_mode: str = "",
    shadows: Optional[bool] = None,
    camera_position: Optional[List[float]] = None,
    look_at: Optional[List[float]] = None,
    up_vector: Optional[List[float]] = None,
    focal_length: Optional[float] = None,
    margin: float = 0.08,
    auto_extend_far_clip: bool = True,
    show_ornaments: bool = False,
    hide_joints: bool = True,
    hide_controls: bool = True,
    mesh_only: bool = False,
    note: str = "",
) -> ToolResult:
    c = _cmds()
    width = max(320, min(int(width or _DEFAULT_W), 1920))
    height = max(240, min(int(height or _DEFAULT_H), 1080))
    panel_name = _resolve_model_panel(panel or "")

    pose_requested = camera_position is not None or look_at is not None or focal_length is not None
    temp_cam = ""
    prev_far = None
    cam_name = (camera or "").strip()

    # If pose without camera, create a temporary persp camera
    if pose_requested and not cam_name:
        nodes = c.camera(name="MayaAgent_shot_cam")
        temp_cam = nodes[0] if isinstance(nodes, (list, tuple)) else nodes
        cam_name = temp_cam

    _prev_cam, restore_cam = _with_camera(panel_name, cam_name)
    del _prev_cam

    # Apply explicit pose on the active camera
    active_cam = cam_name
    if not active_cam:
        try:
            active_cam = c.modelEditor(panel_name, query=True, camera=True) or ""
        except Exception:
            active_cam = ""

    restore_pose_fn: Optional[Callable[[], None]] = None
    if active_cam and pose_requested:
        # Save prior transform / focal to restore when using existing camera
        saved = {
            "t": c.xform(active_cam, q=True, ws=True, t=True),
            "ro": c.xform(active_cam, q=True, ws=True, ro=True),
        }
        shape = _camera_shape(active_cam)
        if shape and c.attributeQuery("focalLength", node=shape, exists=True):
            saved["focal"] = c.getAttr(f"{shape}.focalLength")

        eye = camera_position
        target = look_at
        if eye is None and target is not None:
            eye = saved["t"]
        if target is None and eye is not None:
            bb = _world_bbox(_resolve_frame_targets(frame_objects, frame_selection))
            target = (bb or {}).get("center") or [0, 0, 0]
        _apply_camera_pose(
            active_cam,
            eye=eye,
            look_at=target,
            up=up_vector or [0, 1, 0],
            focal_length=focal_length,
        )

        def _restore_pose() -> None:
            try:
                c.xform(active_cam, ws=True, translation=saved["t"])
                c.xform(active_cam, ws=True, rotation=saved["ro"])
                if "focal" in saved and shape:
                    c.setAttr(f"{shape}.focalLength", saved["focal"])
            except Exception:
                pass

        # Temp cameras are deleted; only restore existing cameras
        if not temp_cam:
            restore_pose_fn = _restore_pose

    framed, restore_sel, did_frame = None, (lambda: None), False
    if pose_requested:
        # Explicit eye/look_at wins; do not viewFit (would override aim).
        framed = _resolve_frame_targets(frame_objects, frame_selection)
        did_frame = True
    else:
        framed, restore_sel, did_frame = _maybe_frame(
            panel_name,
            frame_objects,
            bool(frame_selection),
            fit_scene_if_empty=True,
        )
    # margin is used by multi-view ortho framing; single-view relies on viewFit + far-clip.
    _ = margin

    bbox_targets = framed if framed else _resolve_frame_targets(frame_objects, frame_selection)
    bbox = _world_bbox(bbox_targets if bbox_targets else None)
    if auto_extend_far_clip and active_cam:
        prev_far = _ensure_far_clip_covers(active_cam, bbox)

    restore_display = _apply_viewport_display(
        panel_name,
        display_mode=display_mode or "",
        show_only=show_only,
        shadows=shadows,
        hide_joints=hide_joints,
        hide_controls=hide_controls,
        mesh_only=mesh_only,
    )

    image_path = ""
    capture_method = "playblast"
    shot_meta: Dict[str, Any] = {}
    try:
        image_path, capture_method = _capture_panel_image(
            panel_name, width, height, show_ornaments=show_ornaments
        )
        shot_meta = _camera_meta(active_cam)
    finally:
        restore_display()
        restore_sel()
        if restore_pose_fn:
            restore_pose_fn()
        if prev_far is not None and active_cam:
            shape = _camera_shape(active_cam)
            try:
                if shape:
                    c.setAttr(f"{shape}.farClipPlane", prev_far)
            except Exception:
                pass
        restore_cam()
        if temp_cam and c.objExists(temp_cam):
            try:
                c.delete(temp_cam)
            except Exception:
                pass

    ignored: List[str] = []
    framing_mode = "explicit_pose" if pose_requested else ("viewFit" if did_frame else "none")
    if pose_requested and (frame_objects or frame_selection):
        ignored.append(
            "frame_objects/viewFit：显式 camera_position/look_at 优先，未执行 viewFit，"
            "以免覆盖机位；frame_objects 仅用于 bbox/远裁剪"
        )

    return _finish_capture(
        image_path=image_path,
        attachment_name="viewport.jpg",
        panel=panel_name,
        camera=shot_meta.get("camera") or active_cam or "",
        width=width,
        height=height,
        method=capture_method,
        framed=list(framed or []),
        did_frame=did_frame or bool(pose_requested),
        note=note,
        extra={
            "temporary_camera": bool(temp_cam),
            "temporary_cameras_cleaned": True,
            "show_only": list(show_only or []),
            "display_mode": display_mode or "",
            "shadows": shadows,
            "hide_joints": hide_joints,
            "hide_controls": hide_controls,
            "mesh_only": mesh_only,
            "framing_mode": framing_mode,
            "requested": {
                "camera_position": list(camera_position) if camera_position is not None else None,
                "look_at": list(look_at) if look_at is not None else None,
                "focal_length": focal_length,
                "frame_objects": list(frame_objects or []),
            },
            "applied": {
                "pose_applied": bool(pose_requested and active_cam),
                "skipped_viewFit": bool(pose_requested),
            },
            "ignored": ignored,
            "camera_meta_at_capture": shot_meta,
        },
    )


@tool(
    name="capture_viewport_views",
    description=(
        "多视角截图（默认透视+前+侧+顶，最多 4 张）。"
        "透视相机按 bbox 球径与焦距反算距离，避免主体过小；"
        "image_stats.subject_coverage 低于约 22% 会 warning。"
        "hide_joints 默认开；形变 QC 可用 mesh_only=true。"
        "截图结束后自动删除临时相机（temporary_cameras_cleaned=true）。"
    ),
    parameters=obj_schema(
        {
            "views": {
                "type": "array",
                "items": {"type": "string"},
                "default": list(_DEFAULT_MULTI_VIEWS),
                "description": f"视角列表，最多 {MAX_IMAGES} 个",
            },
            "width": {"type": "integer", "default": _MULTI_W},
            "height": {"type": "integer", "default": _MULTI_H},
            "panel": {"type": "string", "default": ""},
            "frame_objects": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
            },
            "frame_selection": {
                "type": "boolean",
                "default": True,
                "description": "与 capture_viewport 一致：无 frame_objects 时对选择取景，无选择则取景整场景",
            },
            "show_only": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": "只显示这些对象/组",
            },
            "display_mode": {
                "type": "string",
                "default": "",
                "description": "smoothShaded / wireframe / flatShaded",
            },
            "shadows": {"type": "boolean"},
            "margin": {
                "type": "number",
                "default": 0.1,
                "description": "取景余量，默认 0.1（约 10%）",
            },
            "show_ornaments": {"type": "boolean", "default": False},
            "hide_joints": {"type": "boolean", "default": True},
            "hide_controls": {"type": "boolean", "default": True},
            "mesh_only": {"type": "boolean", "default": False},
            "note": {"type": "string", "default": ""},
        }
    ),
    category="scene",
    requires_vision=True,
)
def capture_viewport_views(
    views: Optional[List[str]] = None,
    width: int = _MULTI_W,
    height: int = _MULTI_H,
    panel: str = "",
    frame_objects: Optional[List[str]] = None,
    frame_selection: bool = True,
    show_only: Optional[List[str]] = None,
    display_mode: str = "",
    shadows: Optional[bool] = None,
    margin: float = 0.1,
    show_ornaments: bool = False,
    hide_joints: bool = True,
    hide_controls: bool = True,
    mesh_only: bool = False,
    note: str = "",
) -> ToolResult:
    c = _cmds()
    width = max(320, min(int(width or _MULTI_W), 1600))
    height = max(240, min(int(height or _MULTI_H), 1200))
    aspect = float(width) / float(max(height, 1))
    view_list = _normalize_views(views, MAX_IMAGES)
    if not view_list:
        return ToolResult(ok=False, error="未指定有效视角")

    panel_name = _resolve_model_panel(panel or "")
    try:
        prev_cam = c.modelEditor(panel_name, query=True, camera=True) or ""
    except Exception:
        prev_cam = ""

    frame_targets = _resolve_frame_targets(frame_objects, frame_selection)
    bbox = _world_bbox(frame_targets if frame_targets else None)
    if not bbox:
        return ToolResult(ok=False, error="场景中没有可取景的几何体")

    attachments: List[ImageAttachment] = []
    captured: List[Dict[str, Any]] = []
    errors: List[str] = []
    warnings_all: List[str] = []
    temp_cams: List[str] = []
    cleaned = False
    prev_sel = c.ls(selection=True, long=True) or []
    restore_display = _apply_viewport_display(
        panel_name,
        display_mode=display_mode or "",
        show_only=show_only,
        shadows=shadows,
        hide_joints=hide_joints,
        hide_controls=hide_controls,
        mesh_only=mesh_only,
    )

    def _restore_selection():
        try:
            if prev_sel:
                c.select(prev_sel, replace=True)
            else:
                c.select(clear=True)
        except Exception:
            pass

    try:
        for view in view_list:
            image_path = ""
            cam = ""
            try:
                cam = _create_framed_view_camera(
                    view, bbox, aspect=aspect, margin=float(margin or 0.1)
                )
                temp_cams.append(cam)
                _set_panel_camera(panel_name, cam)
                _focus_model_panel(panel_name)

                image_path, method = _capture_panel_image(
                    panel_name, width, height, show_ornaments=show_ornaments
                )
                att = attachment_from_raw_file(image_path)
                att.name = f"viewport_{view}.jpg"
                emptiness = _analyze_image_emptiness(image_path)
                cam_meta = _camera_meta(cam)
                view_warnings: List[str] = []
                if emptiness.get("mostly_empty"):
                    view_warnings.append(f"{view}: 画面几乎无内容")
                clip_w = _clip_warning(cam_meta, bbox)
                if clip_w:
                    view_warnings.append(f"{view}: {clip_w}")
                coverage = _subject_coverage(cam_meta, bbox)
                cov_w = _coverage_warning(coverage)
                if cov_w:
                    view_warnings.append(f"{view}: {cov_w}")
                if coverage is not None:
                    emptiness["subject_coverage"] = round(coverage, 3)
                warnings_all.extend(view_warnings)
                attachments.append(att)
                captured.append(
                    {
                        "view": view,
                        "camera": cam,
                        "temporary_camera": True,
                        "method": method,
                        "name": att.name,
                        "did_frame": True,
                        "camera_meta": cam_meta,
                        "image_stats": emptiness,
                        "warnings": view_warnings,
                    }
                )
            except Exception as e:
                log.warning("capture view %s failed: %s", view, e)
                errors.append(f"{view}: {e}")
            finally:
                _cleanup_capture(image_path)
    finally:
        restore_display()
        _restore_selection()
        try:
            if prev_cam:
                _set_panel_camera(panel_name, prev_cam)
        except Exception:
            pass
        leftover = []
        for cam in temp_cams:
            try:
                if c.objExists(cam):
                    c.delete(cam)
                if c.objExists(cam):
                    leftover.append(cam)
            except Exception:
                leftover.append(cam)
        cleaned = len(leftover) == 0

    if not attachments:
        detail = "；".join(errors) if errors else "未知错误"
        return ToolResult(ok=False, error=f"多视角截图失败：{detail}")

    # Strip deleted camera names from payload clarity
    for item in captured:
        item["camera_deleted"] = cleaned

    msg = f"已截取 {len(attachments)} 个视角：{', '.join(x['view'] for x in captured)}"
    if note:
        msg = f"{msg}（{note}）"
    if cleaned:
        msg = f"{msg}；临时相机已清理"
    if errors:
        msg = f"{msg}；部分失败：{'；'.join(errors)}"
    if warnings_all:
        msg = f"{msg} ⚠ " + "；".join(warnings_all)

    return ToolResult(
        ok=True,
        data={
            "panel": panel_name,
            "width": width,
            "height": height,
            "views": captured,
            "framed": frame_targets or [],
            "did_frame": True,
            "scene_bbox": bbox,
            "margin": margin,
            "show_only": list(show_only or []),
            "display_mode": display_mode or "",
            "shadows": shadows,
            "hide_joints": hide_joints,
            "hide_controls": hide_controls,
            "mesh_only": mesh_only,
            "temporary_cameras_cleaned": cleaned,
            "errors": errors,
            "warnings": warnings_all,
        },
        message=msg,
        images=attachments,
    )

@tool(
    name="render_still",
    description=(
        "渲染单帧到图片文件（展示图）。renderer=hardware 用高质量视口抓图；"
        "mayaSoftware 用软件渲染；arnold 在已加载 mtoa 时可用。"
        "可指定相机与分辨率；成功时附带图像供视觉分析。"
    ),
    parameters=obj_schema(
        {
            "file_path": {
                "type": "string",
                "default": "",
                "description": "输出路径；空则写临时 jpg",
            },
            "width": {"type": "integer", "default": 1920},
            "height": {"type": "integer", "default": 1080},
            "camera": {
                "type": "string",
                "default": "",
                "description": "相机名；空则当前视口相机",
            },
            "renderer": {
                "type": "string",
                "enum": ["hardware", "mayaSoftware", "arnold"],
                "default": "hardware",
            },
            "show_only": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
            },
            "display_mode": {"type": "string", "default": "smoothShaded"},
            "shadows": {"type": "boolean", "default": True},
            "note": {"type": "string", "default": ""},
        }
    ),
    category="scene",
    requires_vision=True,
)
def render_still(
    file_path: str = "",
    width: int = 1920,
    height: int = 1080,
    camera: str = "",
    renderer: str = "hardware",
    show_only: Optional[List[str]] = None,
    display_mode: str = "smoothShaded",
    shadows: bool = True,
    note: str = "",
) -> ToolResult:
    c = _cmds()
    width = max(320, min(int(width or 1920), 4096))
    height = max(240, min(int(height or 1080), 4096))
    renderer = (renderer or "hardware").strip()
    panel_name = _resolve_model_panel("")
    cam = (camera or "").strip()
    if not cam:
        try:
            cam = c.modelEditor(panel_name, query=True, camera=True) or ""
        except Exception:
            cam = "persp"

    out_path = (file_path or "").replace("\\", "/")
    temp_out = False
    if not out_path:
        tmp = tempfile.NamedTemporaryFile(
            prefix="mayaagent_render_",
            suffix=".jpg",
            delete=False,
            dir=_viewport_temp_dir(),
        )
        tmp.close()
        out_path = tmp.name.replace("\\", "/")
        temp_out = True
    else:
        parent = os.path.dirname(out_path)
        if parent and not os.path.isdir(parent):
            try:
                os.makedirs(parent, exist_ok=True)
            except Exception as e:
                return ToolResult(ok=False, error=f"无法创建输出目录: {e}")

    restore_cam = (lambda: None)
    prev_cam = ""
    if cam:
        prev_cam, restore_cam = _with_camera(panel_name, cam)

    restore_display = _apply_viewport_display(
        panel_name,
        display_mode=display_mode or "smoothShaded",
        show_only=show_only,
        shadows=shadows,
    )

    method = renderer
    image_path = ""
    try:
        if renderer == "hardware":
            image_path, method = _capture_panel_image(
                panel_name, width, height, show_ornaments=False
            )
            # Copy/move to requested path
            if os.path.abspath(image_path) != os.path.abspath(out_path):
                import shutil

                shutil.copy2(image_path, out_path)
                _cleanup_capture(image_path)
                image_path = out_path
            method = "hardware_playblast"
        elif renderer == "arnold":
            try:
                c.loadPlugin("mtoa", quiet=True)
            except Exception:
                pass
            try:
                # Set output via render globals then arnoldRender / render
                prefix = out_path.rsplit(".", 1)[0]
                c.setAttr(
                    "defaultRenderGlobals.currentRenderer", "arnold", type="string"
                )
                c.setAttr("defaultResolution.width", width)
                c.setAttr("defaultResolution.height", height)
                c.setAttr(
                    "defaultRenderGlobals.imageFilePrefix", prefix, type="string"
                )
                if hasattr(c, "arnoldRender"):
                    c.arnoldRender(camera=cam, width=width, height=height)
                else:
                    c.render(cam, x=width, y=height)
                # Locate produced file near prefix
                import glob as _glob

                candidates = _glob.glob(prefix + ".*") + _glob.glob(prefix + "*.*")
                candidates = [
                    p
                    for p in candidates
                    if p.lower().endswith((".jpg", ".jpeg", ".png", ".exr", ".tif", ".tiff"))
                ]
                if candidates:
                    candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
                    import shutil

                    if os.path.abspath(candidates[0]) != os.path.abspath(out_path):
                        shutil.copy2(candidates[0], out_path)
                    image_path = out_path
                    method = "arnold"
                else:
                    raise RuntimeError("Arnold 未找到输出文件")
            except Exception as e:
                log.warning("Arnold still render fallback: %s", e)
                image_path, method = _capture_panel_image(
                    panel_name, width, height, show_ornaments=False
                )
                import shutil

                shutil.copy2(image_path, out_path)
                _cleanup_capture(image_path)
                image_path = out_path
                method = "hardware_fallback_from_arnold"
        else:
            # mayaSoftware
            try:
                c.setAttr("defaultRenderGlobals.currentRenderer", "mayaSoftware", type="string")
            except Exception:
                pass
            try:
                c.setAttr("defaultResolution.width", width)
                c.setAttr("defaultResolution.height", height)
                c.setAttr("defaultRenderGlobals.imageFilePrefix", out_path.rsplit(".", 1)[0], type="string")
            except Exception:
                pass
            try:
                rendered = c.render(cam, x=width, y=height)
                if isinstance(rendered, str) and os.path.isfile(rendered):
                    import shutil

                    shutil.copy2(rendered, out_path)
                    image_path = out_path
                    method = "mayaSoftware"
                else:
                    raise RuntimeError(f"render 未返回文件: {rendered}")
            except Exception as e:
                log.warning("mayaSoftware render failed, hardware fallback: %s", e)
                image_path, method = _capture_panel_image(
                    panel_name, width, height, show_ornaments=False
                )
                import shutil

                shutil.copy2(image_path, out_path)
                _cleanup_capture(image_path)
                image_path = out_path
                method = "hardware_fallback_from_software"
    finally:
        restore_display()
        restore_cam()

    if not image_path or not os.path.isfile(image_path):
        return ToolResult(ok=False, error="渲染未生成图像文件")

    try:
        attachment = attachment_from_raw_file(image_path)
        attachment.name = os.path.basename(out_path) or "render.jpg"
    except Exception as e:
        return ToolResult(ok=False, error=f"图像编码失败: {e}")

    size = os.path.getsize(image_path) if os.path.isfile(image_path) else 0
    msg = f"静帧已渲染: {out_path}（{method}, {width}x{height}"
    if note:
        msg += f", {note}"
    msg += ")"
    return ToolResult(
        ok=True,
        data={
            "path": out_path.replace("\\", "/"),
            "width": width,
            "height": height,
            "camera": cam,
            "renderer": renderer,
            "method": method,
            "size_bytes": size,
            "temporary_file": temp_out,
            "show_only": list(show_only or []),
        },
        message=msg,
        images=[attachment],
    )
