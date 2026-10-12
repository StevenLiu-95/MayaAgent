"""
Discover Maya user versions and mayapy executables (no Maya UI required).

Used by install.py / install_deps.py / install.bat / doctor.py.

Extra install roots (semicolon- or colon-separated on Unix) via env:
  MAYA_AGENT_MAYAPY_ROOTS
  Example (Windows):
    set MAYA_AGENT_MAYAPY_ROOTS=D:\\LAS\\LAD\\Maya\\Program\\2025\\Maya2025;E:\\Autodesk\\Maya2024
"""

from __future__ import annotations

import argparse
import os
import platform
import sys
from pathlib import Path
from typing import List, Optional, Sequence

try:
    import winreg  # type: ignore
except ImportError:
    winreg = None  # type: ignore

KNOWN_VERSIONS: tuple[str, ...] = ("2020", "2022", "2023", "2024", "2025", "2026")


def documents_dir() -> Path:
    if platform.system() == "Windows":
        return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Documents"
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Preferences" / "Autodesk" / "maya"
    return Path.home() / "maya"


def documents_maya_root() -> Path:
    """Documents/maya on Windows/Linux; Autodesk maya prefs root on Darwin."""
    if platform.system() == "Darwin":
        return documents_dir()
    return documents_dir() / "maya"


def list_maya_user_versions() -> List[str]:
    """Version folders under the Maya user documents tree."""
    versions: List[str] = []
    root = documents_maya_root()
    if not root.is_dir():
        return versions
    for child in root.iterdir():
        if child.is_dir() and child.name.isdigit():
            versions.append(child.name)
    return sorted(versions)


def _env_extra_roots() -> List[Path]:
    raw = (os.environ.get("MAYA_AGENT_MAYAPY_ROOTS") or "").strip()
    if not raw:
        return []
    sep = ";" if platform.system() == "Windows" else (";" if ";" in raw else ":")
    out: List[Path] = []
    for part in raw.split(sep):
        part = part.strip().strip('"')
        if part:
            out.append(Path(part))
    return out


def _registry_install_root(version: str) -> Optional[Path]:
    if platform.system() != "Windows" or winreg is None:
        return None
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            rf"SOFTWARE\Autodesk\Maya\{version}\Setup\InstallPath",
        )
        try:
            loc, _ = winreg.QueryValueEx(key, "MAYA_INSTALL_LOCATION")
        finally:
            winreg.CloseKey(key)
        return Path(str(loc))
    except OSError:
        return None


def _candidate_mayapy_paths(version: str) -> List[Path]:
    ver = str(version).strip()
    candidates: List[Path] = []

    reg = _registry_install_root(ver)
    if reg is not None:
        candidates.extend(
            [
                reg / "bin" / "mayapy.exe",
                reg / "bin" / "mayapy",
            ]
        )

    if platform.system() == "Windows":
        prog = os.environ.get("ProgramFiles", r"C:\Program Files")
        prog_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        bases = [
            Path(prog) / "Autodesk" / f"Maya{ver}",
            Path(prog_x86) / "Autodesk" / f"Maya{ver}",
            Path(r"C:\Program Files\Autodesk") / f"Maya{ver}",
            Path(r"D:\Program Files\Autodesk") / f"Maya{ver}",
            Path(rf"D:\Autodesk\Maya{ver}"),
            Path(rf"E:\Program Files\Autodesk\Maya{ver}"),
        ]
        for extra in _env_extra_roots():
            # Allow either .../Maya2025 or .../Maya2025/bin
            name = extra.name.lower()
            if name == "bin":
                bases.append(extra.parent)
            elif name == f"maya{ver}".lower() or extra.name == ver:
                bases.append(extra)
            else:
                # Treat as parent that may contain Maya{ver}
                bases.append(extra)
                bases.append(extra / f"Maya{ver}")
                bases.append(extra / ver / f"Maya{ver}")
        for base in bases:
            candidates.append(base / "bin" / "mayapy.exe")
    elif platform.system() == "Darwin":
        candidates.extend(
            [
                Path(f"/Applications/Autodesk/maya{ver}/Maya.app/Contents/bin/mayapy"),
                Path(f"/Applications/Autodesk/Maya{ver}/Maya.app/Contents/bin/mayapy"),
            ]
        )
        for extra in _env_extra_roots():
            candidates.append(extra / "bin" / "mayapy")
            candidates.append(extra / "mayapy")
    else:
        candidates.extend(
            [
                Path(f"/usr/autodesk/maya{ver}/bin/mayapy"),
                Path(f"/usr/autodesk/Maya{ver}/bin/mayapy"),
            ]
        )
        for extra in _env_extra_roots():
            candidates.append(extra / "bin" / "mayapy")
            candidates.append(extra / "mayapy")

    return candidates


