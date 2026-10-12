# -*- coding: utf-8 -*-
"""
Maya Agent — Maya Python plug-in (auto-load).

Installed to Documents/maya/plug-ins/MayaAgent.py by scripts/install.py.

MODULE_ROOT is filled at install time, then re-validated at load. If stale,
the plug-in falls back to Documents/maya/<ver>/MayaAgent junction / sys.path.

NOTE: Do NOT pass raw Python source to cmds.evalDeferred() — that command
evaluates strings as MEL. Use maya.utils.executeDeferred(callable) instead.
Only schedule bootstrap once (no parallel evalDeferred when executeDeferred works).
"""
from __future__ import annotations

import os
import sys

import maya.cmds as cmds

# INSTALL: scripts/install.py replaces the next line's path (project root).
MODULE_ROOT = r"__MAYA_AGENT_ROOT__"


def _is_valid_root(root: str) -> bool:
    if not root or root.startswith("__"):
        return False
    marker = os.path.join(root, "maya_agent", "__init__.py")
    return os.path.isfile(marker)


def _maya_version_str() -> str:
    try:
        return str(int(float(cmds.about(version=True))))
    except Exception:
        try:
            return str(cmds.about(version=True) or "")
        except Exception:
            return ""


def _documents_maya_root() -> str:
    if sys.platform == "darwin":
        return os.path.join(
            os.path.expanduser("~"),
            "Library",
            "Preferences",
            "Autodesk",
            "maya",
        )
    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    return os.path.join(home, "Documents", "maya")


def _version_junction_root(version: str) -> str:
    if not version:
        return ""
    if sys.platform == "darwin":
        return os.path.join(_documents_maya_root(), version, "MayaAgent")
    return os.path.join(_documents_maya_root(), version, "MayaAgent")


def _roots_from_sys_path():
    found = []
    for entry in list(sys.path):
        if not entry:
            continue
        candidate = entry.replace("\\", "/")
        if _is_valid_root(candidate):
            found.append(candidate)
    return found


def resolve_module_root() -> str:
    """
    Resolve project root for import.

    Order: configured MODULE_ROOT → per-version junction → sys.path hit.
    """
    configured = (MODULE_ROOT or "").replace("\\", "/")
    if _is_valid_root(configured):
        return configured

    ver = _maya_version_str()
    junction = _version_junction_root(ver).replace("\\", "/")
    if _is_valid_root(junction):
        print(f"[Maya Agent] MODULE_ROOT stale; using version junction: {junction}")
        return junction

    for candidate in _roots_from_sys_path():
        print(f"[Maya Agent] MODULE_ROOT stale; using sys.path: {candidate}")
        return candidate

    return ""


def _ensure_path() -> bool:
    root = resolve_module_root()
    if not root:
        print(
            "[Maya Agent] MODULE_ROOT not configured or invalid — re-run install.bat "
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
    except ModuleNotFoundError as exc:
        import traceback

        print("[Maya Agent] plug-in bootstrap failed:", exc)
        traceback.print_exc()
        print(
            "[Maya Agent] Missing module. Re-run install.bat "
            "(handles Windows proxy/SSL) or drag install_dragdrop.mel into the viewport."
        )
    except Exception as exc:
        import traceback

        print("[Maya Agent] plug-in bootstrap failed:", exc)
        traceback.print_exc()


def _schedule_bootstrap() -> None:
    """Defer bootstrap once — prefer executeDeferred(callable); fallback only if needed."""
    # Preferred: maya.utils.executeDeferred(callable)
    try:
        import maya.utils

        maya.utils.executeDeferred(_bootstrap)
        print("[Maya Agent] plug-in loaded (menu deferred)")
        return
    except Exception as exc:
        print("[Maya Agent] executeDeferred failed:", exc)

    # Fallback: MEL evalDeferred wrapping python("...") — never pass raw Python
    try:
        root = resolve_module_root().replace("\\", "/")
        py = (
            f"import sys; p=r'{root}'; "
            "sys.path.insert(0,p) if p and p not in sys.path else None; "
            "import maya_agent; maya_agent.bootstrap()"
        )
        escaped = py.replace("\\", "\\\\").replace('"', '\\"')
        mel = f'python("{escaped}")'
        cmds.evalDeferred(mel, lowestPriority=True)
        print("[Maya Agent] plug-in loaded (menu deferred via MEL fallback)")
        return
    except Exception as exc:
        print("[Maya Agent] evalDeferred(python(...)) failed:", exc)

    try:
        _bootstrap()
        print("[Maya Agent] plug-in loaded (immediate bootstrap)")
    except Exception as exc:
        print("[Maya Agent] plug-in loaded but bootstrap could not be scheduled:", exc)


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
