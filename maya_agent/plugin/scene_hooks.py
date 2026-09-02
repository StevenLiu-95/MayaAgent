"""Maya scene callbacks — reload / persist chat sessions with project files."""

from __future__ import annotations

from maya_agent.utils.logger import get_logger
from maya_agent.utils.maya_compat import in_maya

log = get_logger("maya_agent.scene_hooks")

_CALLBACK_IDS: list = []
_INSTALLED = False


def install_scene_hooks() -> None:
    global _INSTALLED
    if _INSTALLED or not in_maya():
        return
    try:
        from maya.api.OpenMaya import MSceneMessage

        def _after_open(*_args):
            _on_scene_opened()

        def _after_save(*_args):
            _on_scene_saved()

        def _before_new(*_args):
            _persist_open_window()

        _CALLBACK_IDS.append(MSceneMessage.addCallback(MSceneMessage.kAfterOpen, _after_open))
        _CALLBACK_IDS.append(MSceneMessage.addCallback(MSceneMessage.kAfterSave, _after_save))
        _CALLBACK_IDS.append(MSceneMessage.addCallback(MSceneMessage.kBeforeNew, _before_new))
        _INSTALLED = True
        log.info("scene hooks installed")
    except Exception as e:
        log.warning("scene hooks install failed: %s", e)
        _try_script_job_fallback()


def _try_script_job_fallback() -> None:
    global _INSTALLED
    try:
        import maya.cmds as cmds

        cmds.scriptJob(event=["SceneOpened", "import maya_agent.plugin.scene_hooks as sh; sh._on_scene_opened()"], protected=True)
        cmds.scriptJob(event=["SceneSaved", "import maya_agent.plugin.scene_hooks as sh; sh._on_scene_saved()"], protected=True)
        cmds.scriptJob(event=["NewSceneOpened", "import maya_agent.plugin.scene_hooks as sh; sh._on_scene_opened()"], protected=True)
        _INSTALLED = True
        log.info("scene hooks installed via scriptJob")
    except Exception as e:
        log.warning("scriptJob fallback failed: %s", e)


def _persist_open_window() -> None:
    win = _get_window()
    if win is not None:
        try:
            win.persist_sessions()
        except Exception as e:
            log.debug("persist before scene change: %s", e)


def _on_scene_opened() -> None:
    _persist_open_window()
    win = _get_window()
    if win is not None:
        try:
            win.on_scene_changed()
        except Exception as e:
            log.warning("scene open reload failed: %s", e)


def _on_scene_saved() -> None:
    from maya_agent.core.session_store import get_maya_scene_path, migrate_untitled_to_scene

    _persist_open_window()
    path = get_maya_scene_path()
    if path:
        try:
            migrate_untitled_to_scene(path)
        except Exception as e:
            log.debug("migrate untitled: %s", e)
    win = _get_window()
    if win is not None:
        try:
            win.on_scene_changed(reload_only=False)
        except Exception as e:
            log.debug("scene save notify: %s", e)


def _get_window():
    try:
        from maya_agent.ui.main_window import get_window_instance

        return get_window_instance()
    except Exception:
        return None
