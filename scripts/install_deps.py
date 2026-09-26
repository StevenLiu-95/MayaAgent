"""
Install Python deps into a Maya ``mayapy`` environment.

Maya's bundled pip often breaks on Windows when IE/WinINET proxy is enabled
(``ValueError: check_hostname requires server_hostname``). This script:

1. Detects the system HTTP proxy and passes ``--proxy http://...`` to mayapy
2. Falls back to downloading wheels with the host Python, then offline install
3. Verifies critical imports (yaml / httpx / requests)
"""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple
from urllib.request import getproxies

try:
    import winreg  # type: ignore
except ImportError:  # non-Windows
    winreg = None  # type: ignore

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = PROJECT_ROOT / "requirements.txt"

# Packages we must be able to import after install (module name, pip name)
CRITICAL_IMPORTS: Tuple[Tuple[str, str], ...] = (
    ("yaml", "PyYAML"),
    ("httpx", "httpx"),
    ("requests", "requests"),
)

TRUSTED_HOSTS = (
    "pypi.org",
    "files.pythonhosted.org",
    "pypi.python.org",
    "mirrors.aliyun.com",
    "pypi.tuna.tsinghua.edu.cn",
)


def _run(cmd: Sequence[str], *, env: Optional[dict] = None) -> subprocess.CompletedProcess:
    print("  >", " ".join(cmd))
    return subprocess.run(
        list(cmd),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _print_proc(proc: subprocess.CompletedProcess) -> None:
    if proc.stdout and proc.stdout.strip():
        print(proc.stdout.rstrip())
    if proc.stderr and proc.stderr.strip():
        # pip writes progress to stderr
        print(proc.stderr.rstrip())


def find_mayapy(version: str) -> Optional[Path]:
    """Locate mayapy.exe / mayapy for a Maya version."""
    candidates: List[Path] = []

    if platform.system() == "Windows" and winreg is not None:
        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                rf"SOFTWARE\Autodesk\Maya\{version}\Setup\InstallPath",
            )
            try:
                loc, _ = winreg.QueryValueEx(key, "MAYA_INSTALL_LOCATION")
            finally:
                winreg.CloseKey(key)
            root = Path(str(loc))
            candidates.extend(
                [
                    root / "bin" / "mayapy.exe",
                    root / "bin" / "mayapy",
                ]
            )
        except OSError:
            pass

        for base in (
            Path(r"C:\Program Files\Autodesk") / f"Maya{version}",
            Path(r"D:\Program Files\Autodesk") / f"Maya{version}",
            Path(rf"D:\LAS\LAD\Maya\Program\{version}") / f"Maya{version}",
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Autodesk" / f"Maya{version}",
        ):
            candidates.append(base / "bin" / "mayapy.exe")

    elif platform.system() == "Darwin":
        candidates.append(
            Path(f"/Applications/Autodesk/maya{version}/Maya.app/Contents/bin/mayapy")
        )
    else:
        candidates.append(Path(f"/usr/autodesk/maya{version}/bin/mayapy"))

    for path in candidates:
        if path.is_file():
            return path
    return None


def detect_http_proxy() -> Optional[str]:
    """
    Return an HTTP(S) proxy URL suitable for pip ``--proxy``.

    Mayapy's urllib on Windows often reads IE proxy but then TLS-wraps it
    incorrectly. Explicit ``http://host:port`` fixes that.
    """
    for key in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "ALL_PROXY", "all_proxy"):
        val = (os.environ.get(key) or "").strip()
        if val:
            return val

    proxies = getproxies() or {}
    for key in ("https", "http", "all"):
        val = (proxies.get(key) or "").strip()
        if val:
            if "://" not in val:
                val = "http://" + val
            return val

    if platform.system() == "Windows" and winreg is not None:
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
            )
            try:
                enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
                server, _ = winreg.QueryValueEx(key, "ProxyServer")
            finally:
                winreg.CloseKey(key)
            if int(enabled) and server:
                server = str(server).strip()
                # May be "http=127.0.0.1:7897;https=127.0.0.1:7897" or plain host:port
                if "=" in server:
                    parts = {}
                    for chunk in server.split(";"):
                        if "=" in chunk:
                            k, v = chunk.split("=", 1)
                            parts[k.strip().lower()] = v.strip()
                    server = (
                        parts.get("http")
                        or parts.get("https")
                        or next(iter(parts.values()), "")
                    )
                if server and "://" not in server:
                    server = "http://" + server
                return server or None
        except OSError:
            pass
    return None


def mayapy_python_tag(mayapy: Path) -> str:
    """Return PEP 425 tag like '39' for mayapy's Python."""
    proc = _run(
        [
            str(mayapy),
            "-c",
            "import sys; print(f'{sys.version_info.major}{sys.version_info.minor}')",
        ]
    )
    if proc.returncode != 0:
        return "39"
    tag = (proc.stdout or "").strip()
    return tag if tag.isdigit() else "39"


