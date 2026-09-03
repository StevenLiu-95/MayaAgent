# -*- coding: utf-8 -*-
"""
Maya Agent — Maya Python plug-in (auto-load).

Installed to Documents/maya/plug-ins/MayaAgent.py by scripts/install.py.
Relies on MODULE_ROOT pointing at the project (or ASCII junction).
"""
from __future__ import annotations

import sys

import maya.cmds as cmds

# INSTALL: scripts/install.py replaces the next line's path.
MODULE_ROOT = r"__MAYA_AGENT_ROOT__"


def _ensure_path() -> bool:
    root = (MODULE_ROOT or "").replace("\\", "/")
    if not root or root.startswith("__"):
        print("[Maya Agent] MODULE_ROOT not configured — re-run install.bat")
        return False
    if root not in sys.path:
        sys.path.insert(0, root)
    return True


def _bootstrap():
    if not _ensure_path():
        return
    try:
        import maya_agent

        maya_agent.bootstrap()
        print("[Maya Agent] plug-in bootstrap OK")
    except Exception as exc:
        import traceback

        print("[Maya Agent] plug-in bootstrap failed:", exc)
        traceback.print_exc()


def initializePlugin(plugin):  # noqa: N802 — Maya API name
    """Called when Maya loads this plug-in."""
    print("[Maya Agent] plug-in loading…")
    if not _ensure_path():
        return
    # UI / menu sets are not ready during plug-in init — defer like userSetup
    try:
        import maya.utils

        maya.utils.executeDeferred(_bootstrap)
    except Exception:
        cmds.evalDeferred(
            "import maya_agent; maya_agent.bootstrap()",
            lowestPriority=True,
        )
    print("[Maya Agent] plug-in loaded (menu deferred)")


def uninitializePlugin(plugin):  # noqa: N802 — Maya API name
    """Called when Maya unloads this plug-in — also clears menu/shelf UI."""
    try:
        if _ensure_path():
            import maya_agent.plugin.menu as menu

            menu.uninstall_ui()
        else:
            # Best-effort without package import
            for name in ("MayaAgentMenu", "MayaAgentMainMenu"):
                if cmds.menu(name, exists=True):
                    cmds.deleteUI(name, menu=True)
            if cmds.shelfLayout("MayaAgent", exists=True):
                try:
                    import maya.mel as mel

                    mel.eval('deleteShelfTab "MayaAgent"')
                except Exception:
                    cmds.deleteUI("MayaAgent")
    except Exception as exc:
        print("[Maya Agent] UI cleanup on unload failed:", exc)
    print("[Maya Agent] plug-in unloaded")
