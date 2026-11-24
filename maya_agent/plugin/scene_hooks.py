"""Maya scene callbacks — reload / persist chat sessions with project files."""

from __future__ import annotations

from maya_agent.utils.logger import get_logger
from maya_agent.utils.maya_compat import in_maya

log = get_logger("maya_agent.scene_hooks")

_CALLBACK_IDS: list = []
_SCRIPT_JOB_IDS: list = []
_INSTALLED = False
_SUPPRESS = 0
_LAST_SCENE_PATH: str = ""


class suppress_scene_hooks:
    """Context manager: ignore scene open/save/new callbacks (checkpoint restore)."""

    def __enter__(self):
        global _SUPPRESS
        _SUPPRESS += 1
        return self

    def __exit__(self, *_exc):
        global _SUPPRESS
        _SUPPRESS = max(0, _SUPPRESS - 1)
        return False


def hooks_suppressed() -> bool:
    return _SUPPRESS > 0


def _current_scene_path() -> str:
    try:
        from maya_agent.core.session_store import get_maya_scene_path

        return (get_maya_scene_path() or "").strip().replace("\\", "/")
    except Exception:
        return ""


def install_scene_hooks() -> None:
    global _INSTALLED, _LAST_SCENE_PATH
    if _INSTALLED or not in_maya():
        return
    _LAST_SCENE_PATH = _current_scene_path()
    try:
        from maya.api.OpenMaya import MSceneMessage

        def _before_switch(*_args):
            _persist_open_window()

        def _after_new(*_args):
            _on_new_scene()

        def _after_open(*_args):
            _on_scene_opened()

        def _after_save(*_args):
            _on_scene_saved()

        _CALLBACK_IDS.append(MSceneMessage.addCallback(MSceneMessage.kBeforeNew, _before_switch))
        _CALLBACK_IDS.append(MSceneMessage.addCallback(MSceneMessage.kAfterNew, _after_new))
        before_open = getattr(MSceneMessage, "kBeforeOpen", None)
        if before_open is not None:
            _CALLBACK_IDS.append(MSceneMessage.addCallback(before_open, _before_switch))
        _CALLBACK_IDS.append(MSceneMessage.addCallback(MSceneMessage.kAfterOpen, _after_open))
        _CALLBACK_IDS.append(MSceneMessage.addCallback(MSceneMessage.kAfterSave, _after_save))
        _INSTALLED = True
        log.info("scene hooks installed (%d callbacks)", len(_CALLBACK_IDS))
    except Exception as e:
        log.warning("scene hooks install failed: %s", e)
        _try_script_job_fallback()


def _try_script_job_fallback() -> None:
    global _INSTALLED
    try:
        import maya.cmds as cmds

        _SCRIPT_JOB_IDS.append(
            cmds.scriptJob(
                event=["SceneOpened", "import maya_agent.plugin.scene_hooks as sh; sh._on_scene_opened()"],
                protected=True,
            )
        )
        _SCRIPT_JOB_IDS.append(
            cmds.scriptJob(
                event=["SceneSaved", "import maya_agent.plugin.scene_hooks as sh; sh._on_scene_saved()"],
                protected=True,
            )
        )
        _SCRIPT_JOB_IDS.append(
            cmds.scriptJob(
                event=["NewSceneOpened", "import maya_agent.plugin.scene_hooks as sh; sh._on_new_scene()"],
                protected=True,
            )
        )
        _INSTALLED = True
        log.info("scene hooks installed via scriptJob")
    except Exception as e:
        log.warning("scriptJob fallback failed: %s", e)


def uninstall_scene_hooks() -> None:
    """Remove registered OpenMaya callbacks / scriptJobs (reload & plug-in unload)."""
    global _INSTALLED, _LAST_SCENE_PATH
    if _CALLBACK_IDS:
        remover = None
        try:
            from maya.api.OpenMaya import MMessage

            remover = MMessage.removeCallback
        except Exception:
            try:
                from maya.api.OpenMaya import MSceneMessage

                remover = getattr(MSceneMessage, "removeCallback", None)
            except Exception:
                remover = None
        if remover is not None:
            for cid in list(_CALLBACK_IDS):
                try:
                    remover(cid)
                except Exception as e:
                    log.debug("removeCallback failed: %s", e)
        _CALLBACK_IDS.clear()

    if _SCRIPT_JOB_IDS:
        try:
            import maya.cmds as cmds

            for jid in list(_SCRIPT_JOB_IDS):
                try:
                    if cmds.scriptJob(exists=jid):
                        cmds.scriptJob(kill=jid, force=True)
                except Exception as e:
                    log.debug("kill scriptJob %s failed: %s", jid, e)
        except Exception:
            pass
        _SCRIPT_JOB_IDS.clear()

    _INSTALLED = False
    _LAST_SCENE_PATH = ""


def _persist_open_window() -> None:
    if hooks_suppressed():
        return
    win = _get_window()
    if win is not None:
        try:
            win.persist_sessions()
        except Exception as e:
            log.debug("persist before scene change: %s", e)


def _reset_headless_fallback_agent() -> None:
    """Clear headless MCP fallback memory when scene changes with no panel open."""
    try:
        from maya_agent.bridge import agent_remote as ar

        if ar._panel_agent is not None or ar._fallback_agent is None:
            return
        lock = ar.agent_lock()
        if lock.acquire(blocking=False):
            try:
                ar._fallback_agent.reset()
            finally:
                lock.release()
    except Exception as e:
        log.debug("reset fallback agent on scene switch: %s", e)


def _handle_scene_switched() -> None:
    global _LAST_SCENE_PATH
    if hooks_suppressed():
        return
    _persist_open_window()
    _LAST_SCENE_PATH = _current_scene_path()
    win = _get_window()
    if win is not None:
        try:
            win.on_scene_changed(reload_only=True, persist_current=False)
        except Exception as e:
            log.warning("scene switch reload failed: %s", e)
    else:
        _reset_headless_fallback_agent()


def _on_new_scene() -> None:
    _handle_scene_switched()


def _on_scene_opened() -> None:
    _handle_scene_switched()


def _on_scene_saved() -> None:
    global _LAST_SCENE_PATH
    if hooks_suppressed():
        return
    from maya_agent.core.session_store import (
        clone_project_to_scene,
        migrate_untitled_to_scene,
    )

    win = _get_window()
    if win is not None and hasattr(win, "sessions"):
        prev_path = (win.sessions.project.scene_path or "").strip().replace("\\", "/")
    else:
        prev_path = _LAST_SCENE_PATH

    _persist_open_window()
    new_path = _current_scene_path()
    if new_path:
        try:
            if not prev_path:
                migrate_untitled_to_scene(new_path)
            elif prev_path != new_path:
                clone_project_to_scene(prev_path, new_path)
        except Exception as e:
            log.debug("post-save session transition (%s -> %s): %s", prev_path, new_path, e)
    _LAST_SCENE_PATH = new_path

    if win is not None:
        try:
            win.on_scene_changed(reload_only=False, persist_current=False)
        except Exception as e:
            log.debug("scene save notify: %s", e)


def _get_window():
    try:
        from maya_agent.ui.main_window import get_window_instance

        return get_window_instance()
    except Exception:
        return None
