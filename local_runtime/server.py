#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local Runtime HTTP server — run with the isolated CUDA Python."""

from __future__ import annotations

import json
import os
import secrets
import socket
import sys
import threading
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

# Allow `python local_runtime/server.py` from project root
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from local_runtime import __version__  # noqa: E402
from local_runtime.backends import run_kind  # noqa: E402

try:
    from http.server import ThreadingHTTPServer as _ServerBase
except Exception:  # pragma: no cover
    from socketserver import ThreadingMixIn
    from http.server import HTTPServer

    class _ServerBase(ThreadingMixIn, HTTPServer):  # type: ignore
        daemon_threads = True


def _user_config_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    path = base / "MayaAgent"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _default_models_dir() -> Path:
    env = os.environ.get("MAYA_AGENT_MODELS_DIR", "").strip()
    if env:
        return Path(env)
    # Sibling of project: .../MayaAgentModels
    return _ROOT.parent / "MayaAgentModels"


def _pick_port(host: str, preferred: int, auto: bool) -> int:
    ports = [preferred]
    if auto:
        ports.extend(range(preferred + 1, preferred + 40))
    last = None
    for port in ports:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((host, port))
            return port
        except OSError as e:
            last = e
            if not auto:
                break
    raise OSError(f"no free port near {preferred}: {last}")


def _write_discovery(host: str, port: int, token: str, python_exe: str) -> None:
    path = _user_config_dir() / "local_runtime.json"
    payload = {
        "host": host,
        "port": port,
        "token": token,
        "pid": os.getpid(),
        "base_url": f"http://{host}:{port}",
        "api_prefix": "/v1",
        "version": __version__,
        "python_exe": python_exe,
        "models_dir": str(_default_models_dir()),
    }
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _load_catalog() -> Dict[str, Any]:
    path = Path(__file__).resolve().parent / "catalog.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"backends": []}


def _backend_ready(models_dir: Path, backend_id: str) -> bool:
    root = models_dir / backend_id
    if (root / ".installed").is_file():
        return True
    return root.is_dir() and any(root.rglob("*"))


class RuntimeState:
    def __init__(self) -> None:
        self.host = os.environ.get("MAYA_AGENT_LOCAL_HOST", "127.0.0.1")
        self.port = int(os.environ.get("MAYA_AGENT_LOCAL_PORT", "8770") or 8770)
        self.port_auto = os.environ.get("MAYA_AGENT_LOCAL_PORT_AUTO", "1") not in (
            "0",
            "false",
            "False",
        )
        self.token = secrets.token_urlsafe(24)
        self.models_dir = _default_models_dir()
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.RLock()
        self.server: Optional[_ServerBase] = None
        self._shutdown = threading.Event()


STATE = RuntimeState()


def _json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")


def _authorize(handler: BaseHTTPRequestHandler) -> bool:
    auth = handler.headers.get("Authorization") or ""
    if auth.startswith("Bearer "):
        return auth[7:].strip() == STATE.token
    # Allow empty token only on loopback health for easier first connect — still require token
    return False


def _run_task(task_id: str) -> None:
    with STATE.lock:
        task = STATE.tasks.get(task_id)
        if not task:
            return
        task["status"] = "RUNNING"
        kind = task["kind"]
        params = task["params"]
        models_dir = task.get("models_dir") or str(STATE.models_dir)

    def on_progress(ev: Dict[str, Any]) -> None:
        with STATE.lock:
            t = STATE.tasks.get(task_id)
            if not t:
                return
            t["progress"] = ev.get("progress", t.get("progress", 0))
            if ev.get("message"):
                t["message"] = ev["message"]

    try:
        result = run_kind(kind, params, models_dir=models_dir, on_progress=on_progress)
        with STATE.lock:
            t = STATE.tasks.get(task_id)
            if not t:
                return
            if result.get("ok"):
                t["status"] = "SUCCEEDED"
                t["result"] = result
                t["progress"] = 100
                t["message"] = result.get("message") or "ok"
            else:
                t["status"] = "FAILED"
                t["error"] = result.get("error") or "failed"
                t["result"] = result
    except Exception as e:
        with STATE.lock:
            t = STATE.tasks.get(task_id)
            if t:
                t["status"] = "FAILED"
                t["error"] = str(e)
                t["traceback"] = traceback.format_exc()