def verify_imports(mayapy: Path) -> List[str]:
    missing: List[str] = []
    for mod, pip_name in CRITICAL_IMPORTS:
        proc = _run([str(mayapy), "-c", f"import {mod}"])
        if proc.returncode != 0:
            missing.append(pip_name)
    return missing


def _trusted_host_args() -> List[str]:
    args: List[str] = []
    for host in TRUSTED_HOSTS:
        args.extend(["--trusted-host", host])
    return args


def ascii_requirements(req: Path) -> Path:
    """
    Maya 2020–2023 mayapy ships an old pip that decodes requirements as GBK
    on Chinese Windows. Strip non-ASCII (comments) into a temp UTF-8/ASCII file.
    """
    lines: List[str] = []
    raw = req.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Drop inline comments; keep requirement specs only
        if "#" in stripped:
            stripped = stripped.split("#", 1)[0].strip()
        if not stripped:
            continue
        # Ensure ASCII-only for ancient pip
        ascii_line = stripped.encode("ascii", errors="ignore").decode("ascii").strip()
        if ascii_line:
            lines.append(ascii_line)
    if not lines:
        lines = ["requests>=2.28.0", "PyYAML>=6.0", "httpx>=0.24.0"]
    tmp = Path(tempfile.gettempdir()) / "maya_agent_requirements_ascii.txt"
    tmp.write_text("\n".join(lines) + "\n", encoding="ascii")
    return tmp


def package_names_from_req(req: Path) -> List[str]:
    """Parse top-level package names for fallback ``pip install pkg1 pkg2``."""
    names: List[str] = []
    for line in ascii_requirements(req).read_text(encoding="ascii").splitlines():
        spec = line.strip()
        if not spec:
            continue
        for sep in (">=", "<=", "==", "~=", "!=", ">", "<"):
            if sep in spec:
                spec = spec.split(sep, 1)[0].strip()
                break
        if spec and spec not in names:
            names.append(spec)
    return names


def pip_install_online(mayapy: Path, req: Path, proxy: Optional[str]) -> bool:
    safe_req = ascii_requirements(req)
    cmd = [str(mayapy), "-m", "pip", "install", "-r", str(safe_req)]
    cmd.extend(_trusted_host_args())
    if proxy:
        cmd.extend(["--proxy", proxy])

    env = os.environ.copy()
    if proxy:
        # Force both env and flag — mayapy otherwise re-reads broken IE TLS proxy
        env["HTTP_PROXY"] = proxy
        env["HTTPS_PROXY"] = proxy
        env["http_proxy"] = proxy
        env["https_proxy"] = proxy

    proc = _run(cmd, env=env)
    _print_proc(proc)
    if proc.returncode == 0 and not verify_imports(mayapy):
        return True

    # Fallback: install by package names (avoids -r file encoding entirely)
    pkgs = package_names_from_req(req)
    if not pkgs:
        return False
    cmd2 = [str(mayapy), "-m", "pip", "install", *pkgs]
    cmd2.extend(_trusted_host_args())
    if proxy:
        cmd2.extend(["--proxy", proxy])
    proc2 = _run(cmd2, env=env)
    _print_proc(proc2)
    return proc2.returncode == 0 and not verify_imports(mayapy)


def pip_install_offline(mayapy: Path, req: Path, wheel_dir: Path) -> bool:
    safe_req = ascii_requirements(req)
    cmd = [
        str(mayapy),
        "-m",
        "pip",
        "install",
        "--no-index",
        "--find-links",
        str(wheel_dir),
        "-r",
        str(safe_req),
    ]
    proc = _run(cmd)
    _print_proc(proc)
    if proc.returncode == 0 and not verify_imports(mayapy):
        return True

    pkgs = package_names_from_req(req)
    if not pkgs:
        return False
    cmd2 = [
        str(mayapy),
        "-m",
        "pip",
        "install",
        "--no-index",
        "--find-links",
        str(wheel_dir),
        *pkgs,
    ]
    proc2 = _run(cmd2)
    _print_proc(proc2)
    return proc2.returncode == 0 and not verify_imports(mayapy)


