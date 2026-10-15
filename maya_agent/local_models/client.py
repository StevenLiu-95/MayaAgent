"""HTTP client for Local Runtime (Maya process side)."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from maya_agent.local_models.availability import local_cfg
from maya_agent.local_models.discovery import (
    discovery_base_url,
    is_runtime_installed,
    read_discovery,
)
from maya_agent.utils.logger import get_logger
from maya_agent.utils.paths import models_root, project_root

log = get_logger("maya_agent.local_models.client")


class LocalRuntimeError(RuntimeError):
    pass


def _http():
    try:
        import httpx
    except ImportError as e:
        raise LocalRuntimeError(
            "需要 httpx 才能连接 Local Runtime。请运行 install.bat / install_deps。"
        ) from e
    return httpx


def _auth_headers(token: str = "") -> Dict[str, str]:
    data = read_discovery() or {}
    tok = (token or str(data.get("token") or "")).strip()
    headers = {"Content-Type": "application/json"}
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    return headers


def runtime_status() -> Dict[str, Any]:
    cfg = local_cfg()
    disc = read_discovery() or {}
    installed = is_runtime_installed()
    base = discovery_base_url(disc)
    online = False
    health: Dict[str, Any] = {}
    if base:
        try:
            httpx = _http()
            with httpx.Client(timeout=3.0) as client:
                r = client.get(f"{base}/v1/health", headers=_auth_headers())
                if r.status_code == 200:
                    online = True
                    health = r.json() if r.content else {}
        except Exception as e:
            health = {"error": str(e)}
    return {
        "enabled": cfg["enabled"],
        "installed": installed,
        "online": online,
        "base_url": base,
        "models_dir": str(models_root()),
        "discovery": {
            "host": disc.get("host"),
            "port": disc.get("port"),
            "python_exe": disc.get("python_exe"),
            "version": disc.get("version"),
        },
        "health": health,
    }


def list_remote_backends() -> List[Dict[str, Any]]:
    base = discovery_base_url()
    if not base:
        return []
    httpx = _http()
    with httpx.Client(timeout=10.0) as client:
        r = client.get(f"{base}/v1/backends", headers=_auth_headers())
        r.raise_for_status()
        data = r.json()
    return list(data.get("backends") or [])


def submit_task(kind: str, params: Dict[str, Any]) -> Dict[str, Any]:
    base = discovery_base_url()
    if not base:
        raise LocalRuntimeError(
            "Local Runtime 未运行。请在「模型 → 本地模型」中启动，或菜单启动 Local Runtime。"
        )
    httpx = _http()
    body = {"kind": kind, "params": params or {}, "models_dir": str(models_root())}
    with httpx.Client(timeout=60.0) as client:
        r = client.post(
            f"{base}/v1/tasks",
            headers=_auth_headers(),
            content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        )
        if r.status_code >= 400:
            try:
                err = r.json()
            except Exception:
                err = {"error": r.text}
            raise LocalRuntimeError(err.get("error") or r.text or f"HTTP {r.status_code}")
        return r.json()


def get_task(task_id: str) -> Dict[str, Any]:
    base = discovery_base_url()
    if not base:
        raise LocalRuntimeError("Local Runtime 未运行")
    httpx = _http()
    with httpx.Client(timeout=30.0) as client:
        r = client.get(f"{base}/v1/tasks/{task_id}", headers=_auth_headers())
        if r.status_code >= 400:
            raise LocalRuntimeError(r.text or f"HTTP {r.status_code}")
        return r.json()


def wait_task(
    task_id: str,
    *,
    timeout: Optional[float] = None,
    poll_interval: Optional[float] = None,
    on_progress=None,
) -> Dict[str, Any]:
    cfg = local_cfg()
    timeout = float(timeout if timeout is not None else cfg["wait_timeout"])
    poll_interval = float(
        poll_interval if poll_interval is not None else cfg["poll_interval"]
    )
    deadline = time.time() + timeout
    last: Dict[str, Any] = {}
    while time.time() < deadline:
        last = get_task(task_id)
        status = str(last.get("status") or "").upper()
        if on_progress:
            try:
                on_progress(last)
            except Exception:
                pass
        if status in ("SUCCEEDED", "FAILED", "CANCELED"):
            return last
        time.sleep(max(0.5, poll_interval))
    raise LocalRuntimeError(f"等待任务超时 ({timeout}s): {task_id}")


def _python_exe_from_discovery() -> str:
    disc = read_discovery() or {}
    for key in ("python_exe", "python_home"):
        p = str(disc.get(key) or "").strip()
        if p and Path(p).exists():
            if key == "python_home" and Path(p).is_dir():
                win = Path(p) / "python.exe"
                nix = Path(p) / "bin" / "python"
                if win.is_file():
                    return str(win)
                if nix.is_file():
                    return str(nix)
            return p
    # install root fallbacks
    from maya_agent.utils.paths import local_runtime_install_root

    root = local_runtime_install_root()
    candidates = [
        root / "venv" / "Scripts" / "python.exe",
        root / "venv" / "bin" / "python",
        root / "python" / "python.exe",
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return ""


def start_runtime(*, wait_online: float = 20.0) -> Dict[str, Any]:
    """Spawn Local Runtime server as a detached process."""
    st = runtime_status()
    if st.get("online"):
        return {"ok": True, "message": "已在运行", **st}

    py = _python_exe_from_discovery()
    if not py:
        return {
            "ok": False,
            "error": "未找到 Local Runtime Python。请先运行 install_local_runtime.bat。",
            **st,
        }

    cfg = local_cfg()
    server_mod = project_root() / "local_runtime" / "server.py"
    if not server_mod.is_file():
        return {"ok": False, "error": f"缺少 {server_mod}"}

    env = dict(**{k: v for k, v in __import__("os").environ.items()})
    env["MAYA_AGENT_MODELS_DIR"] = str(models_root())
    env["MAYA_AGENT_LOCAL_HOST"] = cfg["runtime_host"]
    env["MAYA_AGENT_LOCAL_PORT"] = str(cfg["runtime_port"])
    env["MAYA_AGENT_LOCAL_PORT_AUTO"] = "1" if cfg["port_auto"] else "0"
    env["PYTHONPATH"] = str(project_root()) + (
        f"{__import__('os').pathsep}{env['PYTHONPATH']}" if env.get("PYTHONPATH") else ""
    )

    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]

    try:
        subprocess.Popen(
            [py, str(server_mod)],
            cwd=str(project_root()),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            start_new_session=(sys.platform != "win32"),
        )
    except OSError as e:
        return {"ok": False, "error": str(e)}

    deadline = time.time() + wait_online
    while time.time() < deadline:
        time.sleep(0.5)
        st = runtime_status()
        if st.get("online"):
            return {"ok": True, "message": "Local Runtime 已启动", **st}
    return {
        "ok": False,
        "error": "已启动进程但健康检查超时，请查看 Runtime 日志。",
        **runtime_status(),
    }


def stop_runtime() -> Dict[str, Any]:
    base = discovery_base_url()
    if not base:
        return {"ok": True, "message": "未在运行"}
    try:
        httpx = _http()
        with httpx.Client(timeout=5.0) as client:
            r = client.post(f"{base}/v1/shutdown", headers=_auth_headers())
            if r.status_code < 500:
                return {"ok": True, "message": "已请求关闭"}
    except Exception as e:
        log.debug("shutdown request failed: %s", e)
    return {"ok": True, "message": "关闭请求已发送（若仍占用端口请结束进程）"}
