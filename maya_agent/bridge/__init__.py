"""Local MCP service — expose Maya tools + Agent over localhost HTTP / MCP."""

from __future__ import annotations

from typing import Any, Dict, Optional

from maya_agent.bridge.discovery import (
    bridge_discovery_path,
    clear_discovery,
    read_discovery,
)
from maya_agent.bridge.http_server import start_server, status, stop_server
from maya_agent.bridge.agent_remote import (
    register_panel_agent,
    unregister_panel_agent,
)

__all__ = [
    "start",
    "stop",
    "status",
    "start_server",
    "stop_server",
    "register_panel_agent",
    "unregister_panel_agent",
    "bridge_discovery_path",
    "read_discovery",
    "clear_discovery",
    "copy_mcp_config",
]


def start(
    *,
    host: Optional[str] = None,
    port: Optional[int] = None,
    port_auto: Optional[bool] = None,
) -> Dict[str, Any]:
    return start_server(host=host, port=port, port_auto=port_auto)


def stop() -> Dict[str, Any]:
    return stop_server()


def copy_mcp_config() -> Dict[str, Any]:
    """Return MCP config JSON text for clipboard / UI."""
    import json

    from maya_agent.bridge.protocol import mcp_config_snippet
    from maya_agent.utils.paths import project_root

    # Keep Cursor alwaysApply rule in sync with system_zh.md
    try:
        from pathlib import Path
        import runpy

        sync = project_root() / "scripts" / "sync_cursor_maya_rules.py"
        if sync.is_file():
            ns = runpy.run_path(str(sync))
            fn = ns.get("sync")
            if callable(fn):
                fn()
    except Exception:
        pass

    snippet = mcp_config_snippet(project_root=str(project_root()), python_exe="python")
    text = json.dumps(snippet, ensure_ascii=False, indent=2)
    return {
        "ok": True,
        "text": text,
        "mcp": snippet,
        "discovery": str(bridge_discovery_path()),
    }
