"""Maya menu / shelf registration (deferred until UI is ready)."""

from __future__ import annotations

from maya_agent.utils.logger import get_logger
from maya_agent.utils.maya_compat import in_maya

log = get_logger("maya_agent.plugin")

# IMPORTANT: menu and shelf UI names must be DIFFERENT — Maya UI names are global.
MENU_NAME = "MayaAgentMenu"
MENU_LABEL = "Maya Agent"
SHELF_NAME = "MayaAgent"
SHELF_BUTTON_LABEL = "Agent"


def _main_window_name():
    import maya.cmds as cmds
    import maya.mel as mel

    try:
        name = mel.eval("$tmp=$gMainWindow")
        if name and cmds.window(name, exists=True):
            return name
    except Exception:
        pass
    if cmds.window("MayaWindow", exists=True):
        return "MayaWindow"
    windows = cmds.lsUI(windows=True) or []
    for w in windows:
        if "Maya" in w or w.endswith("Window"):
            return w
    return None


def _delete_menu_if_exists(name: str) -> None:
    import maya.cmds as cmds

    try:
        if cmds.menu(name, exists=True):
            cmds.deleteUI(name, menu=True)
    except Exception:
        try:
            cmds.deleteUI(name)
        except Exception:
            pass


def install_menu() -> None:
    if not in_maya():
        return
    import maya.cmds as cmds

    g_main = _main_window_name()
    if not g_main:
        log.warning("main window not ready")
        raise RuntimeError("Maya main window not ready for menu install")

    # Clean both new and legacy menu names
    _delete_menu_if_exists(MENU_NAME)
    _delete_menu_if_exists("MayaAgent")  # legacy name that collided with shelf

    try:
        cmds.menu(
            MENU_NAME,
            label=MENU_LABEL,
            parent=g_main,
            tearOff=True,
            allowOptionBoxes=False,
        )
    except Exception as e:
        # Name may still be occupied by a non-menu control; pick a unique fallback
        log.warning("menu create failed (%s), trying fallback name", e)
        fallback = "MayaAgentMainMenu"
        _delete_menu_if_exists(fallback)
        cmds.menu(
            fallback,
            label=MENU_LABEL,
            parent=g_main,
            tearOff=True,
        )
        menu_parent = fallback
    else:
        menu_parent = MENU_NAME

    cmds.menuItem(label="打开面板", parent=menu_parent, command=open_ui)
    cmds.menuItem(label="重新加载", parent=menu_parent, command=reload_plugin)
    cmds.menuItem(divider=True, parent=menu_parent)
    cmds.menuItem(label="关于 Maya Agent", parent=menu_parent, command=show_about)

    # Verify
    if not cmds.menu(menu_parent, exists=True):
        raise RuntimeError(f"menu {menu_parent} was not created")

    log.info("Maya Agent menu installed: %s under %s", menu_parent, g_main)
    print(f"[Maya Agent] menu OK: {menu_parent} -> parent {g_main}")


def install_shelf() -> None:
    if not in_maya():
        return
    import maya.cmds as cmds
    import maya.mel as mel

    try:
        top = mel.eval("$tmp=$gShelfTopLevel")
    except Exception as e:
        log.warning("shelf not ready: %s", e)
        return
    if not top or not cmds.shelfTabLayout(top, exists=True):
        log.warning("shelfTabLayout missing: %s", top)
        return

    if not cmds.shelfLayout(SHELF_NAME, exists=True):
        try:
            mel.eval(f'addNewShelfTab "{SHELF_NAME}"')
        except Exception:
            cmds.shelfLayout(SHELF_NAME, parent=top)

    if not cmds.shelfLayout(SHELF_NAME, exists=True):
        log.error("failed to create shelf tab %s", SHELF_NAME)
        return

    children = cmds.shelfLayout(SHELF_NAME, query=True, childArray=True) or []
    for ch in children:
        try:
            if cmds.shelfButton(ch, exists=True):
                label = cmds.shelfButton(ch, query=True, label=True) or ""
                ann = cmds.shelfButton(ch, query=True, annotation=True) or ""
                if label == SHELF_BUTTON_LABEL or "Maya Agent" in ann:
                    cmds.deleteUI(ch)
        except Exception:
            pass

    cmd = _launch_command()

    cmds.shelfButton(
        parent=SHELF_NAME,
        label=SHELF_BUTTON_LABEL,
        annotation="Maya Agent — 打开 AI 助手面板",
        image="pythonFamily.png",
        image1="pythonFamily.png",
        style="iconAndTextVertical",
        command=cmd,
        sourceType="python",
    )

    try:
        current = cmds.shelfTabLayout(top, query=True, selectTab=True)
        if current and current != SHELF_NAME and cmds.shelfLayout(current, exists=True):
            _ensure_button_on_shelf(current, cmd)
    except Exception as e:
        log.debug("skip current-shelf button: %s", e)

    try:
        cmds.shelfTabLayout(top, edit=True, selectTab=SHELF_NAME)
    except Exception:
        pass

    log.info("Maya Agent shelf installed")
    print("[Maya Agent] shelf OK:", SHELF_NAME)


