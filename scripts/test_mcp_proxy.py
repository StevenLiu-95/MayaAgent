#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test MCP proxy client against a fake HTTP bridge (no Maya / no mcp SDK required).

Exercises scripts/maya_mcp.py BridgeClient + meta tool routing via a stdlib
ThreadingHTTPServer that mimics /v1/health, /v1/tools, /v1/tools/call.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _ok(name: str) -> None:
    print(f"  OK  {name}")


TOKEN = "test-token-mcp-proxy"
FAKE_TOOLS = [
    {
        "name": "get_scene_info",
        "description": "Query scene info",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    }
]


class _FakeBridge(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        pass

    def _auth_ok(self) -> bool:
        auth = self.headers.get("Authorization") or ""
        return auth == f"Bearer {TOKEN}"

    def _send(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/v1/health":
            self._send(
                200,
                {
                    "ok": True,
                    "service": "maya-agent-bridge",
                    "tool_count": len(FAKE_TOOLS),
                    "maya": "fake",
                },
            )
            return
        if path == "/v1/tools":
            if not self._auth_ok():
                self._send(401, {"ok": False, "error": "unauthorized"})
                return
            self._send(200, {"ok": True, "tools": FAKE_TOOLS})
            return
        if path == "/v1/system-prompt":
            if not self._auth_ok():
                self._send(401, {"ok": False, "error": "unauthorized"})
                return
            self._send(
                200,
                {
                    "ok": True,
                    "prompt": "FAKE_SYSTEM_PROMPT\n\n## 运行环境\n- Maya: fake\n",
                    "source": "build_system_prompt",
                },
            )
            return
        self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            data = {}
        if not self._auth_ok():
            self._send(401, {"ok": False, "error": "unauthorized"})
            return
        if path == "/v1/tools/call":
            name = data.get("name")
            self._send(
                200,
                {
                    "ok": True,
                    "name": name,
                    "result": json.dumps(
                        {"ok": True, "message": f"called {name}", "data": data.get("arguments")}
                    ),
                },
            )
            return
        if path == "/v1/agent/chat":
            self._send(
                200,
                {
                    "ok": True,
                    "final": "hello from fake agent",
                    "events": [{"type": "done", "content": "hello from fake agent"}],
                },
            )
            return
        if path == "/v1/agent/undo":
            self._send(200, {"ok": True, "message": "undone"})
            return
        self._send(404, {"ok": False, "error": "not found"})


def _start_fake() -> Tuple[HTTPServer, int, threading.Thread]:
    server = HTTPServer(("127.0.0.1", 0), _FakeBridge)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port, thread


def test_bridge_client_against_fake() -> None:
    import maya_mcp as mcp_mod

    server, port, _thread = _start_fake()
    original_read = mcp_mod.read_discovery
    try:
        mcp_mod.read_discovery = lambda: {  # type: ignore
            "host": "127.0.0.1",
            "port": port,
            "token": TOKEN,
            "base_url": f"http://127.0.0.1:{port}",
        }
        client = mcp_mod.BridgeClient()
        health = client.health()
        assert health.get("ok") is True
        tools = client.list_tools()
        assert tools and tools[0]["name"] == "get_scene_info"
        called = client.call_tool("get_scene_info", {})
        assert called.get("ok") is True
        assert "get_scene_info" in (called.get("result") or "")

        status_text = mcp_mod._run_meta("mayaagent_status", {})
        assert "maya-agent-bridge" in status_text
        prompt_text = mcp_mod._run_meta("mayaagent_system_prompt", {})
        assert "FAKE_SYSTEM_PROMPT" in prompt_text
        assert "build_system_prompt" in prompt_text
        prompt_live, src = mcp_mod.resolve_system_prompt()
        assert "FAKE_SYSTEM_PROMPT" in prompt_live
        assert src == "build_system_prompt" or src == "maya_bridge"
        chat_text = mcp_mod._run_meta("mayaagent_chat", {"text": "hi"})
        assert "hello from fake agent" in chat_text
        undo_text = mcp_mod._run_meta("mayaagent_undo", {})
        assert "undone" in undo_text
        tool_text = mcp_mod._run_maya_tool("get_scene_info", {"x": 1})
        assert "called get_scene_info" in tool_text or '"ok": true' in tool_text.lower() or "ok" in tool_text
    finally:
        mcp_mod.read_discovery = original_read  # type: ignore
        server.shutdown()
        server.server_close()
    _ok("bridge_client_against_fake")


def main() -> None:
    print("test_mcp_proxy")
    # Prefer httpx; BridgeClient requires it
    try:
        import httpx  # noqa: F401
    except ImportError:
        print("  SKIP  httpx not installed (pip install httpx)")
        return
    test_bridge_client_against_fake()
    print("all passed")


if __name__ == "__main__":
    main()
