"""
Build offline vendor_cache/<abi>/ trees for the commercial installer.

Run on a build machine with network + system Python (not required on end-user PCs):

  python scripts/build_vendor_cache.py
  python scripts/build_vendor_cache.py --tags cp311
  python scripts/build_vendor_cache.py --tags cp39,cp311 --force

Output: <project>/vendor_cache/cp37|cp39|cp311/
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Sequence

_SCRIPTS = Path(__file__).resolve().parent
_PROJECT = _SCRIPTS.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from maya_abi import KNOWN_ABI_TAGS, parse_tags_arg  # noqa: E402

REQUIREMENTS = _PROJECT / "requirements.txt"
VENDOR_CACHE = _PROJECT / "vendor_cache"

# Map ABI dir → pip python_version / implementation for download
# Use pip download with --python-version / --abi / --platform
TAG_PIP_META = {
    "cp37": {"python_version": "37", "abi": "cp37m", "platform": "win_amd64"},
    "cp39": {"python_version": "39", "abi": "cp39", "platform": "win_amd64"},
    "cp311": {"python_version": "311", "abi": "cp311", "platform": "win_amd64"},
}

PIP_INDEXES = (
    ("PyPI", ""),
    ("清华 TUNA", "https://pypi.tuna.tsinghua.edu.cn/simple"),
    ("阿里云", "https://mirrors.aliyun.com/pypi/simple"),
)


def _run(cmd: Sequence[str], *, timeout: float = 600) -> subprocess.CompletedProcess:
    print("  >", " ".join(cmd))
    return subprocess.run(
        list(cmd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _print(proc: subprocess.CompletedProcess) -> None:
    if proc.stdout and proc.stdout.strip():
        print(proc.stdout.rstrip())
    if proc.stderr and proc.stderr.strip():
        print(proc.stderr.rstrip())


def package_names(req: Path) -> List[str]:
    names: List[str] = []
    if not req.is_file():
        return ["httpx", "requests", "PyYAML", "matplotlib"]
    for line in req.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = line.split(";", 1)[0].split("#", 1)[0].strip()
        for sep in ("+=", "==", ">=", "<=", "~=", "!=", ">"):
            if sep in name:
                name = name.split(sep, 1)[0].strip()
                break
        if name:
            names.append(name)
    return names or ["httpx", "requests", "PyYAML", "matplotlib"]


def build_tag(
    tag: str,
    *,
    req: Path,
    cache_root: Path,
    force: bool = False,
    python_exe: Optional[str] = None,
) -> bool:
    meta = TAG_PIP_META.get(tag)
    if meta is None:
        print(f"[跳过] 未知 tag: {tag}")
        return False

    dest = cache_root / tag
    if dest.is_dir() and any(dest.iterdir()) and not force:
        print(f"[跳过] 已存在 {dest} （使用 --force 重建）")
        return True

    py = python_exe or sys.executable
    wheel_dir = cache_root / f"_wheels_{tag}"
    if wheel_dir.exists():
        shutil.rmtree(wheel_dir, ignore_errors=True)
    wheel_dir.mkdir(parents=True, exist_ok=True)

    pkgs = package_names(req)
    # Keep transitive pins sane for mayapy (avoid accidental python-dateutil 4.x)
    constraint = ["python-dateutil>=2.7,<3"]
    print(f"\n=== Building vendor_cache/{tag} ===")
    print(f"  packages: {', '.join(pkgs)}")

    downloaded = False
    for label, index in PIP_INDEXES:
        cmd = [
            py,
            "-m",
            "pip",
            "download",
            "--dest",
            str(wheel_dir),
            "--only-binary=:all:",
            "--python-version",
            meta["python_version"],
            "--abi",
            meta["abi"],
            "--platform",
            meta["platform"],
            *pkgs,
            *constraint,
        ]
        if index:
            host = index.split("//", 1)[-1].split("/", 1)[0]
            cmd.extend(["-i", index, "--trusted-host", host])
        print(f"  [download] {label} …")
        proc = _run(cmd, timeout=900)
        _print(proc)
        if proc.returncode == 0 and any(wheel_dir.iterdir()):
            downloaded = True
            break
        # Fallback without abi pin (some pkgs are py3-none)
        cmd2 = [
            py,
            "-m",
            "pip",
            "download",
            "--dest",
            str(wheel_dir),
            "--python-version",
            meta["python_version"],
            "--platform",
            meta["platform"],
            *pkgs,
            *constraint,
        ]
        if index:
            host = index.split("//", 1)[-1].split("/", 1)[0]
            cmd2.extend(["-i", index, "--trusted-host", host])
        print(f"  [download-loose] {label} …")
        proc2 = _run(cmd2, timeout=900)
        _print(proc2)
        if proc2.returncode == 0 and any(wheel_dir.iterdir()):
            downloaded = True
            break

    if not downloaded:
        print(f"  [失败] 无法下载 wheels for {tag}")
        shutil.rmtree(wheel_dir, ignore_errors=True)
        return False

    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)

    cmd_install = [
        py,
        "-m",
        "pip",
        "install",
        "--no-index",
        "--find-links",
        str(wheel_dir),
        "--target",
        str(dest),
        "--upgrade",
        *pkgs,
        *constraint,
    ]
    print(f"  [install --target] {dest}")
    proc = _run(cmd_install, timeout=600)
    _print(proc)
    shutil.rmtree(wheel_dir, ignore_errors=True)

    if proc.returncode != 0:
        print(f"  [失败] pip install --target {tag}")
        return False

    # Sanity: httpx folder or dist-info present
    markers = list(dest.glob("httpx*")) + list(dest.glob("*/httpx*"))
    if not markers and not (dest / "httpx").exists():
        # still accept if any content
        if not any(dest.iterdir()):
            print(f"  [失败] {dest} 为空")
            return False
    print(f"  [成功] {dest}")
    return True


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build Maya Agent vendor_cache")
    parser.add_argument(
        "--tags",
        default="all",
        help="ABI tags: all | cp311 | cp39,cp311 …",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild even if tag dir exists",
    )
    parser.add_argument(
        "--output",
        default=str(VENDOR_CACHE),
        help="Output vendor_cache root",
    )
    parser.add_argument(
        "--requirements",
        default=str(REQUIREMENTS),
        help="requirements.txt path",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    tags = parse_tags_arg(args.tags)
    # Only build tags we know how to download for
    tags = [t for t in tags if t in TAG_PIP_META]
    if not tags:
        tags = list(KNOWN_ABI_TAGS)

    cache_root = Path(args.output)
    cache_root.mkdir(parents=True, exist_ok=True)
    req = Path(args.requirements)

    print(f"Project: {_PROJECT}")
    print(f"Output:  {cache_root}")
    print(f"Tags:    {', '.join(tags)}")
    print(f"Python:  {sys.executable}")

    ok = 0
    for tag in tags:
        if build_tag(tag, req=req, cache_root=cache_root, force=args.force):
            ok += 1

    print(f"\nDone: {ok}/{len(tags)} tags built under {cache_root}")
    # Write a small manifest for the installer
    manifest = cache_root / "MANIFEST.txt"
    lines = [t for t in tags if (cache_root / t).is_dir()]
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if ok == len(tags) else 1


if __name__ == "__main__":
    raise SystemExit(main())
