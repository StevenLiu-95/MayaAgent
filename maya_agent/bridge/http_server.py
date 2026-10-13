"""Localhost HTTP MCP server running inside Maya."""

from __future__ import annotations

import json
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote

from maya_agent import __version__
from maya_agent.bridge import discovery as disc
from maya_agent.bridge.agent_remote import (
    make_tool_confirm_callback,
    run_agent_chat,
    run_agent_undo,
)
from maya_agent.bridge.protocol import (
    API_PREFIX,
    authorize,
    error_body,
    json_bytes,
    match_route,
    mcp_config_snippet,
    new_token,
    normalize_path,
    parse_json_body,
    tool_specs_to_openai_dicts,
)
from maya_agent.core.executor import ToolExecutor
from maya_agent.llm.base import ImageAttachment
from maya_agent.tools.registry import ensure_tools_loaded, tool_specs
from maya_agent.utils.config import get_config
from maya_agent.utils.logger import get_logger
from maya_agent.utils.maya_compat import in_maya, maya_version
from maya_agent.utils.paths import project_root

log = get_logger("maya_agent.bridge.http")

# Python 3.7 may lack ThreadingHTTPServer — fall back
try:
    _ServerBase = ThreadingHTTPServer
except NameError:  # pragma: no cover
    from socketserver import ThreadingMixIn
    from http.server import HTTPServer

    class _ServerBase(ThreadingMixIn, HTTPServer):  # type: ignore
        daemon_threads = True


class BridgeState:
    def __init__(self) -> None:
        self.host = "127.0.0.1"
        self.port = 8765
        self.token = ""
        self.server: Optional[_ServerBase] = None
        self.thread: Optional[threading.Thread] = None
        self.executor = ToolExecutor(confirm_callback=make_tool_confirm_callback())

    @property
    def running(self) -> bool:
        return self.server is not None and self.thread is not None and self.thread.is_alive()


_STATE = BridgeState()


def get_state() -> BridgeState:
    return _STATE


def _pick_port(host: str, preferred: int, auto: bool) -> int:
    ports = [preferred]
    if auto:
        ports.extend(range(preferred + 1, preferred + 40))
    last_err: Optional[BaseException] = None
    for port in ports:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((host, port))
            return port
        except OSError as e:
            last_err = e
            if not auto:
                break
    raise OSError(f"no free port near {preferred}: {last_err}")


