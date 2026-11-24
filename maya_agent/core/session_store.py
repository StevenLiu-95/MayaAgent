"""Persist chat sessions as sidecar JSON next to Maya scene files."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from maya_agent.core.chat_session import ProjectChatData
from maya_agent.utils.logger import get_logger
from maya_agent.utils.maya_compat import in_maya
from maya_agent.utils.paths import agent_temp_subdir

log = get_logger("maya_agent.session_store")

SIDECAR_SUFFIX = ".mayaagent.json"


def get_maya_scene_path() -> str:
    if not in_maya():
        return ""
    import maya.cmds as cmds

    try:
        path = cmds.file(query=True, sceneName=True) or ""
        return path.replace("\\", "/")
    except Exception:
        return ""


def is_scene_saved() -> bool:
    path = get_maya_scene_path()
    return bool(path) and os.path.isfile(path)


def sidecar_path_for_scene(scene_path: str) -> Optional[Path]:
    if not scene_path:
        return None
    p = Path(scene_path.replace("\\", "/"))
    if not p.name:
        return None
    # Sidecar: scene.ma -> scene.ma.mayaagent.json (travels with project when copied)
    return p.parent / f"{p.name}{SIDECAR_SUFFIX}"


def fallback_path_for_untitled() -> Path:
    """Untitled scenes: store under the agent temp root until first save."""
    return agent_temp_subdir("untitled_sessions") / "current.json"


def storage_path(scene_path: Optional[str] = None) -> Path:
    scene_path = scene_path if scene_path is not None else get_maya_scene_path()
    sidecar = sidecar_path_for_scene(scene_path)
    if sidecar:
        return sidecar
    return fallback_path_for_untitled()


def load_project(scene_path: Optional[str] = None) -> ProjectChatData:
    raw = get_maya_scene_path() if scene_path is None else scene_path
    scene = (raw or "").replace("\\", "/")
    path = storage_path(scene)
    if not path.exists():
        return ProjectChatData(scene_path=scene)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        project = ProjectChatData.from_dict(data)
        project.scene_path = scene
        return project
    except Exception as e:
        log.warning("load project failed %s: %s", path, e)
        return ProjectChatData(scene_path=scene)


def save_project(project: ProjectChatData, scene_path: Optional[str] = None) -> Path:
    """
    Persist ``project`` next to ``scene_path``.

    When ``scene_path`` is explicitly provided (including ""), use it for the
    sidecar location. Only fall back to the live Maya scene name when the
    caller omits the argument — this avoids AfterOpen/AfterNew races where Maya
    has already switched scenes but the in-memory project still belongs to the
    previous file (or untitled buffer).
    """
    if scene_path is None:
        scene = (get_maya_scene_path() or project.scene_path or "").replace("\\", "/")
    else:
        scene = scene_path.replace("\\", "/")
    project.scene_path = scene
    path = storage_path(scene)
    path.parent.mkdir(parents=True, exist_ok=True)
    from maya_agent.core.chat_session import _now_iso

    project.saved_at = _now_iso()
    # Atomic write: a crash mid-write must not truncate the existing sidecar
    # (chat history is the only copy of a session).
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(project.to_dict(), f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    log.info("saved project chats to %s", path)
    return path


def migrate_untitled_to_scene(scene_path: str) -> None:
    """When user saves untitled scene, move fallback data to sidecar."""
    fb = fallback_path_for_untitled()
    if not fb.exists():
        return
    sidecar = sidecar_path_for_scene(scene_path)
    if not sidecar:
        return
    if sidecar.exists():
        # merge: keep sidecar, drop fallback
        try:
            fb.unlink()
        except OSError:
            pass
        return
    try:
        project = load_project("")
        project.scene_path = scene_path.replace("\\", "/")
        save_project(project, scene_path)
        fb.unlink()
        log.info("migrated untitled sessions to %s", sidecar)
    except Exception as e:
        log.warning("migrate untitled failed: %s", e)


def clone_project_to_scene(src_scene_path: str, dst_scene_path: str) -> None:
    """Copy sidecar sessions on 'Save Scene As' when destination has none yet."""
    src_norm = (src_scene_path or "").replace("\\", "/").strip()
    dst_norm = (dst_scene_path or "").replace("\\", "/").strip()
    if not src_norm or not dst_norm or src_norm == dst_norm:
        return
    src_sidecar = sidecar_path_for_scene(src_norm)
    dst_sidecar = sidecar_path_for_scene(dst_norm)
    if not src_sidecar or not dst_sidecar or not src_sidecar.exists():
        return
    if dst_sidecar.exists():
        return
    try:
        project = load_project(src_norm)
        project.scene_path = dst_norm
        save_project(project, dst_norm)
        log.info("cloned project sessions %s -> %s", src_sidecar, dst_sidecar)
    except Exception as e:
        log.warning("clone project on save-as failed: %s", e)

