"""Maya Agent — AI-powered assistant for Maya game development workflows."""

from __future__ import annotations

import sys
from pathlib import Path


def _read_project_version() -> str:
    """Single source: project-root ``VERSION`` file (see scripts/sync_version.py)."""
    path = Path(__file__).resolve().parent.parent / "VERSION"
    try:
        return path.read_text(encoding="utf-8").strip().splitlines()[0].strip() or "0.0.0"
    except (OSError, IndexError):
        return "0.0.0"


__version__ = _read_project_version()
__app_name__ = "Maya Agent"


def _abi_tag() -> str:
    return f"cp{sys.version_info.major}{sys.version_info.minor}"


def _ensure_vendor_path() -> None:
    """
    Prefer project ``.vendor/<abi>/`` when mayapy site-packages lacks deps.

    Layout (commercial installer / install_deps):
      .vendor/cp37 | cp39 | cp311
    Legacy flat ``.vendor/`` (packages at top level) is still supported.
    """
    root = Path(__file__).resolve().parent.parent
    vendor_root = root / ".vendor"
    if not vendor_root.is_dir():
        return

    tag = _abi_tag()
    chosen = None
    tagged = vendor_root / tag
    if tagged.is_dir():
        try:
            if any(tagged.iterdir()):
                chosen = tagged
        except OSError:
            chosen = tagged

    if chosen is None:
        # Legacy: non-tag package dirs directly under .vendor
        try:
            kids = list(vendor_root.iterdir())
        except OSError:
            kids = []
        tag_names = {"cp37", "cp39", "cp311"}
        if any(c.is_dir() and c.name not in tag_names for c in kids):
            chosen = vendor_root

    if chosen is None:
        return
    path = str(chosen)
    if path not in sys.path:
        sys.path.insert(0, path)


_ensure_vendor_path()


def get_config():
    from maya_agent.utils.config import get_config as _get

    return _get()


def launch():
    from maya_agent.main import launch as _launch

    return _launch()


def bootstrap():
    from maya_agent.plugin.menu import bootstrap as _boot

    return _boot()


def reload():
    """Reload plugin code and reinstall Maya menu / shelf."""
    from maya_agent.plugin.menu import reload_plugin

    return reload_plugin()


__all__ = ["__version__", "__app_name__", "get_config", "launch", "bootstrap", "reload"]
