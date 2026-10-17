"""HTTP protocol helpers for the Maya MCP service."""

from __future__ import annotations

import json
import secrets
from typing import Any, Dict, List, Optional, Tuple

API_PREFIX = "/v1"


def new_token() -> str:
    return secrets.token_urlsafe(32)


def parse_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.strip().split(None, 1)
    if len(parts) != 2:
        return None
    scheme, value = parts[0].lower(), parts[1].strip()
    if scheme != "bearer" or not value:
        return None
    return value


def authorize(headers: Dict[str, str], expected_token: str) -> Tuple[bool, str]:
    """Return (ok, error_message). health may skip auth; others require token."""
    if not expected_token:
        return False, "bridge token not configured"
    # Header keys may be mixed-case depending on client
    auth = ""
    for key, val in headers.items():
        if key.lower() == "authorization":
            auth = val
            break
    token = parse_bearer(auth)
    if not token:
        return False, "missing or invalid Authorization Bearer token"
    if not secrets.compare_digest(token, expected_token):
        return False, "invalid token"
    return True, ""


def json_bytes(payload: Any, *, status: int = 200) -> Tuple[int, bytes, str]:
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    return status, body, "application/json; charset=utf-8"


def error_body(message: str, *, status: int = 400, code: str = "") -> Tuple[int, bytes, str]:
    payload: Dict[str, Any] = {"ok": False, "error": message}
    if code:
        payload["code"] = code
    return json_bytes(payload, status=status)


def normalize_path(path: str) -> str:
    raw = (path or "/").split("?", 1)[0]
    if not raw.startswith("/"):
        raw = "/" + raw
    # Collapse trailing slash except root
    if len(raw) > 1 and raw.endswith("/"):
        raw = raw.rstrip("/")
    return raw


def match_route(method: str, path: str) -> Optional[str]:
    """
    Map method+path to a route id, or None if unknown.
    Route ids: health, tools, tools_call, agent_chat, agent_undo, mcp_config,
    system_prompt
    """
    m = (method or "GET").upper()
    p = normalize_path(path)
    if p == f"{API_PREFIX}/health" and m == "GET":
        return "health"
    if p == f"{API_PREFIX}/tools" and m == "GET":
        return "tools"
    if p == f"{API_PREFIX}/tools/call" and m == "POST":
        return "tools_call"
    if p == f"{API_PREFIX}/agent/chat" and m == "POST":
        return "agent_chat"
    if p == f"{API_PREFIX}/agent/undo" and m == "POST":
        return "agent_undo"
    if p == f"{API_PREFIX}/mcp-config" and m == "GET":
        return "mcp_config"
    if p == f"{API_PREFIX}/system-prompt" and m == "GET":
        return "system_prompt"
    return None


def tool_specs_to_openai_dicts(specs: List[Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for spec in specs:
        if hasattr(spec, "to_openai"):
            out.append(spec.to_openai())
        elif isinstance(spec, dict):
            out.append(spec)
    return out


def mcp_config_snippet(
    *,
    project_root: str,
    python_exe: str = "python",
) -> Dict[str, Any]:
    """Cursor / VS Code style mcp.json fragment."""
    script = str(Path_join(project_root, "scripts", "maya_mcp.py"))
    return {
        "mcpServers": {
            "maya-agent": {
                "command": python_exe,
                "args": [script],
            }
        }
    }


def Path_join(*parts: str) -> str:
    from pathlib import Path

    return str(Path(parts[0]).joinpath(*parts[1:]))


def parse_json_body(raw: bytes) -> Tuple[Optional[Dict[str, Any]], str]:
    if not raw:
        return {}, ""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        return None, f"invalid JSON body: {e}"
    if data is None:
        return {}, ""
    if not isinstance(data, dict):
        return None, "JSON body must be an object"
    return data, ""


def is_loopback_host(host: str) -> bool:
    h = (host or "").strip().lower()
    return h in ("127.0.0.1", "localhost", "::1")