def _launch_command() -> str:
    try:
        import maya_agent as _ma
        import os

        root = os.path.dirname(os.path.dirname(os.path.abspath(_ma.__file__)))
        root = root.replace("\\", "/")
    except Exception:
        root = ""
    if root:
        return (
            "import sys\n"
            f"p=r'{root}'\n"
            "sys.path.insert(0,p) if p not in sys.path else None\n"
            "import maya_agent\n"
            "maya_agent.launch()\n"
        )
    return "import maya_agent\nmaya_agent.launch()\n"


def _ensure_button_on_shelf(shelf: str, cmd: str) -> None:
    import maya.cmds as cmds

    children = cmds.shelfLayout(shelf, query=True, childArray=True) or []
    for ch in children:
        try:
            if cmds.shelfButton(ch, exists=True):
                ann = cmds.shelfButton(ch, query=True, annotation=True) or ""
                if "Maya Agent" in ann:
                    return
        except Exception:
            pass
    cmds.shelfButton(
        parent=shelf,
        label=SHELF_BUTTON_LABEL,
        annotation="Maya Agent — 打开 AI 助手面板",
        image="pythonFamily.png",
        image1="pythonFamily.png",
        style="iconAndTextVertical",
        command=cmd,
        sourceType="python",
    )


def open_ui(*_args) -> None:
    from maya_agent.ui.main_window import show_main_window

    show_main_window()


def reload_plugin(*_args) -> None:
    import importlib
    import sys

    modules = [m for m in list(sys.modules) if m.startswith("maya_agent")]
    for m in sorted(modules, reverse=True):
        try:
            importlib.reload(sys.modules[m])
        except Exception:
            pass
    install_menu()
    install_shelf()
    open_ui()


def show_about(*_args) -> None:
    import maya.cmds as cmds
    from maya_agent import __app_name__, __version__

    cmds.confirmDialog(
        title="关于",
        message=f"{__app_name__} v{__version__}\nAI Assistant for Maya game pipelines.",
        button=["OK"],
    )


def _deferred_install() -> None:
    menu_ok = False
    shelf_ok = False
    try:
        install_menu()
        menu_ok = True
    except Exception as e:
        log.exception("menu install failed")
        print("[Maya Agent] menu install failed:", e)
    try:
        install_shelf()
        shelf_ok = True
    except Exception as e:
        log.exception("shelf install failed")
        print("[Maya Agent] shelf install failed:", e)
    print(f"[Maya Agent] register done (menu={menu_ok}, shelf={shelf_ok})")
    try:
        from maya_agent.plugin.scene_hooks import install_scene_hooks

        install_scene_hooks()
    except Exception as e:
        log.warning("scene hooks failed: %s", e)


def bootstrap() -> None:
    """Called from userSetup.py — deferred because UI is not ready yet."""
    if not in_maya():
        return
    try:
        import maya.utils

        maya.utils.executeDeferred(_deferred_install)
        # Maya 2025: run once more after UI fully settles
        try:
            import maya.cmds as cmds

            cmds.evalDeferred(_deferred_install, lowestPriority=True)
        except Exception:
            maya.utils.executeDeferred(_deferred_install)
        print("[Maya Agent] bootstrap scheduled")
    except Exception as e:
        log.error("bootstrap schedule failed: %s", e)
        try:
            import maya.cmds as cmds

            cmds.evalDeferred(
                "import maya_agent; maya_agent.plugin.menu._deferred_install()"
            )
        except Exception as e2:
            print("[Maya Agent] bootstrap failed:", e, e2)
