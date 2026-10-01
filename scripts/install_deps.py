"""
Install Python deps into a Maya ``mayapy`` environment (hardened).

Maya's bundled pip often breaks on Windows when IE/WinINET proxy is enabled
(``ValueError: check_hostname requires server_hostname``). This script:

1. Bootstraps / upgrades pip inside mayapy when needed
2. Detects system HTTP proxy and passes ``--proxy``
3. Tries multiple PyPI mirrors (official → Tsinghua → Aliyun)
4. Falls back to per-package install, then host-Python wheel download
5. Last resort: install into project ``.vendor`` (injected on Maya Agent import)
6. Verifies critical imports (httpx / requests / yaml)
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple
from urllib.request import getproxies

try:
    import winreg  # type: ignore
except ImportError:  # non-Windows
    winreg = None  # type: ignore

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = PROJECT_ROOT / "requirements.txt"
VENDOR_DIR = PROJECT_ROOT / ".vendor"

# Packages we must be able to import after install (module name, pip name)
CRITICAL_IMPORTS: Tuple[Tuple[str, str], ...] = (
    ("httpx", "httpx"),
    ("requests", "requests"),
    ("yaml", "PyYAML"),
)

# Minimal set required for chat (yaml is optional for config JSON)
CHAT_CRITICAL: Tuple[Tuple[str, str], ...] = (
    ("httpx", "httpx"),
    ("requests", "requests"),
)

TRUSTED_HOSTS = (
    "pypi.org",
    "files.pythonhosted.org",
    "pypi.python.org",
    "mirrors.aliyun.com",
    "pypi.tuna.tsinghua.edu.cn",
    "mirrors.cloud.tencent.com",
)

# (label, index URL) — empty index means default PyPI
PIP_INDEXES: Tuple[Tuple[str, str], ...] = (
    ("PyPI", ""),
    ("清华 TUNA", "https://pypi.tuna.tsinghua.edu.cn/simple"),
    ("阿里云", "https://mirrors.aliyun.com/pypi/simple"),
    ("腾讯云", "https://mirrors.cloud.tencent.com/pypi/simple"),
)

# Transitive deps often needed when downloading wheels for older mayapy
EXTRA_WHEEL_PKGS = (
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
)


def _run(
    cmd: Sequence[str],
    *,
    env: Optional[dict] = None,
    timeout: Optional[float] = 600,
) -> subprocess.CompletedProcess:
    print("  >", " ".join(cmd))
    try:
        return subprocess.run(
            list(cmd),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"") if isinstance(e.stdout, (bytes, bytearray)) else (e.stdout or "")
        err = (e.stderr or b"") if isinstance(e.stderr, (bytes, bytearray)) else (e.stderr or "")
        if isinstance(out, bytes):
            out = out.decode("utf-8", errors="replace")
        if isinstance(err, bytes):
            err = err.decode("utf-8", errors="replace")
        return subprocess.CompletedProcess(
            list(cmd), returncode=124, stdout=out or "", stderr=(err or "") + "\n[timeout]"
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
    ver = str(version).strip()

    if platform.system() == "Windows" and winreg is not None:
        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                rf"SOFTWARE\Autodesk\Maya\{ver}\Setup\InstallPath",
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

        prog = os.environ.get("ProgramFiles", r"C:\Program Files")
        prog_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        for base in (
            Path(prog) / "Autodesk" / f"Maya{ver}",
            Path(prog_x86) / "Autodesk" / f"Maya{ver}",
            Path(r"C:\Program Files\Autodesk") / f"Maya{ver}",
            Path(r"D:\Program Files\Autodesk") / f"Maya{ver}",
            Path(rf"D:\LAS\LAD\Maya\Program\{ver}") / f"Maya{ver}",
            Path(rf"D:\Autodesk\Maya{ver}"),
            Path(rf"E:\Program Files\Autodesk\Maya{ver}"),
        ):
            candidates.append(base / "bin" / "mayapy.exe")

    elif platform.system() == "Darwin":
        candidates.extend(
            [
                Path(f"/Applications/Autodesk/maya{ver}/Maya.app/Contents/bin/mayapy"),
                Path(f"/Applications/Autodesk/Maya{ver}/Maya.app/Contents/bin/mayapy"),
            ]
        )
    else:
        candidates.extend(
            [
                Path(f"/usr/autodesk/maya{ver}/bin/mayapy"),
                Path(f"/usr/autodesk/Maya{ver}/bin/mayapy"),
            ]
        )

    seen = set()
    for path in candidates:
        try:
            key = str(path.resolve()) if path.exists() else str(path)
        except OSError:
            key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.is_file():
            return path
    return None


def find_mayapy_beside_executable(executable: Optional[str] = None) -> Optional[Path]:
    """
    When running inside Maya, ``sys.executable`` is often maya.exe.
    mayapy sits next to it in the same ``bin`` folder.
    """
    exe = Path(executable or sys.executable)
    parent = exe.parent
    names = ("mayapy.exe", "mayapy") if platform.system() == "Windows" else ("mayapy",)
    for name in names:
        cand = parent / name
        if cand.is_file():
            return cand
    # Sometimes Script Editor points at a wrapper; walk up one level
    for name in names:
        cand = parent.parent / "bin" / name
        if cand.is_file():
            return cand
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


def verify_imports(
    mayapy: Path,
    *,
    critical: Sequence[Tuple[str, str]] = CRITICAL_IMPORTS,
    extra_paths: Optional[Sequence[Path]] = None,
) -> List[str]:
    """Return pip names that fail to import under mayapy."""
    missing: List[str] = []
    path_setup = ""
    if extra_paths:
        parts = [str(p).replace("\\", "/") for p in extra_paths if p]
        if parts:
            path_setup = (
                "import sys;"
                + "".join(f"sys.path.insert(0, r'{p}');" for p in reversed(parts))
            )
    for mod, pip_name in critical:
        code = f"{path_setup}import {mod}" if path_setup else f"import {mod}"
        proc = _run([str(mayapy), "-c", code])
        if proc.returncode != 0:
            missing.append(pip_name)
    return missing


def verify_imports_in_process(
    *,
    critical: Sequence[Tuple[str, str]] = CHAT_CRITICAL,
) -> List[str]:
    """Check imports in the current interpreter (e.g. Maya Script Editor)."""
    # Ensure vendor is visible
    ensure_vendor_on_sys_path()
    missing: List[str] = []
    for mod, pip_name in critical:
        try:
            __import__(mod)
        except ImportError:
            missing.append(pip_name)
    return missing


def ensure_vendor_on_sys_path() -> Optional[Path]:
    """Prepend project ``.vendor`` to ``sys.path`` if it exists."""
    if VENDOR_DIR.is_dir():
        path = str(VENDOR_DIR.resolve())
        if path not in sys.path:
            sys.path.insert(0, path)
        return VENDOR_DIR
    return None


def _trusted_host_args() -> List[str]:
    args: List[str] = []
    for host in TRUSTED_HOSTS:
        args.extend(["--trusted-host", host])
    return args


def _index_args(index_url: str) -> List[str]:
    if not index_url:
        return []
    return ["-i", index_url, "--trusted-host", index_url.split("//", 1)[-1].split("/", 1)[0]]


def _proxy_env(proxy: Optional[str], *, clear: bool = False) -> dict:
    env = os.environ.copy()
    keys = (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
    )
    if clear:
        for k in keys:
            env.pop(k, None)
        env["NO_PROXY"] = "*"
        env["no_proxy"] = "*"
        return env
    if proxy:
        for k in keys[:4]:
            env[k] = proxy
    return env


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


def ensure_pip(mayapy: Path) -> bool:
    """Make sure ``python -m pip`` works inside mayapy."""
    probe = _run([str(mayapy), "-m", "pip", "--version"])
    if probe.returncode == 0:
        return True
    print("  [提示] mayapy 无 pip，尝试 ensurepip …")
    for args in (
        [str(mayapy), "-m", "ensurepip", "--upgrade"],
        [str(mayapy), "-m", "ensurepip"],
    ):
        proc = _run(args)
        _print_proc(proc)
        if _run([str(mayapy), "-m", "pip", "--version"]).returncode == 0:
            return True
    # Host pip bootstrap get-pip is too heavy; report failure
    print("  [警告] 无法在 mayapy 中启用 pip")
    return False


def upgrade_build_tools(mayapy: Path, proxy: Optional[str]) -> None:
    """Best-effort upgrade of pip/setuptools/wheel (ignore failures)."""
    env = _proxy_env(proxy)
    base = [str(mayapy), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"]
    base.extend(_trusted_host_args())
    if proxy:
        base.extend(["--proxy", proxy])
    for label, index in PIP_INDEXES[:2]:
        cmd = list(base) + _index_args(index)
        print(f"  [工具] 升级 pip/setuptools/wheel via {label} …")
        proc = _run(cmd, env=env, timeout=180)
        if proc.returncode == 0:
            return
    print("  [提示] pip 升级跳过（不影响后续安装）")


def _pip_install_cmd(
    mayapy: Path,
    packages_or_req: Sequence[str],
    *,
    proxy: Optional[str],
    index_url: str = "",
    user: bool = False,
    force: bool = False,
    no_index: bool = False,
    find_links: Optional[Path] = None,
    target: Optional[Path] = None,
) -> List[str]:
    cmd = [str(mayapy), "-m", "pip", "install"]
    if force:
        cmd.append("--force-reinstall")
        cmd.append("--no-cache-dir")
    if user and target is None:
        cmd.append("--user")
    if target is not None:
        cmd.extend(["--target", str(target)])
    if no_index:
        cmd.append("--no-index")
    if find_links is not None:
        cmd.extend(["--find-links", str(find_links)])
    if proxy and not no_index:
        cmd.extend(["--proxy", proxy])
    if not no_index:
        cmd.extend(_trusted_host_args())
        cmd.extend(_index_args(index_url))
    cmd.extend(list(packages_or_req))
    return cmd


def _try_pip_install(
    mayapy: Path,
    packages_or_req: Sequence[str],
    *,
    proxy: Optional[str],
    clear_proxy: bool = False,
    force: bool = False,
    user: bool = False,
    find_links: Optional[Path] = None,
    no_index: bool = False,
    target: Optional[Path] = None,
) -> bool:
    env = _proxy_env(None if clear_proxy else proxy, clear=clear_proxy)
    indexes = (("",),) if no_index else PIP_INDEXES
    for label, index in indexes:
        if not no_index:
            print(f"  · 源: {label}")
        cmd = _pip_install_cmd(
            mayapy,
            packages_or_req,
            proxy=None if clear_proxy else proxy,
            index_url=index,
            user=user,
            force=force,
            no_index=no_index,
            find_links=find_links,
            target=target,
        )
        if clear_proxy and not no_index:
            # Explicit empty proxy arg helps some old pip builds
            if "--proxy" not in cmd:
                cmd = cmd[:4] + ["--proxy", ""] + cmd[4:]
        proc = _run(cmd, env=env)
        _print_proc(proc)
        if proc.returncode == 0:
            return True
        # Permission / read-only site-packages → try --user once
        err = (proc.stderr or "") + (proc.stdout or "")
        if (
            not user
            and target is None
            and not no_index
            and any(
                s in err.lower()
                for s in ("permission", "access is denied", "readonly", "read-only")
            )
        ):
            print("  [提示] 权限不足，改用 --user 安装 …")
            return _try_pip_install(
                mayapy,
                packages_or_req,
                proxy=proxy,
                clear_proxy=clear_proxy,
                force=force,
                user=True,
                find_links=find_links,
                no_index=no_index,
                target=target,
            )
    return False


def pip_install_online(
    mayapy: Path,
    req: Path,
    proxy: Optional[str],
    *,
    force: bool = False,
    only: Optional[Sequence[str]] = None,
) -> bool:
    safe_req = ascii_requirements(req)
    packages = list(only) if only else ["-r", str(safe_req)]

    if _try_pip_install(mayapy, packages, proxy=proxy, force=force):
        return not verify_imports(mayapy)

    # Fallback: install by package names (avoids -r file encoding entirely)
    pkgs = list(only) if only else package_names_from_req(req)
    if not pkgs:
        return False
    if _try_pip_install(mayapy, pkgs, proxy=proxy, force=force):
        return not verify_imports(mayapy)
    return False


def pip_install_packages_individually(
    mayapy: Path,
    packages: Sequence[str],
    proxy: Optional[str],
    *,
    force: bool = False,
) -> List[str]:
    """Install one package at a time; return still-missing pip names."""
    failed: List[str] = []
    for pkg in packages:
        print(f"  [逐包] 安装 {pkg} …")
        ok = _try_pip_install(mayapy, [pkg], proxy=proxy, force=force)
        if not ok and proxy:
            ok = _try_pip_install(
                mayapy, [pkg], proxy=proxy, clear_proxy=True, force=force
            )
        if not ok:
            failed.append(pkg)
            continue
        # Brief pause helps flaky mirrors
        time.sleep(0.2)
    return failed


def pip_install_offline(mayapy: Path, req: Path, wheel_dir: Path, *, force: bool = False) -> bool:
    safe_req = ascii_requirements(req)
    if _try_pip_install(
        mayapy,
        ["-r", str(safe_req)],
        proxy=None,
        force=force,
        no_index=True,
        find_links=wheel_dir,
    ):
        return not verify_imports(mayapy)

    pkgs = package_names_from_req(req)
    if not pkgs:
        return False
    if _try_pip_install(
        mayapy,
        pkgs,
        proxy=None,
        force=force,
        no_index=True,
        find_links=wheel_dir,
    ):
        return not verify_imports(mayapy)
    return False


def download_wheels_with_host_python(req: Path, wheel_dir: Path, py_tag: str) -> bool:
    """Use system/host Python (usually healthier SSL) to fetch wheels for mayapy."""
    wheel_dir.mkdir(parents=True, exist_ok=True)
    host_py = sys.executable
    proxy = detect_http_proxy()
    env = _proxy_env(proxy)

    def _download(only_binary: bool) -> bool:
        for label, index in PIP_INDEXES:
            cmd = [
                host_py,
                "-m",
                "pip",
                "download",
                "-d",
                str(wheel_dir),
                "-r",
                str(ascii_requirements(req)),
                "--python-version",
                py_tag,
            ]
            if only_binary:
                cmd.append("--only-binary=:all:")
            cmd.extend(EXTRA_WHEEL_PKGS)
            cmd.extend(_trusted_host_args())
            cmd.extend(_index_args(index))
            if proxy:
                cmd.extend(["--proxy", proxy])
            print(f"  · host download via {label}{' (binary)' if only_binary else ''} …")
            proc = _run(cmd, env=env, timeout=600)
            _print_proc(proc)
            if proc.returncode == 0 and any(wheel_dir.iterdir()):
                return True
        return False

    if _download(True):
        return True
    print("  [提示] 仅二进制下载失败，改用通用 download …")
    return _download(False)


def install_to_vendor(req: Path, *, force: bool = False) -> bool:
    """
    Install deps into project ``.vendor`` with the host Python.

    Maya Agent prepends this folder to ``sys.path`` on import, so chat can work
    even when mayapy site-packages is unwritable / broken.
    """
    host_py = sys.executable
    if force and VENDOR_DIR.exists():
        print(f"  [vendor] 清理旧目录 {VENDOR_DIR}")
        try:
            shutil.rmtree(VENDOR_DIR)
        except OSError as e:
            print(f"  [警告] 无法清理 vendor: {e}")
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)

    proxy = detect_http_proxy()
    env = _proxy_env(proxy)
    pkgs = package_names_from_req(req)
    if not pkgs:
        pkgs = ["httpx", "requests", "PyYAML"]

    for label, index in PIP_INDEXES:
        cmd = [
            host_py,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--target",
            str(VENDOR_DIR),
            *pkgs,
        ]
        cmd.extend(_trusted_host_args())
        cmd.extend(_index_args(index))
        if proxy:
            cmd.extend(["--proxy", proxy])
        print(f"  [vendor] 安装到 .vendor via {label} …")
        proc = _run(cmd, env=env, timeout=600)
        _print_proc(proc)
        if proc.returncode == 0:
            # Verify in host process with vendor path
            ensure_vendor_on_sys_path()
            missing = verify_imports_in_process(critical=CHAT_CRITICAL)
            if not missing:
                print(f"  [成功] vendor 依赖已就绪 → {VENDOR_DIR}")
                return True
    missing = verify_imports_in_process(critical=CHAT_CRITICAL)
    if missing:
        print(f"  [失败] vendor 仍缺: {', '.join(missing)}")
        return False
    return True


def install_for_mayapy(
    mayapy: Path,
    req: Path | None = None,
    *,
    force: bool = False,
    allow_vendor: bool = True,
) -> bool:
    req = Path(req or REQUIREMENTS)
    if not req.is_file():
        print(f"  [错误] 缺少 {req}")
        return False

    print(f"  mayapy: {mayapy}")
    if not ensure_pip(mayapy):
        print("  [警告] mayapy pip 不可用，将尝试 vendor 兜底")
        return bool(allow_vendor and install_to_vendor(req, force=force))

    extra = [VENDOR_DIR] if VENDOR_DIR.is_dir() else None
    missing = verify_imports(mayapy, extra_paths=extra)
    if not missing and not force:
        print("  [成功] 关键依赖已就绪，跳过安装")
        return True

    if missing:
        print(f"  缺失: {', '.join(missing)}")
    elif force:
        print("  [强制] 重新安装全部依赖")

    proxy = detect_http_proxy()
    if proxy:
        print(f"  检测到代理: {proxy}")

    upgrade_build_tools(mayapy, proxy)

    print("  [步骤 1/4] mayapy pip 在线安装 …")
    if pip_install_online(mayapy, req, proxy, force=force):
        print("  [成功] 在线安装完成")
        return True

    # Direct connection (clear broken IE proxy)
    if proxy:
        print("  [步骤 1b] 直连安装（清空代理）…")
        pkgs = package_names_from_req(req)
        if _try_pip_install(mayapy, ["-r", str(ascii_requirements(req))], proxy=proxy, clear_proxy=True, force=force):
            if not verify_imports(mayapy):
                print("  [成功] 直连安装完成")
                return True
        if pkgs and _try_pip_install(mayapy, pkgs, proxy=proxy, clear_proxy=True, force=force):
            if not verify_imports(mayapy):
                print("  [成功] 直连安装完成")
                return True

    print("  [步骤 2/4] 逐包安装缺失模块 …")
    need = missing or [pip for _mod, pip in CRITICAL_IMPORTS]
    still = pip_install_packages_individually(mayapy, need, proxy, force=force)
    if not verify_imports(mayapy):
        print("  [成功] 逐包安装完成")
        return True
    if still:
        print(f"  仍缺失: {', '.join(still)}")

    print("  [步骤 3/4] 系统 Python 下载 wheel + mayapy 离线安装 …")
    py_tag = mayapy_python_tag(mayapy)
    with tempfile.TemporaryDirectory(prefix="maya_agent_wheels_") as tmp:
        wheel_dir = Path(tmp)
        if download_wheels_with_host_python(req, wheel_dir, py_tag):
            if pip_install_offline(mayapy, req, wheel_dir, force=force):
                print("  [成功] 离线安装完成")
                return True
        else:
            print("  [失败] 无法下载依赖包")

    if allow_vendor:
        print("  [步骤 4/4] 项目 .vendor 兜底（不依赖 mayapy site-packages）…")
        if install_to_vendor(req, force=force):
            # Also confirm mayapy can see vendor when we inject path
            left = verify_imports(mayapy, critical=CHAT_CRITICAL, extra_paths=[VENDOR_DIR])
            if not left:
                print("  [成功] mayapy 可通过 .vendor 导入关键包")
                return True
            # Vendor works in-process; Maya Agent __init__ will inject path
            if not verify_imports_in_process(critical=CHAT_CRITICAL):
                print("  [成功] .vendor 可用（Maya Agent 启动时自动注入）")
                return True

    left = verify_imports(mayapy, extra_paths=[VENDOR_DIR] if VENDOR_DIR.is_dir() else None)
    if left:
        print(f"  [失败] 仍缺失: {', '.join(left)}")
        print(
            f'  可手动执行:\n'
            f'    "{mayapy}" -m pip install --upgrade httpx requests PyYAML\n'
            f"  或重新运行 install.bat / scripts/install_deps.py --force"
        )
        return False
    return True


def install_versions(
    versions: Iterable[str],
    req: Path | None = None,
    *,
    force: bool = False,
    allow_vendor: bool = True,
) -> int:
    req = Path(req or REQUIREMENTS)
    failures = 0
    found_any = False
    for ver in versions:
        print(f"\n=== Maya {ver} 依赖 ===")
        mayapy = find_mayapy(ver)
        if not mayapy:
            print("  [跳过] 未找到 mayapy.exe，仅会写入脚本挂钩")
            continue
        found_any = True
        if not install_for_mayapy(mayapy, req, force=force, allow_vendor=allow_vendor):
            failures += 1

    if not found_any:
        print("\n[警告] 未找到任何 mayapy。")
        print("  将尝试写入项目 .vendor，供 Maya 启动时加载。")
        if allow_vendor and install_to_vendor(req, force=force):
            return 0
        print("  [警告] 依赖未安装。菜单仍可出现，但对话功能需要 httpx。")
        return 1
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
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force reinstall even if imports already succeed",
    )
    parser.add_argument(
        "--no-vendor",
        action="store_true",
        help="Do not fall back to project .vendor directory",
    )
    parser.add_argument(
        "--vendor-only",
        action="store_true",
        help="Only populate project .vendor (skip mayapy)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    req = Path(args.requirements)
    if args.vendor_only:
        ok = install_to_vendor(req, force=args.force)
        return 0 if ok else 1

    versions = list(args.versions)
    if not versions:
        versions = ["2020", "2022", "2023", "2024", "2025", "2026"]

    failures = install_versions(
        versions,
        req,
        force=args.force,
        allow_vendor=not args.no_vendor,
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
