#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Install MayaAgent Local Runtime (isolated Python + torch CUDA + local_runtime).

Does NOT download model weights — those are fetched from the MayaAgent UI.

Usage:
  python scripts/install_local_runtime.py
  python scripts/install_local_runtime.py --repair
  python scripts/install_local_runtime.py --uninstall
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import venv
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _progress(pct: int, message: str = "") -> None:
    """Machine-readable progress for MayaAgent UI (PROGRESS <0-100> <msg>)."""
    pct = max(0, min(100, int(pct)))
    msg = (message or "").replace("\n", " ").strip()
    print(f"PROGRESS {pct} {msg}", flush=True)
    if msg:
        print(f"[install] ({pct}%) {msg}", flush=True)


def _subprogress(pct: int, message: str = "") -> None:
    """
    Sub-step progress (e.g. single wheel download) for a secondary UI bar.
    SUBPROGRESS <0-100> <msg>
    """
    pct = max(0, min(100, int(pct)))
    msg = (message or "").replace("\n", " ").strip()
    print(f"SUBPROGRESS {pct} {msg}", flush=True)


def _local_appdata() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))


def install_root() -> Path:
    return _local_appdata() / "MayaAgent" / "local_runtime"


def user_config_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "MayaAgent"


def detect_nvidia() -> Tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if proc.returncode == 0 and (proc.stdout or "").strip():
            return True, (proc.stdout or "").strip().splitlines()[0]
    except Exception as e:
        return False, str(e)
    return False, "nvidia-smi not found or failed"


def venv_python(root: Path) -> Path:
    if os.name == "nt":
        return root / "venv" / "Scripts" / "python.exe"
    return root / "venv" / "bin" / "python"


def ensure_venv(root: Path) -> Path:
    vdir = root / "venv"
    py = venv_python(root)
    if py.is_file():
        _progress(18, f"复用已有 venv: {vdir}")
        return py
    _progress(12, f"创建 venv: {vdir}")
    print(f"[install] creating venv at {vdir}", flush=True)
    venv.create(str(vdir), with_pip=True, clear=False)
    if not py.is_file():
        raise RuntimeError(f"venv python missing: {py}")
    return py


def pip_install(
    py: Path,
    args: List[str],
    *,
    progress_start: Optional[int] = None,
    progress_end: Optional[int] = None,
    phase_label: str = "",
) -> None:
    """
    Run pip with streamed stdout. When progress_start/end are set, map pip's
    download percentage into that band so the UI does not appear stuck on large wheels.
    """
    # `raw` progress works better when stdout is piped (no TTY).
    cmd = [
        str(py),
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--progress-bar",
        "raw",
        *args,
    ]
    print("[install]", " ".join(cmd), flush=True)
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PIP_PROGRESS_BAR"] = "raw"

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
    )
    assert proc.stdout is not None
    last_emit = -1
    last_sub = -1
    pct_re = re.compile(r"(\d{1,3})%")
    # pip raw: "Progress 1234567 of 2449000000"
    bytes_re = re.compile(
        r"(?i)^(?:progress)\s+(\d+)\s+(?:of|/)\s+(\d+)\s*$"
    )
    bytes_re_loose = re.compile(
        r"(?i)(?:progress|downloading).*?(\d+)\s*(?:of|/)\s*(\d+)"
    )
    mb_re = re.compile(r"(?i)(\d+(?:\.\d+)?)\s*MB")

    def _emit_download(pip_pct: int, done: int = 0, total: int = 0) -> None:
        nonlocal last_emit, last_sub
        pip_pct = max(0, min(100, int(pip_pct)))
        if total > 0:
            sub_msg = (
                f"{done / 1e6:.1f} / {total / 1e6:.1f} MB  ({pip_pct}%)"
            )
        else:
            sub_msg = f"{pip_pct}%"
        if last_sub < 0 or pip_pct - last_sub >= 1 or pip_pct >= 100:
            _subprogress(pip_pct, sub_msg)
            last_sub = pip_pct
        if progress_start is not None and progress_end is not None:
            lo, hi = int(progress_start), int(progress_end)
            mapped = lo + int((hi - lo) * pip_pct / 100)
            msg = f"{phase_label or 'pip'} {pip_pct}%"
            if last_emit < 0 or mapped - last_emit >= 1 or mapped >= hi:
                _progress(mapped, msg)
                last_emit = mapped

    for raw in proc.stdout:
        line = raw.rstrip("\r\n")
        stripped = line.strip()
        # Don't flood the UI log with every 256KB Progress tick
        is_byte_progress = bool(bytes_re.match(stripped))
        if stripped and not is_byte_progress:
            print(line, flush=True)

        if progress_start is None or progress_end is None:
            continue

        lo, hi = int(progress_start), int(progress_end)
        bm = bytes_re.match(stripped) or bytes_re_loose.search(
            stripped.replace(",", "")
        )
        if bm:
            done, total = int(bm.group(1)), int(bm.group(2))
            if total > 0:
                _emit_download(int(done * 100 / total), done, total)
            continue

        m = pct_re.search(stripped)
        if m:
            _emit_download(int(m.group(1)))
            continue

        if "Downloading" in line or "downloading" in line:
            size_m = mb_re.search(line)
            if size_m and last_sub < 0:
                _subprogress(0, f"开始下载（约 {size_m.group(1)} MB）…")
                _progress(lo, f"{phase_label or 'pip'} 下载中（约 {size_m.group(1)} MB）…")
                last_emit = lo

    code = proc.wait()
    if last_sub >= 0:
        _subprogress(100, "下载/安装步骤完成")
    if code != 0:
        raise RuntimeError(f"pip failed ({code}): {cmd}")


