"""Persist chat sessions as sidecar JSON next to Maya scene files."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from maya_agent.core.chat_session import ProjectChatData
from maya_agent.utils.config import user_config_dir
from maya_agent.utils.logger import get_logger
from maya_agent.utils.maya_compat import in_maya

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
    """Untitled scenes: store under user config until first save."""
    base = user_config_dir() / "untitled_sessions"
    base.mkdir(parents=True, exist_ok=True)
    return base / "current.json"


def storage_path(scene_path: Optional[str] = None) -> Path:
    scene_path = scene_path if scene_path is not None else get_maya_scene_path()
    sidecar = sidecar_path_for_scene(scene_path)
    if sidecar:
        return sidecar
    return fallback_path_for_untitled()


def load_project(scene_path: Optional[str] = None) -> ProjectChatData:
    path = storage_path(scene_path)
    scene = scene_path if scene_path is not None else get_maya_scene_path()
    if not path.exists():
        return ProjectChatData(scene_path=scene)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        project = ProjectChatData.from_dict(data)
        project.scene_path = scene or project.scene_path
        return project
    except Exception as e:
        log.warning("load project failed %s: %s", path, e)
        return ProjectChatData(scene_path=scene)


def save_project(project: ProjectChatData, scene_path: Optional[str] = None) -> Path:
    scene = scene_path if scene_path is not None else get_maya_scene_path()
    project.scene_path = scene or project.scene_path
    path = storage_path(scene)
    path.parent.mkdir(parents=True, exist_ok=True)
    from maya_agent.core.chat_session import _now_iso

    project.saved_at = _now_iso()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(project.to_dict(), f, ensure_ascii=False, indent=2)
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
