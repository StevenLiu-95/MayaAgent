#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for MCP HTTP protocol / discovery (no Maya required)."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ok(name: str) -> None:
    print(f"  OK  {name}")


def _fail(name: str, msg: str) -> None:
    raise AssertionError(f"{name}: {msg}")


def test_protocol_routes() -> None:
    from maya_agent.bridge.protocol import (
        authorize,
        match_route,
        new_token,
        normalize_path,
        parse_bearer,
        parse_json_body,
    )

    assert normalize_path("/v1/health/") == "/v1/health"
    assert match_route("GET", "/v1/health") == "health"
    assert match_route("GET", "/v1/tools") == "tools"
    assert match_route("POST", "/v1/tools/call") == "tools_call"
    assert match_route("POST", "/v1/agent/chat") == "agent_chat"
    assert match_route("POST", "/v1/agent/undo") == "agent_undo"
    assert match_route("GET", "/v1/mcp-config") == "mcp_config"
    assert match_route("GET", "/v1/system-prompt") == "system_prompt"
    assert match_route("GET", "/v1/nope") is None

    token = new_token()
    assert parse_bearer(f"Bearer {token}") == token
    assert parse_bearer("Basic x") is None
    ok, err = authorize({"Authorization": f"Bearer {token}"}, token)
    assert ok and not err
    ok, err = authorize({"Authorization": "Bearer wrong"}, token)
    assert not ok

    data, err = parse_json_body(b'{"name":"x","arguments":{}}')
    assert err == "" and data["name"] == "x"
    data, err = parse_json_body(b"not-json")
    assert data is None and err
    _ok("protocol_routes")


def test_discovery_roundtrip() -> None:
    from maya_agent.bridge import discovery as disc

    with tempfile.TemporaryDirectory() as tmp:
        # Monkeypatch user config dir via writing to a custom path
        custom = Path(tmp) / "bridge.json"
        original = disc.bridge_discovery_path

        def _path():
            return custom

        disc.bridge_discovery_path = _path  # type: ignore
        try:
            path = disc.write_discovery(
                host="127.0.0.1", port=8765, token="tok_test", pid=12345
            )
            assert path == custom
            data = disc.read_discovery()
            assert data is not None
            assert data["port"] == 8765
            assert data["token"] == "tok_test"
            assert disc.discovery_base_url(data) == "http://127.0.0.1:8765"
            assert disc.clear_discovery(only_if_pid=999) is False
            assert custom.is_file()
            assert disc.clear_discovery(only_if_pid=12345) is True
            assert not custom.is_file()
        finally:
            disc.bridge_discovery_path = original  # type: ignore
    _ok("discovery_roundtrip")


def test_mcp_config_snippet() -> None:
    from maya_agent.bridge.protocol import mcp_config_snippet

    snippet = mcp_config_snippet(project_root=str(ROOT), python_exe="python")
    servers = snippet.get("mcpServers") or {}
    assert "maya-agent" in servers
    args = servers["maya-agent"]["args"]
    assert args and Path(args[0]).name == "maya_mcp.py"
    _ok("mcp_config_snippet")


def test_http_server_health_auth() -> None:
    """Start bridge outside Maya, hit health + unauthorized tools."""
    from maya_agent.bridge import start, stop, status
    from maya_agent.bridge import discovery as disc
    from maya_agent.utils.config import get_config

    cfg = get_config()
    cfg.set("bridge.enabled", True)
    cfg.set("bridge.port", 18765)
    cfg.set("bridge.port_auto", True)

    # Ensure clean slate
    try:
        stop()
    except Exception:
        pass

    result = start(host="127.0.0.1", port=18765, port_auto=True)
    assert result.get("ok"), result
    base = result["base_url"]
    discovery = disc.read_discovery()
    assert discovery and discovery.get("token")

    try:
        import urllib.error
        import urllib.request

        # health — no auth
        with urllib.request.urlopen(f"{base}/v1/health", timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        assert payload.get("ok") is True
        assert "tool_count" in payload

        # tools without auth → 401
        req = urllib.request.Request(f"{base}/v1/tools")
        try:
            urllib.request.urlopen(req, timeout=5)
            _fail("tools_unauth", "expected 401")
        except urllib.error.HTTPError as e:
            assert e.code == 401

        # tools with auth
        token = discovery["token"]
        req = urllib.request.Request(
            f"{base}/v1/tools",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            tools_payload = json.loads(resp.read().decode("utf-8"))
        assert tools_payload.get("ok") is True
        tools = tools_payload.get("tools") or []
        assert isinstance(tools, list)
        assert len(tools) > 10
        names = {t.get("name") for t in tools if isinstance(t, dict)}
        # scene tools should be present when modules load
        assert any(names), "empty tool names"

        req = urllib.request.Request(
            f"{base}/v1/system-prompt",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            prompt_payload = json.loads(resp.read().decode("utf-8"))
        assert prompt_payload.get("ok") is True
        prompt_text = prompt_payload.get("prompt") or ""
        assert "Maya" in prompt_text or "maya" in prompt_text.lower()
        assert "## 运行环境" in prompt_text

        st = status()
        assert st.get("running") is True
    finally:
        stop()
        assert status().get("running") is False
    _ok("http_server_health_auth")


def main() -> None:
    print("test_bridge_protocol")
    test_protocol_routes()
    test_discovery_roundtrip()
    test_mcp_config_snippet()
    test_http_server_health_auth()
    print("all passed")


if __name__ == "__main__":
    main()
