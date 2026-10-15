"""Maya menu / shelf registration (deferred until UI is ready)."""

from __future__ import annotations

from maya_agent.utils.logger import get_logger
from maya_agent.utils.maya_compat import in_maya
from maya_agent.i18n import init_from_config, t

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
    init_from_config()
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
        label=t("menu.open"),
        parent=menu_parent,
        command=_menu_item_cmd("open_ui"),
        sourceType="python",
    )
    cmds.menuItem(
        label=t("menu.reload"),
        parent=menu_parent,
        command=_menu_item_cmd("reload_plugin"),
        sourceType="python",
    )
    cmds.menuItem(divider=True, parent=menu_parent)
    cmds.menuItem(
        label=t("menu.bridge_start"),
        parent=menu_parent,
        command=_menu_item_cmd("bridge_start"),
        sourceType="python",
    )
    cmds.menuItem(
        label=t("menu.bridge_stop"),
        parent=menu_parent,
        command=_menu_item_cmd("bridge_stop"),
        sourceType="python",
    )
    cmds.menuItem(
        label=t("menu.bridge_copy_mcp"),
        parent=menu_parent,
        command=_menu_item_cmd("bridge_copy_mcp"),
        sourceType="python",
    )
    cmds.menuItem(divider=True, parent=menu_parent)
    cmds.menuItem(
        label=t("menu.local_runtime_install"),
        parent=menu_parent,
        command=_menu_item_cmd("local_runtime_install"),
        sourceType="python",
    )
    cmds.menuItem(
        label=t("menu.local_runtime_start"),
        parent=menu_parent,
        command=_menu_item_cmd("local_runtime_start"),
        sourceType="python",
    )
    cmds.menuItem(
        label=t("menu.local_runtime_stop"),
        parent=menu_parent,
        command=_menu_item_cmd("local_runtime_stop"),
        sourceType="python",
    )
    cmds.menuItem(divider=True, parent=menu_parent)
    cmds.menuItem(
        label=t("menu.about"),
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
    init_from_config()
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
        annotation=t("menu.shelf_annotation"),
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
        annotation=t("menu.shelf_annotation"),
        image="pythonFamily.png",
        image1="pythonFamily.png",
        style="iconAndTextVertical",
        command=cmd,
        sourceType="python",
    )


def open_ui(*_args) -> None:
    from maya_agent.ui.main_window import show_main_window

    show_main_window()


def bridge_start(*_args) -> None:
    init_from_config()
    from maya_agent.bridge import start

    result = start()
    import maya.cmds as cmds

    if result.get("ok"):
        url = result.get("base_url") or ""
        port = result.get("port") or ""
        msg = t("bridge.started", url=url, port=port)
        if result.get("already_running"):
            msg = t("bridge.already_running", url=url)
        cmds.confirmDialog(title=t("bridge.title"), message=msg, button=["OK"])
        print(f"[Maya Agent] MCP: {url}")
    else:
        cmds.confirmDialog(
            title=t("bridge.title"),
            message=t("bridge.start_failed", error=result.get("error") or "unknown"),
            button=["OK"],
        )


def bridge_stop(*_args) -> None:
    init_from_config()
    from maya_agent.bridge import stop

    result = stop()
    import maya.cmds as cmds

    cmds.confirmDialog(
        title=t("bridge.title"),
        message=t("bridge.stopped") if result.get("stopped") else t("bridge.not_running"),
        button=["OK"],
    )
    print("[Maya Agent] MCP stopped")


def bridge_copy_mcp(*_args) -> None:
    init_from_config()
    from maya_agent.bridge import copy_mcp_config

    result = copy_mcp_config()
    text = result.get("text") or ""
    import maya.cmds as cmds

    try:
        from maya_agent.utils.maya_compat import import_qt

        _, _, QtWidgets, _ = import_qt()
        clip = QtWidgets.QApplication.clipboard()
        if clip is not None:
            clip.setText(text)
            cmds.confirmDialog(
                title=t("bridge.title"),
                message=t("bridge.mcp_copied", path=result.get("discovery") or ""),
                button=["OK"],
            )
            print("[Maya Agent] MCP config copied to clipboard")
            return
    except Exception as e:
        log.debug("clipboard copy failed: %s", e)
    cmds.confirmDialog(
        title=t("bridge.title"),
        message=text[:1500] if text else t("bridge.mcp_copy_failed"),
        button=["OK"],
    )


