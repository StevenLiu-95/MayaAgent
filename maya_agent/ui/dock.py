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
        cmds.workspaceControl(CONTROL_NAME, edit=True, restore=True, visible=True)
        return CONTROL_NAME

    try:
        return _create_workspace_control()
    except Exception:
        return _show_floating()


def _show_floating():
    from maya_agent.ui.main_window import show_floating_window

    return show_floating_window()


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
    )

    ctrl_ptr = omui.MQtUtil.findControl(CONTROL_NAME)
    if not ctrl_ptr:
        return _show_floating()

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

    return CONTROL_NAME
