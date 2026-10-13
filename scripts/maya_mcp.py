#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Maya Agent MCP stdio server — proxies Cursor / VS Code / Claude Desktop
to the localhost MCP HTTP service running inside Maya.

Prerequisites:
  1. Start MCP in Maya (menu: Maya Agent → Start MCP)
  2. pip install -r requirements-mcp.txt   (system Python, not mayapy)
  3. Point mcp.json at this script

Discovery file (written by Maya):
  Windows: %APPDATA%/MayaAgent/bridge.json
  macOS/Linux: ~/.config/MayaAgent/bridge.json
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Discovery (stdlib only — mirrors maya_agent.bridge.discovery without importing Maya)
# ---------------------------------------------------------------------------


def _user_config_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "MayaAgent"


def read_discovery() -> Optional[Dict[str, Any]]:
    path = _user_config_dir() / "bridge.json"
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def discovery_base_url(data: Dict[str, Any]) -> str:
    url = str(data.get("base_url") or "").strip().rstrip("/")
    if url:
        return url
    host = str(data.get("host") or "127.0.0.1").strip() or "127.0.0.1"
    port = int(data.get("port") or 0)
    if not port:
        return ""
    return f"http://{host}:{port}"


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------


class BridgeClient:
    def __init__(self) -> None:
        self._http = None

    def _ensure_httpx(self):
        if self._http is not None:
            return self._http
        try:
            import httpx
        except ImportError as e:
            raise RuntimeError(
                "httpx is required. Run: pip install -r requirements-mcp.txt"
            ) from e
        self._http = httpx
        return httpx

    def _endpoint(self) -> Tuple[str, str]:
        data = read_discovery()
        if not data:
            raise RuntimeError(
                "Maya MCP discovery not found. "
                "In Maya: Maya Agent → Start MCP "
                f"(expected {_user_config_dir() / 'bridge.json'})"
            )
        base = discovery_base_url(data)
        token = str(data.get("token") or "")
        if not base or not token:
            raise RuntimeError("bridge.json is incomplete (need base_url/port and token)")
        return base, token

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        auth: bool = True,
        timeout: float = 120.0,
    ) -> Dict[str, Any]:
        httpx = self._ensure_httpx()
        base, token = self._endpoint()
        url = f"{base.rstrip('/')}{path}"
        headers = {"Accept": "application/json"}
        if auth:
            headers["Authorization"] = f"Bearer {token}"
        try:
            resp = httpx.request(
                method.upper(),
                url,
                headers=headers,
                json=json_body,
                timeout=timeout,
            )
        except httpx.ConnectError as e:
            raise RuntimeError(
                f"Cannot connect to Maya MCP at {base}. "
                "Is Maya running with MCP started?"
            ) from e
        try:
            data = resp.json()
        except Exception:
            data = {"ok": False, "error": resp.text[:500]}
        if resp.status_code == 401:
            raise RuntimeError(
                "Unauthorized — MCP token mismatch. Restart MCP in Maya."
            )
        if resp.status_code >= 400 and isinstance(data, dict) and data.get("error"):
            raise RuntimeError(str(data["error"]))
        if not isinstance(data, dict):
            return {"ok": False, "error": "invalid response", "raw": data}
        return data

    def health(self) -> Dict[str, Any]:
        return self.request("GET", "/v1/health", auth=False, timeout=10.0)

    def list_tools(self) -> List[Dict[str, Any]]:
        data = self.request("GET", "/v1/tools", timeout=30.0)
        tools = data.get("tools") or []
        return tools if isinstance(tools, list) else []

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return self.request(
            "POST",
            "/v1/tools/call",
            json_body={"name": name, "arguments": arguments or {}},
            timeout=300.0,
        )

    def agent_chat(self, text: str, images: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {"text": text, "stream": False}
        if images:
            body["images"] = images
        # Long-running multi-round agent
        return self.request("POST", "/v1/agent/chat", json_body=body, timeout=1800.0)

    def agent_undo(self) -> Dict[str, Any]:
        return self.request("POST", "/v1/agent/undo", json_body={}, timeout=60.0)


CLIENT = BridgeClient()

META_TOOLS = [
    {
        "name": "mayaagent_status",
        "description": (
            "Check whether the Maya Agent MCP service is running. "
            "Returns Maya version, tool count, and service URL."
        ),
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "mayaagent_chat",
        "description": (
            "Run the full MayaAgent conversation loop inside Maya "
            "(same tools + LLM + undo as the Maya panel). "
            "Prefer this for multi-step Maya tasks; for a single tool call, "
            "invoke that Maya tool directly."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "User instruction for MayaAgent",
                },
                "images": {
                    "type": "array",
                    "description": "Optional images as {mime, data_b64, name}",
                    "items": {"type": "object"},
                },
            },
            "required": ["text"],
            "additionalProperties": False,
        },
    },
    {
        "name": "mayaagent_undo",
        "description": "Undo the last MayaAgent turn (panel or mayaagent_chat) in Maya.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]


def _text_result(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _run_meta(name: str, arguments: Dict[str, Any]) -> str:
    if name == "mayaagent_status":
        return _text_result(CLIENT.health())
    if name == "mayaagent_chat":
        text = str((arguments or {}).get("text") or "")
        images = (arguments or {}).get("images")
        if images is not None and not isinstance(images, list):
            images = None
        out = CLIENT.agent_chat(text, images=images)
        # Compact summary for the IDE model
        summary = {
            "ok": out.get("ok"),
            "final": out.get("final") or out.get("error") or "",
            "events": out.get("events") or [],
        }
        return _text_result(summary)
    if name == "mayaagent_undo":
        return _text_result(CLIENT.agent_undo())
    raise ValueError(f"unknown meta tool: {name}")


def _run_maya_tool(name: str, arguments: Dict[str, Any]) -> str:
    out = CLIENT.call_tool(name, arguments or {})
    # Prefer the ToolResult JSON string if present
    if isinstance(out.get("result"), str) and out.get("result"):
        return out["result"]
    return _text_result(out)


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------


def main() -> None:
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        from mcp.types import TextContent, Tool
    except ImportError:
        print(
            "ERROR: mcp package not installed.\n"
            "  pip install -r requirements-mcp.txt",
            file=sys.stderr,
        )
        sys.exit(1)

    import anyio

    server = Server("maya-agent")

    @server.list_tools()
    async def list_tools() -> List[Tool]:
        tools: List[Tool] = []
        for meta in META_TOOLS:
            tools.append(
                Tool(
                    name=meta["name"],
                    description=meta["description"],
                    inputSchema=meta["parameters"],
                )
            )
        try:
            for item in CLIENT.list_tools():
                name = str(item.get("name") or "").strip()
                if not name or name.startswith("mayaagent_"):
                    continue
                tools.append(
                    Tool(
                        name=name,
                        description=str(item.get("description") or name),
                        inputSchema=item.get("parameters")
                        or {"type": "object", "properties": {}},
                    )
                )
        except Exception as e:
            # Still expose meta tools so the user can call mayaagent_status
            tools.append(
                Tool(
                    name="mayaagent_bridge_error",
                    description=f"MCP unreachable: {e}",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                )
            )
        return tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> List[TextContent]:
        args = arguments or {}

        def _dispatch() -> str:
            if name == "mayaagent_bridge_error":
                return _text_result(CLIENT.health())
            if name in {m["name"] for m in META_TOOLS}:
                return _run_meta(name, args)
            return _run_maya_tool(name, args)

        try:
            text = await anyio.to_thread.run_sync(_dispatch)
        except Exception as e:
            text = json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
        return [TextContent(type="text", text=text)]

    async def _amain() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )

    anyio.run(_amain)


if __name__ == "__main__":
    main()