def download_wheels_with_host_python(req: Path, wheel_dir: Path, py_tag: str) -> bool:
    """Use system/host Python (usually healthier SSL) to fetch wheels for mayapy."""
    wheel_dir.mkdir(parents=True, exist_ok=True)
    host_py = sys.executable
    cmd = [
        host_py,
        "-m",
        "pip",
        "download",
        "-d",
        str(wheel_dir),
        "-r",
        str(req),
        "--python-version",
        py_tag,
        "--only-binary=:all:",
        # Common transitive deps for httpx on py<3.13
        "typing_extensions",
        "exceptiongroup",
        "sniffio",
        "anyio",
        "httpcore",
        "h11",
        "certifi",
        "idna",
        "charset_normalizer",
        "urllib3",
    ]
    # Prefer binary; if that fails, retry without only-binary for pure-python pkgs
    proc = _run(cmd)
    _print_proc(proc)
    if proc.returncode == 0:
        return True

    print("  [提示] 仅二进制下载失败，改用通用 download …")
    cmd2 = [
        host_py,
        "-m",
        "pip",
        "download",
        "-d",
        str(wheel_dir),
        "-r",
        str(req),
        "--python-version",
        py_tag,
        "typing_extensions",
        "exceptiongroup",
        "sniffio",
    ]
    proc2 = _run(cmd2)
    _print_proc(proc2)
    return proc2.returncode == 0


def install_for_mayapy(mayapy: Path, req: Path | None = None) -> bool:
    req = Path(req or REQUIREMENTS)
    if not req.is_file():
        print(f"  [错误] 缺少 {req}")
        return False

    print(f"  mayapy: {mayapy}")
    missing = verify_imports(mayapy)
    if not missing:
        print("  [成功] 关键依赖已就绪，跳过安装")
        return True

    print(f"  缺失: {', '.join(missing)}")
    proxy = detect_http_proxy()
    if proxy:
        print(f"  检测到代理: {proxy}")

    print("  [尝试 1/2] mayapy pip 在线安装 …")
    if pip_install_online(mayapy, req, proxy):
        print("  [成功] 在线安装完成")
        return True

    # If IE proxy was wrong as HTTPS, retry with explicit http:// proxy already done.
    # Second try without proxy env (direct) in case proxy itself is down.
    if proxy:
        print("  [尝试 1b] 直连（清空代理环境变量）…")
        env = os.environ.copy()
        for k in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "http_proxy",
            "https_proxy",
            "ALL_PROXY",
            "all_proxy",
        ):
            env.pop(k, None)
        env["NO_PROXY"] = "*"
        env["no_proxy"] = "*"
        cmd = [
            str(mayapy),
            "-m",
            "pip",
            "install",
            "--proxy",
            "",
            "-r",
            str(ascii_requirements(req)),
        ]
        cmd.extend(_trusted_host_args())
        proc = _run(cmd, env=env)
        _print_proc(proc)
        if proc.returncode == 0 and not verify_imports(mayapy):
            print("  [成功] 直连安装完成")
            return True
        # Package-name fallback
        pkgs = package_names_from_req(req)
        if pkgs:
            cmd_pkg = [str(mayapy), "-m", "pip", "install", "--proxy", "", *pkgs]
            cmd_pkg.extend(_trusted_host_args())
            proc_pkg = _run(cmd_pkg, env=env)
            _print_proc(proc_pkg)
            if proc_pkg.returncode == 0 and not verify_imports(mayapy):
                print("  [成功] 直连安装完成")
                return True

    print("  [尝试 2/2] 系统 Python 下载 wheel + mayapy 离线安装 …")
    py_tag = mayapy_python_tag(mayapy)
    with tempfile.TemporaryDirectory(prefix="maya_agent_wheels_") as tmp:
        wheel_dir = Path(tmp)
        if not download_wheels_with_host_python(req, wheel_dir, py_tag):
            print("  [失败] 无法下载依赖包")
            return False
        if pip_install_offline(mayapy, req, wheel_dir):
            print("  [成功] 离线安装完成")
            return True

    missing = verify_imports(mayapy)
    if missing:
        print(f"  [失败] 仍缺失: {', '.join(missing)}")
        print(f"  可手动执行: \"{mayapy}\" -m pip install --proxy http://127.0.0.1:PORT -r requirements.txt")
        return False
    return True


def install_versions(versions: Iterable[str], req: Path | None = None) -> int:
    req = Path(req or REQUIREMENTS)
    failures = 0
    found_any = False
    for ver in versions:
        print(f"\n=== Maya {ver} 依赖 ===")
        mayapy = find_mayapy(ver)
        if not mayapy:
            print(f"  [跳过] 未找到 mayapy.exe，仅会写入脚本挂钩")
            continue
        found_any = True
        if not install_for_mayapy(mayapy, req):
            failures += 1
    if not found_any:
        print("\n[警告] 未找到任何 mayapy，依赖未安装。菜单仍可出现，但对话功能需要 httpx。")
    return failures


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Install Maya Agent deps into mayapy")
    parser.add_argument(
        "--maya-version",
        action="append",
        dest="versions",
        default=[],
        help="Maya version (repeatable). Default: auto-detect common versions.",
    )
    parser.add_argument(
        "--requirements",
        default=str(REQUIREMENTS),
        help="Path to requirements.txt",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    versions = list(args.versions)
    if not versions:
        versions = ["2020", "2022", "2023", "2024", "2025", "2026"]

    failures = install_versions(versions, Path(args.requirements))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
