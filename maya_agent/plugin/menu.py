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


def _unregister_menu_from_sets(name: str) -> None:
    """Remove a menu from all Maya menu sets (safe if missing)."""
    import maya.cmds as cmds

    try:
        for ms in cmds.menuSet(query=True, allMenuSets=True) or []:
            try:
                arr = cmds.menuSet(ms, query=True, menuArray=True) or []
                if name in arr:
                    cmds.menuSet(ms, edit=True, removeMenu=name)
            except Exception:
                pass
    except Exception:
        pass


def _add_menu_to_set(menu_set: str, name: str) -> bool:
    """Add menu to a menuSet; try string then list form (Maya version differences)."""
    import maya.cmds as cmds

    try:
        arr = cmds.menuSet(menu_set, query=True, menuArray=True) or []
    except Exception:
        return False
    if name in arr:
        return True
    for payload in (name, [name]):
        try:
            cmds.menuSet(menu_set, edit=True, addMenu=payload)
            return True
        except Exception:
            continue
    return False


def _register_menu_in_sets(name: str) -> None:
    """
    Register custom menu into Maya menu sets so it actually appears.

    Maya 2016+ only shows menus that belong to the active menu set
    (建模 / 绑定 / 动画 …). Menus in commonMenuSet are always visible
    alongside File / Edit / Window — required for custom tools.
    Also register into every menu set as a fallback for localized / odd builds.
    """
    import maya.cmds as cmds

    registered = _add_menu_to_set("commonMenuSet", name)
    if not registered:
        log.warning("commonMenuSet register failed for %s", name)

    try:
        for ms in cmds.menuSet(query=True, allMenuSets=True) or []:
            if _add_menu_to_set(ms, name):
                registered = True
    except Exception as e:
        log.warning("menuSet fallback register failed: %s", e)

    if not registered:
        raise RuntimeError(f"failed to register menu {name} into any menu set")

    # Match Autodesk plugins (MASH / Bullet): force visible + place after common menus
    try:
        g_main = _main_window_name()
        common = cmds.menuSet("commonMenuSet", query=True, menuArray=True) or []
        pos = len(common)
        if g_main and pos > 0:
            try:
                cmds.window(g_main, edit=True, menuIndex=(name, pos))
            except Exception:
                pass
        cmds.menu(name, edit=True, visible=True)
    except Exception as e:
        log.debug("menu visibility/index tweak failed: %s", e)

    print(f"[Maya Agent] menuSet OK: {name} -> commonMenuSet (+ all sets)")


def _delete_menu_if_exists(name: str) -> None:
    import maya.cmds as cmds

    _unregister_menu_from_sets(name)
    try:
        if cmds.menu(name, exists=True):
            cmds.deleteUI(name, menu=True)
    except Exception:
        try:
            cmds.deleteUI(name)
        except Exception:
            pass


def _menu_item_cmd(dotted: str) -> str:
    """Stable Python command string for menuItem (survives reload better than callables)."""
    # Must import the submodule path — `import maya_agent` alone does not
    # expose maya_agent.plugin as an attribute on older / lazy packages.
    return (
        "import maya_agent.plugin.menu as _ma_menu\n"
        f"_ma_menu.{dotted}()\n"
    )


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
    _delete_menu_if_exists("MayaAgentMainMenu")

    try:
        cmds.menu(
            MENU_NAME,
            label=MENU_LABEL,
            parent=g_main,
            tearOff=True,
            allowOptionBoxes=False,
        )
        menu_parent = MENU_NAME
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

    cmds.menuItem(
        label="打开面板",
        parent=menu_parent,
        command=_menu_item_cmd("open_ui"),
        sourceType="python",
    )
    cmds.menuItem(
        label="重新加载",
        parent=menu_parent,
        command=_menu_item_cmd("reload_plugin"),
        sourceType="python",
    )
    cmds.menuItem(divider=True, parent=menu_parent)
    cmds.menuItem(
        label="关于 Maya Agent",
        parent=menu_parent,
        command=_menu_item_cmd("show_about"),
        sourceType="python",
    )

    # Critical: without menuSet registration the menu exists but is invisible
    _register_menu_in_sets(menu_parent)

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


def remove_shelf() -> None:
    """Remove MayaAgent shelf tab and any Agent buttons left on other shelves."""
    if not in_maya():
        return
    import maya.cmds as cmds
    import maya.mel as mel

    # 1) Dedicated MayaAgent tab
    try:
        if cmds.shelfLayout(SHELF_NAME, exists=True):
            try:
                mel.eval(f'deleteShelfTab "{SHELF_NAME}"')
            except Exception:
                try:
                    cmds.deleteUI(SHELF_NAME)
                except Exception:
                    pass
    except Exception as e:
        log.debug("deleteShelfTab failed: %s", e)

    # 2) Orphan Agent buttons on any remaining shelf
    try:
        top = mel.eval("$tmp=$gShelfTopLevel")
    except Exception:
        top = None
    if not top or not cmds.shelfTabLayout(top, exists=True):
        print("[Maya Agent] shelf removed (tab only)")
        return

    tabs = cmds.shelfTabLayout(top, query=True, childArray=True) or []
    for tab in tabs:
        try:
            children = cmds.shelfLayout(tab, query=True, childArray=True) or []
        except Exception:
            continue
        for ch in list(children):
            try:
                if not cmds.shelfButton(ch, exists=True):
                    continue
                label = cmds.shelfButton(ch, query=True, label=True) or ""
                ann = cmds.shelfButton(ch, query=True, annotation=True) or ""
                if label == SHELF_BUTTON_LABEL or "Maya Agent" in ann:
                    cmds.deleteUI(ch)
            except Exception:
                pass

    print("[Maya Agent] shelf removed")


