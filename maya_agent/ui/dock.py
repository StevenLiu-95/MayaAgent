"""Optional Maya workspaceControl docking helpers."""

from __future__ import annotations

from maya_agent.utils.maya_compat import import_qt, in_maya, wrap_maya_ptr

CONTROL_NAME = "MayaAgentWorkspace"


def show_dockable():
    """Show Agent UI inside a Maya workspaceControl (preferred in Maya)."""
    if not in_maya():
        return _show_floating()

    import maya.cmds as cmds

    if cmds.workspaceControl(CONTROL_NAME, exists=True):
        if not _workspace_has_content():
            # Stale / empty shell left by Maya workspace restore — rebuild.
            try:
                cmds.deleteUI(CONTROL_NAME)
            except Exception:
                try:
                    cmds.workspaceControl(CONTROL_NAME, edit=True, close=True)
                except Exception:
                    pass
            try:
                _create_workspace_control()
            except Exception:
                return _show_floating()
        _raise_workspace_control()
        return CONTROL_NAME

    try:
        _create_workspace_control()
        _raise_workspace_control()
        return CONTROL_NAME
    except Exception:
        return _show_floating()


def _show_floating():
    from maya_agent.ui.main_window import show_floating_window

    return show_floating_window()


def _workspace_has_content() -> bool:
    """True if the dock control already hosts the Agent UI."""
    try:
        import maya.OpenMayaUI as omui

        import maya_agent.ui.main_window as mw

        if mw._WINDOW_INSTANCE is not None:
            try:
                mw._WINDOW_INSTANCE.isVisible()
                return True
            except Exception:
                mw._WINDOW_INSTANCE = None

        _, _, QtWidgets, _binding = import_qt()
        ctrl_ptr = omui.MQtUtil.findControl(CONTROL_NAME)
        if not ctrl_ptr:
            return False
        control_widget = wrap_maya_ptr(ctrl_ptr, QtWidgets.QWidget)
        if getattr(control_widget, "_maya_agent_window", None) is not None:
            return True
        layout = control_widget.layout()
        if layout is None:
            return False
        return layout.count() > 0
    except Exception:
        return False


def _raise_workspace_control() -> None:
    """Make the dock panel visible and the active tab (not just created)."""
    import maya.cmds as cmds

    if not cmds.workspaceControl(CONTROL_NAME, exists=True):
        return

    # Order matters: visible → restore (un-collapse / select tab) → raise.
    try:
        cmds.workspaceControl(CONTROL_NAME, edit=True, visible=True)
    except Exception:
        pass
    try:
        cmds.workspaceControl(CONTROL_NAME, edit=True, restore=True)
    except Exception:
        pass
    try:
        # `raise` is a Python keyword — Maya exposes it as raise_
        cmds.workspaceControl(CONTROL_NAME, edit=True, raise_=True)
    except Exception:
        try:
            cmds.workspaceControl(CONTROL_NAME, edit=True, **{"raise": True})
        except Exception:
            pass

    # Defer a second restore: Maya often finishes docking layout one tick later.
    # cmds.evalDeferred(string) is MEL — use executeDeferred(callable).
    def _restore_again():
        try:
            if cmds.workspaceControl(CONTROL_NAME, exists=True):
                cmds.workspaceControl(
                    CONTROL_NAME, edit=True, visible=True, restore=True
                )
        except Exception:
            pass

    try:
        from maya_agent.utils.maya_compat import defer_idle_lowest

        defer_idle_lowest(_restore_again)
    except Exception:
        try:
            import maya.utils

            maya.utils.executeDeferred(_restore_again)
        except Exception:
            pass


def _create_workspace_control():
    import maya.cmds as cmds
    import maya.OpenMayaUI as omui

    from maya_agent.ui.main_window import MayaAgentWindow, load_stylesheet_safe
    from maya_agent.utils.config import get_config

    _QtCore, _QtGui, QtWidgets, _binding = import_qt()

    cfg = get_config()
    initial_width = int(cfg.get("ui.window_width", 420))

    cmds.workspaceControl(
        CONTROL_NAME,
        label="Maya Agent",
        retain=False,
        floating=False,
        tabToControl=["AttributeEditor", -1],
        initialWidth=initial_width,
        widthProperty="preferred",
        # Rebuild UI if Maya restores this control later in the session.
        uiScript=(
            "import maya_agent.ui.dock as _ma_dock; "
            "_ma_dock._rebuild_workspace_ui()"
        ),
    )

    _embed_window_into_control()
    return CONTROL_NAME


def _rebuild_workspace_ui() -> None:
    """Called via workspaceControl uiScript when Maya restores the control."""
    if not in_maya():
        return
    import maya.cmds as cmds

    if not cmds.workspaceControl(CONTROL_NAME, exists=True):
        return
    if _workspace_has_content():
        _raise_workspace_control()
        return
    try:
        _embed_window_into_control()
        _raise_workspace_control()
    except Exception as exc:
        print("[Maya Agent] workspace UI rebuild failed:", exc)


def _embed_window_into_control() -> None:
    import maya.OpenMayaUI as omui

    from maya_agent.ui.main_window import MayaAgentWindow, load_stylesheet_safe

    _QtCore, _QtGui, QtWidgets, _binding = import_qt()

    ctrl_ptr = omui.MQtUtil.findControl(CONTROL_NAME)
    if not ctrl_ptr:
        raise RuntimeError(f"workspaceControl {CONTROL_NAME} not found")

    control_widget = wrap_maya_ptr(ctrl_ptr, QtWidgets.QWidget)
    layout = control_widget.layout()
    if layout is None:
        layout = QtWidgets.QVBoxLayout(control_widget)
        layout.setContentsMargins(0, 0, 0, 0)

    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w:
            w.deleteLater()

    win = MayaAgentWindow(parent=control_widget)
    embedded = win.centralWidget()
    if embedded is not None:
        embedded.setParent(control_widget)
        layout.addWidget(embedded)
        win.setCentralWidget(None)
        win.hide()
    else:
        layout.addWidget(win)

    try:
        control_widget.setStyleSheet(load_stylesheet_safe())
    except Exception:
        pass

    control_widget._maya_agent_window = win  # type: ignore[attr-defined]

    import maya_agent.ui.main_window as mw

    mw._WINDOW_INSTANCE = win
