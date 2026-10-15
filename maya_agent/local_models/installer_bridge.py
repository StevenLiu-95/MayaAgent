"""Bridge to scripts/install_local_runtime.py from the Maya UI."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from maya_agent.local_models.discovery import is_runtime_installed, read_discovery
from maya_agent.utils.logger import get_logger
from maya_agent.utils.paths import local_runtime_install_root, project_root

log = get_logger("maya_agent.local_models.installer")

LineCb = Callable[[str], None]
ProgressCb = Callable[[int, str], None]

_PROGRESS_RE = re.compile(r"^PROGRESS\s+(\d{1,3})\s*(.*)$")
_SUBPROGRESS_RE = re.compile(r"^SUBPROGRESS\s+(\d{1,3})\s*(.*)$")
# Fallback if installer is older / pip raw ticks leak through
_PIP_BYTES_RE = re.compile(r"(?i)^Progress\s+(\d+)\s+of\s+(\d+)\s*$")


def installer_script() -> Path:
    return project_root() / "scripts" / "install_local_runtime.py"


def install_report_path() -> Path:
    return local_runtime_install_root() / "install_report.json"


def _is_maya_gui_executable(path: str) -> bool:
    name = Path(path).name.lower()
    return name in {
        "maya.exe",
        "maya",
        "maya.bin",
        "mayabatch.exe",
        "mayabatch",
    }


def _find_mayapy_near_current() -> str:
    """Locate mayapy next to the running Maya binary (never return maya.exe)."""
    try:
        from maya_agent.utils.maya_compat import in_maya, maya_version

        if not in_maya():
            return ""
        scripts = project_root() / "scripts"
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        from maya_discover import find_mayapy, find_mayapy_beside_executable

        beside = find_mayapy_beside_executable(sys.executable)
        if beside and beside.is_file():
            return str(beside)
        ver = maya_version()
        if ver and ver != "unknown":
            found = find_mayapy(ver)
            if found and found.is_file():
                return str(found)
    except Exception as e:
        log.debug("mayapy lookup failed: %s", e)
    try:
        exe = Path(sys.executable)
        for name in ("mayapy.exe", "mayapy"):
            cand = exe.with_name(name)
            if cand.is_file():
                return str(cand)
            cand = exe.parent / name
            if cand.is_file():
                return str(cand)
    except Exception:
        pass
    return ""


def resolve_installer_python() -> str:
    """
    Python used to *bootstrap* Local Runtime install.

    Must not be Maya GUI (maya.exe) — that would open a new Maya scene/window.
    Prefer system Python on PATH; fall back to mayapy; last resort non-GUI sys.executable.
    """
    env_py = (os.environ.get("MAYA_AGENT_RUNTIME_PYTHON") or "").strip()
    if env_py and Path(env_py).is_file() and not _is_maya_gui_executable(env_py):
        return env_py

    for candidate in ("python", "python3", "py"):
        found = shutil.which(candidate)
        if not found:
            continue
        if _is_maya_gui_executable(found):
            continue
        if Path(found).name.lower() in ("py.exe", "py"):
            return found
        low = found.lower().replace("\\", "/")
        if "/maya/" in low and "mayapy" not in low:
            continue
        return found

    mayapy = _find_mayapy_near_current()
    if mayapy:
        return mayapy

    if sys.executable and not _is_maya_gui_executable(sys.executable):
        return sys.executable

    return ""


def _installer_command(script: Path, flags: List[str]) -> List[str]:
    py = resolve_installer_python()
    if not py:
        raise RuntimeError(
            "找不到可用的 Python 来安装 Local Runtime。"
            "请安装系统 Python 3.10+ 并加入 PATH，或设置环境变量 "
            "MAYA_AGENT_RUNTIME_PYTHON=完整路径\\python.exe，"
            "也可直接双击项目根目录 install_local_runtime.bat。"
        )
    name = Path(py).name.lower()
    # -u: unbuffered stdout so UI sees live logs
    if name in ("py.exe", "py"):
        return [py, "-3", "-u", str(script), *flags]
    return [py, "-u", str(script), *flags]


def run_installer(
    *,
    repair: bool = False,
    uninstall: bool = False,
    extra_args: Optional[List[str]] = None,
    on_line: Optional[LineCb] = None,
    on_progress: Optional[ProgressCb] = None,
    on_subprogress: Optional[ProgressCb] = None,
) -> Dict[str, Any]:
    script = installer_script()
    if not script.is_file():
        return {"ok": False, "error": f"缺少安装脚本: {script}"}

    flags: List[str] = []
    if uninstall:
        flags.append("--uninstall")
    elif repair:
        flags.append("--repair")
    if extra_args:
        flags.extend(extra_args)

    try:
        args = _installer_command(script, flags)
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    log.info("running local runtime installer: %s", " ".join(args))
    if on_line:
        on_line("$ " + " ".join(args))
    if on_progress:
        on_progress(1, "启动安装进程…")

    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    stdout_chunks: List[str] = []
    try:
        proc = subprocess.Popen(
            args,
            cwd=str(project_root()),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
            creationflags=creationflags,
        )
    except OSError as e:
        return {"ok": False, "error": str(e)}

    assert proc.stdout is not None
    last_sub_log = -1
    try:
        for raw in proc.stdout:
            line = raw.rstrip("\r\n")
            stdout_chunks.append(line)
            stripped = line.strip()
            sm = _SUBPROGRESS_RE.match(stripped)
            if sm:
                pct = int(sm.group(1))
                msg = (sm.group(2) or "").strip()
                if on_subprogress:
                    on_subprogress(pct, msg)
                # Sparse log lines for sub-bar (every 5%)
                if on_line and (last_sub_log < 0 or pct - last_sub_log >= 5 or pct >= 100):
                    on_line(f"  ↳ 下载 {pct}%{(' — ' + msg) if msg else ''}")
                    last_sub_log = pct
                continue
            m = _PROGRESS_RE.match(stripped)
            if m:
                pct = int(m.group(1))
                msg = (m.group(2) or "").strip()
                if on_progress:
                    on_progress(pct, msg)
                if on_line and msg:
                    on_line(f"[{pct}%] {msg}")
                continue
            # Fallback: raw pip Progress ticks → sub bar
            pm = _PIP_BYTES_RE.match(stripped)
            if pm:
                done, total = int(pm.group(1)), int(pm.group(2))
                if total > 0 and on_subprogress:
                    pct = int(done * 100 / total)
                    msg = f"{done / 1e6:.1f} / {total / 1e6:.1f} MB  ({pct}%)"
                    on_subprogress(pct, msg)
                    if on_line and (last_sub_log < 0 or pct - last_sub_log >= 5 or pct >= 100):
                        on_line(f"  ↳ 下载 {pct}% — {msg}")
                        last_sub_log = pct
                continue
            if on_line and stripped:
                on_line(line)
        try:
            proc.wait(timeout=7200)
        except subprocess.TimeoutExpired:
            proc.kill()
            return {"ok": False, "error": "安装超时（>2h）"}
    except Exception as e:
        try:
            proc.kill()
        except Exception:
            pass
        return {"ok": False, "error": str(e)}

    code = int(proc.returncode or 0)
    ok = code == 0
    full = "\n".join(stdout_chunks)
    return {
        "ok": ok,
        "returncode": code,
        "stdout": full[-12000:],
        "stderr": "",
        "python": args[0],
        "installed": is_runtime_installed(),
        "discovery": read_discovery(),
        "message": "安装成功" if ok else "安装失败，请查看日志",
    }


def start_installer_async(
    *,
    repair: bool = False,
    on_done=None,
    on_line: Optional[LineCb] = None,
    on_progress: Optional[ProgressCb] = None,
    on_subprogress: Optional[ProgressCb] = None,
) -> None:
    def _run() -> None:
        result = run_installer(
            repair=repair,
            on_line=on_line,
            on_progress=on_progress,
            on_subprogress=on_subprogress,
        )
        if on_done:
            on_done(result)

    threading.Thread(target=_run, name="install_local_runtime", daemon=True).start()