def find_mayapy(version: str) -> Optional[Path]:
    """Locate mayapy.exe / mayapy for a Maya version."""
    seen = set()
    for path in _candidate_mayapy_paths(version):
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
    for name in names:
        cand = parent.parent / "bin" / name
        if cand.is_file():
            return cand
    return None


def discover_maya_versions(
    *,
    known: Sequence[str] | None = None,
    require_mayapy: bool = False,
) -> List[str]:
    """
    Versions to install for: user docs folders ∪ installs with mayapy.

    ``require_mayapy=True`` keeps only versions where mayapy was found.
    """
    probe = list(known or KNOWN_VERSIONS)
    found: set[str] = set(list_maya_user_versions())

    for ver in probe:
        if find_mayapy(ver) is not None:
            found.add(ver)
        elif platform.system() == "Windows" and winreg is not None:
            if _registry_install_root(ver) is not None:
                found.add(ver)
        # User docs already covered; also mark if env root looks version-specific
        for extra in _env_extra_roots():
            text = str(extra).replace("\\", "/")
            if ver in text.split("/") or extra.name == f"Maya{ver}" or extra.name == ver:
                found.add(ver)

    ordered = [v for v in probe if v in found]
    # Include unexpected user versions not in KNOWN_VERSIONS
    for v in sorted(found):
        if v not in ordered:
            ordered.append(v)

    if require_mayapy:
        ordered = [v for v in ordered if find_mayapy(v) is not None]
    return ordered


def is_valid_project_root(root: Path | str) -> bool:
    path = Path(root)
    return (path / "maya_agent" / "__init__.py").is_file()


def version_junction_path(version: str) -> Path:
    if platform.system() == "Darwin":
        return documents_maya_root() / version / "MayaAgent"
    return documents_maya_root() / version / "MayaAgent"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Discover Maya versions / mayapy")
    parser.add_argument(
        "--print-versions",
        action="store_true",
        help="Print space-separated Maya versions (for install.bat)",
    )
    parser.add_argument(
        "--require-mayapy",
        action="store_true",
        help="Only list versions that have a mayapy executable",
    )
    parser.add_argument(
        "--maya-version",
        default="",
        help="If set with --print-mayapy, print that version's mayapy path",
    )
    parser.add_argument(
        "--print-mayapy",
        action="store_true",
        help="Print mayapy path for --maya-version",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.print_mayapy:
        ver = args.maya_version or ""
        if not ver:
            print("missing --maya-version", file=sys.stderr)
            return 2
        path = find_mayapy(ver)
        if path is None:
            return 1
        print(path)
        return 0

    versions = discover_maya_versions(require_mayapy=args.require_mayapy)
    if args.print_versions:
        if not versions:
            return 1
        print(" ".join(versions))
        return 0

    # Default: human-readable summary
    print(f"Documents Maya root: {documents_maya_root()}")
    print(f"Versions: {', '.join(versions) if versions else '(none)'}")
    for ver in versions:
        mp = find_mayapy(ver)
        print(f"  {ver}: mayapy={mp or '(not found)'}")
    return 0 if versions else 1


if __name__ == "__main__":
    raise SystemExit(main())
