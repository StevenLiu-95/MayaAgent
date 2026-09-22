# -*- coding: utf-8 -*-
"""
Maya Agent — Maya Python plug-in (auto-load).

Installed to Documents/maya/plug-ins/MayaAgent.py by scripts/install.py.
Relies on MODULE_ROOT pointing at the project (or ASCII junction).

NOTE: Do NOT pass raw Python source to cmds.evalDeferred() — that command
evaluates strings as MEL. Use maya.utils.executeDeferred(callable) instead.
"""
from __future__ import annotations

import sys

import maya.cmds as cmds

# INSTALL: scripts/install.py replaces the next line's path.
MODULE_ROOT = r"__MAYA_AGENT_ROOT__"


def _ensure_path() -> bool:
    root = (MODULE_ROOT or "").replace("\\", "/")
    if not root or root.startswith("__"):
        print(
            "[Maya Agent] MODULE_ROOT not configured — re-run install.bat "
            "or drag install_dragdrop.mel into the viewport"
        )
        return False
    if root not in sys.path:
        sys.path.insert(0, root)
    return True


def _bootstrap() -> None:
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


def _schedule_bootstrap() -> None:
    """Defer bootstrap until Maya idle — must use Python callables, not MEL strings."""
    scheduled = False

    # Preferred: maya.utils.executeDeferred(callable)
    try:
        import maya.utils

        maya.utils.executeDeferred(_bootstrap)
        scheduled = True
    except Exception as exc:
        print("[Maya Agent] executeDeferred failed:", exc)

    # Backup: MEL evalDeferred wrapping python("...") — never pass raw Python
    try:
        root = MODULE_ROOT.replace("\\", "/")
        py = (
            f"import sys; p=r'{root}'; "
            "sys.path.insert(0,p) if p and p not in sys.path else None; "
            "import maya_agent; maya_agent.bootstrap()"
        )
        escaped = py.replace("\\", "\\\\").replace('"', '\\"')
        mel = f'python("{escaped}")'
        cmds.evalDeferred(mel, lowestPriority=True)
        scheduled = True
    except Exception as exc:
        print("[Maya Agent] evalDeferred(python(...)) failed:", exc)

    if not scheduled:
        try:
            _bootstrap()
            scheduled = True
        except Exception as exc:
            print("[Maya Agent] immediate bootstrap failed:", exc)

    if scheduled:
        print("[Maya Agent] plug-in loaded (menu deferred)")
    else:
        print("[Maya Agent] plug-in loaded but bootstrap could not be scheduled")


def initializePlugin(plugin):  # noqa: N802 — Maya API name
    """Called when Maya loads this plug-in."""
    print("[Maya Agent] plug-in loading…")
    if not _ensure_path():
        # Still mark as loaded in Plug-in Manager, but UI will be missing —
        # surface a clear hint in the Script Editor.
        print("[Maya Agent] path missing — menu will not appear until install is fixed")
        return
    _schedule_bootstrap()


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