def install_torch(py: Path) -> None:
    # CUDA 12.1 wheels — widely compatible; users with older drivers may need repair.
    index = "https://download.pytorch.org/whl/cu121"
    _progress(
        35,
        "安装 PyTorch (CUDA)：正在下载约 2.5GB 安装包，网络较慢时会长时间停在此阶段",
    )
    print(f"[install] torch from {index}", flush=True)
    print(
        "[install] 提示: torch wheel ≈ 2.4GB，下载期间进度会随 pip 更新；请勿关闭窗口。",
        flush=True,
    )
    pip_install(
        py,
        [
            "torch",
            "torchvision",
            "torchaudio",
            "--index-url",
            index,
        ],
        progress_start=35,
        progress_end=64,
        phase_label="下载/安装 PyTorch (CUDA)",
    )
    _progress(65, "PyTorch 安装完成")


def write_discovery(py: Path, report: Dict[str, Any]) -> None:
    path = user_config_dir() / "local_runtime.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    # Server rewrites this on start; here we record install location.
    payload = {
        "host": "127.0.0.1",
        "port": 8770,
        "token": "",
        "pid": 0,
        "base_url": "",
        "api_prefix": "/v1",
        "version": report.get("version", "1.0.0"),
        "python_exe": str(py),
        "install_root": str(install_root()),
        "installed": True,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def uninstall() -> int:
    root = install_root()
    print(f"[uninstall] removing {root}")
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    disc = user_config_dir() / "local_runtime.json"
    if disc.is_file():
        try:
            disc.unlink()
        except OSError:
            pass
    print("[uninstall] done")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Install MayaAgent Local Runtime")
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--skip-torch", action="store_true")
    parser.add_argument("--cpu", action="store_true", help="Install CPU torch only")
    args = parser.parse_args(argv)

    if args.uninstall:
        _progress(10, "卸载 Local Runtime")
        code = uninstall()
        _progress(100, "卸载完成" if code == 0 else "卸载失败")
        return code

    # Force line-buffered stdout for UI streaming
    try:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except Exception:
        pass

    _progress(2, "开始安装 Local Runtime")
    print("=== MayaAgent Local Runtime Installer ===", flush=True)
    print(f"platform: {platform.platform()}", flush=True)
    print(f"project:  {PROJECT_ROOT}", flush=True)

    _progress(5, "检测 NVIDIA GPU")
    ok_gpu, gpu_info = detect_nvidia()
    print(f"nvidia:   {'OK — ' + gpu_info if ok_gpu else 'MISSING — ' + gpu_info}", flush=True)
    if not ok_gpu and not args.cpu:
        print(
            "[error] 未检测到 NVIDIA GPU / 驱动。本地大模型推理需要 CUDA。\n"
            "若仅需验证安装流程可加 --cpu（极慢且多数后端不可用）。",
            flush=True,
        )
        _progress(100, "安装中止：无 GPU")
        return 2

    root = install_root()
    root.mkdir(parents=True, exist_ok=True)
    try:
        py = ensure_venv(root)
        _progress(22, "升级 pip / setuptools / wheel")
        pip_install(py, ["pip", "setuptools", "wheel"])
        if not args.skip_torch:
            if args.cpu or not ok_gpu:
                _progress(35, "安装 PyTorch (CPU)")
                pip_install(
                    py,
                    ["torch", "torchvision", "torchaudio"],
                    progress_start=35,
                    progress_end=64,
                    phase_label="下载/安装 PyTorch (CPU)",
                )
                _progress(65, "PyTorch 安装完成")
            else:
                install_torch(py)
        # Runtime deps
        req = PROJECT_ROOT / "local_runtime" / "requirements.txt"
        if req.is_file():
            _progress(70, "安装 local_runtime 依赖")
            pip_install(
                py,
                ["-r", str(req)],
                progress_start=70,
                progress_end=77,
                phase_label="安装 runtime 依赖",
            )
        # Write pth file
        _progress(78, "写入 runtime 路径")
        if os.name == "nt":
            site_packages = root / "venv" / "Lib" / "site-packages"
        else:
            lib = root / "venv" / "lib"
            candidates = list(lib.glob("python3.*"))
            site_packages = (candidates[0] / "site-packages") if candidates else lib / "site-packages"
        site_packages.mkdir(parents=True, exist_ok=True)
        pth = site_packages / "mayaagent_local_runtime.pth"
        pth.write_text(str(PROJECT_ROOT) + "\n", encoding="utf-8")

        # Optional generative extras (best-effort)
        optional = (
            "trimesh",
            "huggingface_hub",
            "Pillow",
            "diffusers",
            "transformers",
            "accelerate",
        )
        for i, pkg in enumerate(optional):
            pct = 80 + int(15 * i / max(1, len(optional)))
            _progress(pct, f"安装可选依赖 {pkg}")
            try:
                pip_install(py, [pkg])
            except Exception as e:
                print(f"[warn] optional package {pkg}: {e}", flush=True)

        _progress(96, "写入 discovery / install report")
        report = {
            "ok": True,
            "install_root": str(root),
            "python_exe": str(py),
            "nvidia": gpu_info,
            "cuda_requested": bool(ok_gpu and not args.cpu),
            "project_root": str(PROJECT_ROOT),
            "version": "1.0.0",
        }
        (root / "install_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        write_discovery(py, report)
        print("=== Install Report ===", flush=True)
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
        print(
            "\n权重仍需在 MayaAgent「模型 → 本地模型」中手动下载。"
            "\n启动: 菜单 Maya Agent → 启动 Local Runtime，或面板内启动。",
            flush=True,
        )
        _progress(100, "安装完成")
        return 0
    except Exception as e:
        print(f"[error] {e}", flush=True)
        report = {"ok": False, "error": str(e), "install_root": str(root)}
        try:
            (root / "install_report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass
        _progress(100, f"安装失败: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
