"""Cached Qt binding for module-level UI classes.

Import UI packages only after Maya (or a standalone PySide) is available —
``maya_agent.launch()`` already delays UI imports.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

from maya_agent.utils.maya_compat import import_qt

_CACHE: Optional[Tuple[Any, Any, Any, str]] = None


def get_qt() -> Tuple[Any, Any, Any, str]:
    """Return ``(QtCore, QtGui, QtWidgets, binding_name)``, cached."""
    global _CACHE
    if _CACHE is None:
        _CACHE = import_qt()
    return _CACHE


def refresh_qt() -> Tuple[Any, Any, Any, str]:
    """Re-resolve Qt binding (e.g. after plugin reload)."""
    global _CACHE
    _CACHE = import_qt()
    return _CACHE


QtCore, QtGui, QtWidgets, QT_BINDING = get_qt()
