"""Maya Agent — AI-powered assistant for Maya game development workflows."""

from __future__ import annotations

import sys
from pathlib import Path

__version__ = "1.4.2"
__app_name__ = "Maya Agent"


def _ensure_vendor_path() -> None:
    """
    Prefer project ``.vendor`` when mayapy site-packages lacks httpx/requests.

    Populated by ``scripts/install_deps.py`` as a last-resort install target.
    """
    root = Path(__file__).resolve().parent.parent
    vendor = root / ".vendor"
    if not vendor.is_dir():
        return
    path = str(vendor)
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