def _build_handler(state: BridgeState):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            log.debug("bridge %s - %s", self.address_string(), fmt % args)

        def _headers_dict(self) -> Dict[str, str]:
            return {k: v for k, v in self.headers.items()}

        def _read_body(self) -> bytes:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return b""
            # Cap at 32MB (images for agent chat)
            if length > 32 * 1024 * 1024:
                return b""
            return self.rfile.read(length)

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            try:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def _send_json(self, status: int, body: bytes, content_type: str) -> None:
            self._send(status, body, content_type)

        def do_OPTIONS(self) -> None:  # noqa: N802
            self._send(204, b"", "text/plain")

        def do_HEAD(self) -> None:  # noqa: N802
            self._dispatch()

        def do_GET(self) -> None:  # noqa: N802
            self._dispatch()

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch()

        def _dispatch(self) -> None:
            path = normalize_path(unquote(self.path or "/"))
            route = match_route(self.command, path)
            if route is None:
                status, body, ctype = error_body("not found", status=404, code="not_found")
                self._send_json(status, body, ctype)
                return

            # health is public (no secrets); others require bearer token
            if route != "health":
                ok, err = authorize(self._headers_dict(), state.token)
                if not ok:
                    status, body, ctype = error_body(err, status=401, code="unauthorized")
                    self._send_json(status, body, ctype)
                    return

            try:
                status, body, ctype = self._handle_route(route)
            except Exception as e:
                log.exception("bridge route %s failed", route)
                status, body, ctype = error_body(str(e), status=500, code="internal")
            self._send_json(status, body, ctype)

        def _handle_route(self, route: str) -> Tuple[int, bytes, str]:
            if route == "health":
                return self._health()
            if route == "tools":
                return self._tools()
            if route == "tools_call":
                return self._tools_call()
            if route == "agent_chat":
                return self._agent_chat()
            if route == "agent_undo":
                return self._agent_undo()
            if route == "mcp_config":
                return self._mcp_config()
            return error_body("not found", status=404)

        def _health(self) -> Tuple[int, bytes, str]:
            ensure_tools_loaded()
            specs = tool_specs(vision=True)
            return json_bytes(
                {
                    "ok": True,
                    "service": "maya-agent-bridge",
                    "version": __version__,
                    "maya": maya_version() if in_maya() else "not-in-maya",
                    "in_maya": in_maya(),
                    "host": state.host,
                    "port": state.port,
                    "tool_count": len(specs),
                    "api_prefix": API_PREFIX,
                }
            )

        def _tools(self) -> Tuple[int, bytes, str]:
            ensure_tools_loaded()
            specs = tool_specs_to_openai_dicts(tool_specs(vision=True))
            # Flatten to MCP-friendly list: name, description, parameters
            tools = []
            for item in specs:
                fn = item.get("function") if isinstance(item, dict) else None
                if isinstance(fn, dict):
                    tools.append(
                        {
                            "name": fn.get("name", ""),
                            "description": fn.get("description", ""),
                            "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
                        }
                    )
            return json_bytes({"ok": True, "tools": tools})

        def _tools_call(self) -> Tuple[int, bytes, str]:
            raw = self._read_body()
            data, err = parse_json_body(raw)
            if data is None:
                return error_body(err or "bad request", status=400)
            name = str(data.get("name") or "").strip()
            if not name:
                return error_body("missing tool name", status=400)
            arguments = data.get("arguments", {})
            if arguments is None:
                arguments = {}
            if isinstance(arguments, str):
                args_json = arguments
            elif isinstance(arguments, dict):
                args_json = json.dumps(arguments, ensure_ascii=False)
            else:
                return error_body("arguments must be object or JSON string", status=400)

            # Direct tool calls take the agent lock so they don't race chat
            from maya_agent.bridge.agent_remote import agent_lock, reset_bridge_confirm_turn

            reset_bridge_confirm_turn()
            with agent_lock():
                result = state.executor.execute(name, args_json)
            payload = {
                "ok": bool(result.ok),
                "name": name,
                "result": result.to_str(),
                "message": result.message,
                "error": result.error,
                "data": result.data,
            }
            # Attach image metadata (not full base64 in list) for callers that need vision
            imgs = []
            for img in result.images or []:
                if getattr(img, "data_b64", ""):
                    imgs.append(
                        {
                            "mime": getattr(img, "mime", "image/png"),
                            "name": getattr(img, "name", ""),
                            "data_b64": img.data_b64,
                        }
                    )
            if imgs:
                payload["images"] = imgs
            return json_bytes(payload, status=200 if result.ok else 200)

        def _parse_images(self, data: Dict[str, Any]) -> List[ImageAttachment]:
            images: List[ImageAttachment] = []
            for item in data.get("images") or []:
                if not isinstance(item, dict):
                    continue
                b64 = str(item.get("data_b64") or "")
                if not b64:
                    continue
                images.append(
                    ImageAttachment(
                        mime=str(item.get("mime") or "image/png"),
                        data_b64=b64,
                        name=str(item.get("name") or ""),
                    )
                )
            return images

        def _agent_chat(self) -> Tuple[int, bytes, str]:
            raw = self._read_body()
            data, err = parse_json_body(raw)
            if data is None:
                return error_body(err or "bad request", status=400)
            text = str(data.get("text") or data.get("message") or "")
            stream = bool(data.get("stream", False))
            images = self._parse_images(data)
            if not text.strip() and not images:
                return error_body("text or images required", status=400)
            out = run_agent_chat(text, images=images or None, stream=stream)
            status = 200 if out.get("ok") else 200
            return json_bytes(out, status=status)

        def _agent_undo(self) -> Tuple[int, bytes, str]:
            out = run_agent_undo()
            return json_bytes(out if isinstance(out, dict) else {"ok": False, "error": str(out)})

        def _mcp_config(self) -> Tuple[int, bytes, str]:
            root = str(project_root())
            py = sys.executable if not in_maya() else "python"
            # Prefer system python in snippet — maya.exe is wrong for MCP stdio
            snippet = mcp_config_snippet(project_root=root, python_exe="python")
            return json_bytes(
                {
                    "ok": True,
                    "discovery": str(disc.bridge_discovery_path()),
                    "base_url": f"http://{state.host}:{state.port}",
                    "mcp": snippet,
                    "hint": (
                        "1) Maya 中启动 MCP  2) 系统 Python: pip install -r requirements-mcp.txt  "
                        "3) 将 mcp 片段写入 Cursor/VS Code 的 mcp.json"
                    ),
                    "maya_python": py,
                }
            )

    return Handler