def uninstall_ui() -> None:
    """Remove menu + shelf from a live Maya session."""
    if not in_maya():
        return
    for name in (MENU_NAME, "MayaAgentMainMenu", "MayaAgent"):
        _delete_menu_if_exists(name)
    remove_shelf()
    print("[Maya Agent] UI uninstalled")


def reload_plugin(*_args) -> None:
    """
    Hard-reload the package and reinstall menu/shelf.

    Prefer clearing sys.modules over importlib.reload(): chained reloads leave
    parent packages without submodule attributes (e.g. maya_agent.plugin missing).
    """
    import sys

    # Keep project root on sys.path (junction / install path)
    root = ""
    try:
        import maya_agent as _ma
        import os

        root = os.path.dirname(os.path.dirname(os.path.abspath(_ma.__file__)))
        if root and root not in sys.path:
            sys.path.insert(0, root)
    except Exception:
        pass

    for name in list(sys.modules):
        if name == "maya_agent" or name.startswith("maya_agent."):
            sys.modules.pop(name, None)

    import maya_agent.plugin.menu as menu_mod  # noqa: F401

    menu_mod._INSTALL_ATTEMPTS = 0
    menu_mod.install_menu()
    menu_mod.install_shelf()
    menu_mod.open_ui()
    return True


def show_about(*_args) -> None:
    import maya.cmds as cmds
    from maya_agent import __app_name__, __version__

    cmds.confirmDialog(
        title="关于",
        message=f"{__app_name__} v{__version__}\nAI Assistant for Maya game pipelines.",
        button=["OK"],
    )


_INSTALL_ATTEMPTS = 0
_MAX_INSTALL_ATTEMPTS = 8


def _deferred_install(force: bool = False) -> None:
    """Install menu/shelf; retry while Maya main window / menu sets warm up."""
    global _INSTALL_ATTEMPTS
    if not force:
        _INSTALL_ATTEMPTS += 1
    attempt = _INSTALL_ATTEMPTS

    menu_ok = False
    shelf_ok = False
    try:
        install_menu()
        menu_ok = True
    except Exception as e:
        log.exception("menu install failed (attempt %s)", attempt)
        print(f"[Maya Agent] menu install failed (attempt {attempt}):", e)
    try:
        install_shelf()
        shelf_ok = True
    except Exception as e:
        log.exception("shelf install failed (attempt %s)", attempt)
        print(f"[Maya Agent] shelf install failed (attempt {attempt}):", e)

    print(f"[Maya Agent] register done (menu={menu_ok}, shelf={shelf_ok}, attempt={attempt})")

    if menu_ok:
        try:
            from maya_agent.plugin.scene_hooks import install_scene_hooks

            install_scene_hooks()
        except Exception as e:
            log.warning("scene hooks failed: %s", e)
        return

    if attempt >= _MAX_INSTALL_ATTEMPTS:
        print(
            "[Maya Agent] menu still missing after retries. "
            "In Script Editor run: import maya_agent; maya_agent.reload()"
        )
        return

    # Menu sets / main window often lag behind plug-in init — retry soon.
    _schedule_retry()


def _schedule_retry() -> None:
    from maya_agent.utils.maya_compat import defer_idle_lowest

    if not defer_idle_lowest(_deferred_install):
        print("[Maya Agent] retry schedule failed")


def bootstrap() -> None:
    """Called from userSetup / plug-in — deferred because UI / menu sets are not ready yet."""
    if not in_maya():
        return
    global _INSTALL_ATTEMPTS
    _INSTALL_ATTEMPTS = 0

    # CRITICAL: cmds.evalDeferred(string) runs MEL, not Python.
    # Use maya.utils.executeDeferred(callable) via defer_idle helpers.
    from maya_agent.utils.maya_compat import defer_idle_lowest

    if defer_idle_lowest(_deferred_install):
        print("[Maya Agent] bootstrap scheduled")
    else:
        print("[Maya Agent] bootstrap schedule failed — trying immediate install")
        try:
            _deferred_install(force=True)
        except Exception as e:
            log.error("bootstrap failed: %s", e)
            print("[Maya Agent] bootstrap failed:", e)
            _print_bootstrap_hint(e)


def _print_bootstrap_hint(exc: BaseException) -> None:
    msg = str(exc)
    if "yaml" in msg.lower() or "httpx" in msg.lower() or "No module named" in msg:
        print(
            "[Maya Agent] 提示: 依赖可能未装入 mayapy。请重新运行 install.bat，\n"
            "  或把 install_dragdrop.mel 拖进视口；菜单创建不依赖 PyYAML。"
        )