def local_runtime_install(*_args) -> None:
    init_from_config()
    import maya.cmds as cmds
    from maya_agent.local_models.installer_bridge import run_installer

    cmds.confirmDialog(
        title="Local Runtime",
        message="开始安装 Local Runtime（不含模型权重，可能耗时较长）…",
        button=["OK"],
    )
    result = run_installer()
    msg = result.get("message") or ""
    if result.get("stdout"):
        msg = (msg + "\n\n" + str(result.get("stdout")))[-1500:]
    if not result.get("ok") and result.get("error"):
        msg = str(result.get("error"))
    cmds.confirmDialog(
        title="Local Runtime",
        message=msg or ("OK" if result.get("ok") else "failed"),
        button=["OK"],
    )


def local_runtime_start(*_args) -> None:
    init_from_config()
    import maya.cmds as cmds
    from maya_agent.local_models.client import start_runtime

    result = start_runtime(wait_online=25.0)
    cmds.confirmDialog(
        title="Local Runtime",
        message=(
            result.get("message")
            or result.get("error")
            or (result.get("base_url") if result.get("ok") else "failed")
        ),
        button=["OK"],
    )


def local_runtime_stop(*_args) -> None:
    init_from_config()
    import maya.cmds as cmds
    from maya_agent.local_models.client import stop_runtime

    result = stop_runtime()
    cmds.confirmDialog(
        title="Local Runtime",
        message=result.get("message") or "stopped",
        button=["OK"],
    )


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


_INSTALL_ATTEMPTS = 0
_MAX_INSTALL_ATTEMPTS = 8
_BOOTSTRAP_DONE = False
_BOOTSTRAP_IN_FLIGHT = False


def _reset_bootstrap_state() -> None:
    """Allow a later bootstrap / reload to install UI again."""
    global _INSTALL_ATTEMPTS, _BOOTSTRAP_DONE, _BOOTSTRAP_IN_FLIGHT
    _INSTALL_ATTEMPTS = 0
    _BOOTSTRAP_DONE = False
    _BOOTSTRAP_IN_FLIGHT = False


def uninstall_ui() -> None:
    """Remove menu + shelf from a live Maya session."""
    if not in_maya():
        return
    _reset_bootstrap_state()
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

    # Stop MCP before wiping modules (old server thread would otherwise linger)
    try:
        from maya_agent.bridge import stop as _bridge_stop

        _bridge_stop()
    except Exception:
        pass

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

    menu_mod._reset_bootstrap_state()
    menu_mod.install_menu()
    menu_mod.install_shelf()
    menu_mod._BOOTSTRAP_DONE = True
    menu_mod._BOOTSTRAP_IN_FLIGHT = False
    menu_mod.open_ui()
    return True


def show_about(*_args) -> None:
    import maya.cmds as cmds
    from maya_agent import __app_name__, __version__

    init_from_config()
    cmds.confirmDialog(
        title=t("about.title"),
        message=t("about.body", version=__version__),
        button=["OK"],
    )


def _deferred_install(force: bool = False) -> None:
    """Install menu/shelf; retry while Maya main window / menu sets warm up."""
    global _INSTALL_ATTEMPTS, _BOOTSTRAP_DONE, _BOOTSTRAP_IN_FLIGHT
    if _BOOTSTRAP_DONE and not force:
        return
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
        try:
            from maya_agent.utils.config import get_config

            if get_config().get("bridge.auto_start", False):
                from maya_agent.bridge import start

                br = start()
                if br.get("ok"):
                    print(f"[Maya Agent] MCP auto-started: {br.get('base_url')}")
                else:
                    print(f"[Maya Agent] MCP auto-start failed: {br.get('error')}")
        except Exception as e:
            log.warning("MCP auto_start failed: %s", e)
        _BOOTSTRAP_DONE = True
        _BOOTSTRAP_IN_FLIGHT = False
        return

    if attempt >= _MAX_INSTALL_ATTEMPTS:
        _BOOTSTRAP_IN_FLIGHT = False
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
    """Called from userSetup / plug-in — deferred because UI / menu sets are not ready yet.

    Idempotent: plug-in + userSetup may both call this in one session; only the
    first successful install runs (reload_plugin / uninstall_ui reset state).
    """
    if not in_maya():
        return
    global _INSTALL_ATTEMPTS, _BOOTSTRAP_IN_FLIGHT
    if _BOOTSTRAP_DONE:
        print("[Maya Agent] bootstrap skipped (already done)")
        return
    if _BOOTSTRAP_IN_FLIGHT:
        print("[Maya Agent] bootstrap skipped (already in flight)")
        return

    _BOOTSTRAP_IN_FLIGHT = True
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
            _BOOTSTRAP_IN_FLIGHT = False
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