def start_server(
    *,
    host: Optional[str] = None,
    port: Optional[int] = None,
    port_auto: Optional[bool] = None,
) -> Dict[str, Any]:
    """Start the bridge if not already running."""
    cfg = get_config()
    if not bool(cfg.get("bridge.enabled", True)):
        return {"ok": False, "error": "bridge.enabled is false in settings"}

    state = _STATE
    if state.running:
        return {
            "ok": True,
            "already_running": True,
            "host": state.host,
            "port": state.port,
            "base_url": f"http://{state.host}:{state.port}",
            "discovery": str(disc.bridge_discovery_path()),
        }

    host = (host or cfg.get("bridge.host") or "127.0.0.1").strip() or "127.0.0.1"
    if host not in ("127.0.0.1", "localhost", "::1"):
        # Force loopback for safety
        log.warning("bridge host %s forced to 127.0.0.1", host)
        host = "127.0.0.1"
    preferred = int(port if port is not None else cfg.get("bridge.port", 8765) or 8765)
    auto = bool(port_auto if port_auto is not None else cfg.get("bridge.port_auto", True))

    try:
        chosen = _pick_port(host, preferred, auto)
    except OSError as e:
        return {"ok": False, "error": str(e)}

    token = new_token()
    handler = _build_handler(state)
    try:
        server = _ServerBase((host, chosen), handler)
    except OSError as e:
        return {"ok": False, "error": f"bind failed: {e}"}

    state.host = host
    state.port = chosen
    state.token = token
    state.server = server
    state.executor = ToolExecutor(confirm_callback=make_tool_confirm_callback())

    def _serve() -> None:
        log.info("MCP listening on http://%s:%s", host, chosen)
        try:
            server.serve_forever(poll_interval=0.5)
        except Exception:
            log.exception("bridge serve_forever exited")

    thread = threading.Thread(target=_serve, name="MayaAgentBridge", daemon=True)
    state.thread = thread
    thread.start()

    disc.write_discovery(host=host, port=chosen, token=token)
    ensure_tools_loaded()
    return {
        "ok": True,
        "already_running": False,
        "host": host,
        "port": chosen,
        "base_url": f"http://{host}:{chosen}",
        "discovery": str(disc.bridge_discovery_path()),
        "tool_count": len(tool_specs(vision=True)),
    }


def stop_server() -> Dict[str, Any]:
    state = _STATE
    if not state.server:
        disc.clear_discovery()
        return {"ok": True, "stopped": False, "message": "bridge was not running"}
    try:
        state.server.shutdown()
    except Exception as e:
        log.warning("bridge shutdown: %s", e)
    try:
        state.server.server_close()
    except Exception:
        pass
    if state.thread and state.thread.is_alive():
        state.thread.join(timeout=3.0)
    state.server = None
    state.thread = None
    state.token = ""
    disc.clear_discovery()
    return {"ok": True, "stopped": True}


def status() -> Dict[str, Any]:
    state = _STATE
    discovery = disc.read_discovery()
    return {
        "ok": True,
        "running": state.running,
        "host": state.host if state.running else (discovery or {}).get("host", ""),
        "port": state.port if state.running else (discovery or {}).get("port", 0),
        "base_url": f"http://{state.host}:{state.port}" if state.running else disc.discovery_base_url(discovery),
        "discovery": str(disc.bridge_discovery_path()),
        "has_discovery": discovery is not None,
    }