def _build_handler():
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            sys.stderr.write("local_runtime %s - %s\n" % (self.address_string(), fmt % args))

        def _send(self, status: int, body: bytes, content_type: str = "application/json") -> None:
            try:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            except Exception:
                pass

        def _read_json(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                return {}
            return data if isinstance(data, dict) else {}

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path.rstrip("/") or "/"
            loopback = self.client_address[0] in ("127.0.0.1", "::1")
            authed = _authorize(self)

            if path == "/v1/health":
                # Loopback may probe without token (startup race); others need Bearer.
                if not authed and not loopback:
                    self._send(401, _json_bytes({"error": "unauthorized"}))
                    return
                body = {
                    "ok": True,
                    "service": "mayaagent-local-runtime",
                    "version": __version__,
                    "models_dir": str(STATE.models_dir),
                    "cuda": _cuda_info(),
                }
                self._send(200, _json_bytes(body))
                return

            if not authed:
                self._send(401, _json_bytes({"error": "unauthorized"}))
                return

            if path == "/v1/backends":
                cat = _load_catalog()
                rows = []
                for b in cat.get("backends") or []:
                    bid = b.get("id")
                    rows.append(
                        {
                            **b,
                            "ready": _backend_ready(STATE.models_dir, str(bid)),
                            "path": str(STATE.models_dir / str(bid)),
                        }
                    )
                self._send(200, _json_bytes({"backends": rows}))
                return

            if path.startswith("/v1/tasks/"):
                task_id = path.split("/v1/tasks/", 1)[-1]
                with STATE.lock:
                    task = STATE.tasks.get(task_id)
                if not task:
                    self._send(404, _json_bytes({"error": "task not found"}))
                    return
                self._send(200, _json_bytes(task))
                return

            self._send(404, _json_bytes({"error": "not found"}))

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path.rstrip("/") or "/"
            if path == "/v1/shutdown":
                if not _authorize(self):
                    self._send(401, _json_bytes({"error": "unauthorized"}))
                    return
                self._send(200, _json_bytes({"ok": True}))
                threading.Thread(target=_shutdown_soon, daemon=True).start()
                return

            if not _authorize(self):
                self._send(401, _json_bytes({"error": "unauthorized"}))
                return

            if path == "/v1/tasks":
                body = self._read_json()
                kind = str(body.get("kind") or "").strip()
                params = body.get("params") if isinstance(body.get("params"), dict) else {}
                models_dir = str(body.get("models_dir") or STATE.models_dir)
                if not kind:
                    self._send(400, _json_bytes({"error": "kind required"}))
                    return
                task_id = uuid.uuid4().hex
                task = {
                    "id": task_id,
                    "kind": kind,
                    "params": params,
                    "models_dir": models_dir,
                    "status": "QUEUED",
                    "progress": 0,
                    "message": "",
                }
                with STATE.lock:
                    STATE.tasks[task_id] = task
                threading.Thread(
                    target=_run_task, args=(task_id,), name=f"task:{task_id}", daemon=True
                ).start()
                self._send(200, _json_bytes({"id": task_id, "status": "QUEUED"}))
                return

            self._send(404, _json_bytes({"error": "not found"}))

    return Handler


def _cuda_info() -> Dict[str, Any]:
    try:
        import torch

        return {
            "available": bool(torch.cuda.is_available()),
            "device_count": int(torch.cuda.device_count()) if torch.cuda.is_available() else 0,
            "name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "",
        }
    except Exception:
        return {"available": False, "device_count": 0, "name": ""}


def _shutdown_soon() -> None:
    import time

    time.sleep(0.3)
    STATE._shutdown.set()
    if STATE.server:
        try:
            STATE.server.shutdown()
        except Exception:
            pass


def main() -> int:
    host = STATE.host
    port = _pick_port(host, STATE.port, STATE.port_auto)
    STATE.port = port
    token = STATE.token
    python_exe = sys.executable
    _write_discovery(host, port, token, python_exe)

    handler = _build_handler()
    server = _ServerBase((host, port), handler)
    STATE.server = server
    print(
        f"[MayaAgent Local Runtime] http://{host}:{port}  models_dir={STATE.models_dir}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            path = _user_config_dir() / "local_runtime.json"
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                if int(data.get("pid") or 0) == os.getpid():
                    path.unlink()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
