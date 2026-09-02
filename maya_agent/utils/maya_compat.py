"""Maya / Qt compatibility helpers for Maya Agent."""

from __future__ import annotations

import threading
from typing import Any, Callable, Optional, Tuple, TypeVar

_IN_MAYA: Optional[bool] = None
_MAYA_VERSION: Optional[str] = None

T = TypeVar("T")

NOT_IN_MAYA = "未在 Maya 中运行"


def in_maya() -> bool:
    global _IN_MAYA
    if _IN_MAYA is not None:
        return _IN_MAYA
    try:
        import maya.cmds  # noqa: F401

        _IN_MAYA = True
    except ImportError:
        _IN_MAYA = False
    return _IN_MAYA


def maya_version() -> str:
    """Return Maya version string like '2024' or 'unknown'."""
    global _MAYA_VERSION
    if _MAYA_VERSION is not None:
        return _MAYA_VERSION
    if not in_maya():
        _MAYA_VERSION = "unknown"
        return _MAYA_VERSION
    import maya.cmds as cmds_mod

    try:
        _MAYA_VERSION = str(int(float(cmds_mod.about(version=True))))
    except Exception:
        _MAYA_VERSION = cmds_mod.about(version=True) or "unknown"
    return _MAYA_VERSION


def get_qt_binding() -> Tuple[Any, str]:
    """Return (Qt package root module, binding name). Prefer Maya's bundled PySide."""
    errors = []
    for name in ("PySide6", "PySide2", "PyQt5"):
        try:
            mod = __import__(name)
            return mod, name
        except ImportError as e:
            errors.append(f"{name}: {e}")
    raise ImportError(
        "未找到 Qt 绑定（PySide6/PySide2/PyQt5）。"
        "请在 Maya 内运行或安装 PySide2。详情: " + "; ".join(errors)
    )


def import_qt():
    """Import QtCore, QtGui, QtWidgets with a unified interface."""
    _binding_mod, name = get_qt_binding()
    QtCore = __import__(f"{name}.QtCore", fromlist=["QtCore"])
    QtGui = __import__(f"{name}.QtGui", fromlist=["QtGui"])
    QtWidgets = __import__(f"{name}.QtWidgets", fromlist=["QtWidgets"])
    return QtCore, QtGui, QtWidgets, name


def wrap_maya_ptr(ptr, qwidget_cls=None):
    """Wrap a Maya UI pointer into a Qt widget (shiboken2/6)."""
    if ptr is None:
        return None
    _QtCore, _QtGui, QtWidgets, name = import_qt()
    cls = qwidget_cls or QtWidgets.QWidget
    if name == "PySide6":
        from shiboken6 import wrapInstance
    else:
        from shiboken2 import wrapInstance
    return wrapInstance(int(ptr), cls)


def get_maya_main_window():
    if not in_maya():
        return None
    try:
        import maya.OpenMayaUI as omui

        return wrap_maya_ptr(omui.MQtUtil.mainWindow())
    except Exception:
        return None


def cmds():
    if not in_maya():
        raise RuntimeError(NOT_IN_MAYA)
    import maya.cmds as _cmds

    return _cmds


def mel():
    if not in_maya():
        raise RuntimeError(NOT_IN_MAYA)
    import maya.mel as _mel

    return _mel


def ensure_plugin(name: str, quiet: bool = True) -> bool:
    c = cmds()
    if c.pluginInfo(name, query=True, loaded=True):
        return True
    try:
        c.loadPlugin(name, quiet=quiet)
        return True
    except Exception:
        return False


def run_on_main_thread(fn: Callable[[], T]) -> T:
    """Run callable on Maya main thread when needed (cmds are not thread-safe)."""
    if not in_maya():
        return fn()
    try:
        import maya.utils

        if threading.current_thread() is threading.main_thread():
            return fn()
        return maya.utils.executeInMainThreadWithResult(fn)
    except Exception:
        return fn()
