"""
Single source of truth for Maya Agent version: project-root ``VERSION`` file.

Used by package import, install hooks, sync/bump scripts, and (via sync) docs/installer.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

_SCRIPTS = Path(__file__).resolve().parent
PROJECT_ROOT = _SCRIPTS.parent
VERSION_FILE = PROJECT_ROOT / "VERSION"

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[a-zA-Z0-9.\-+]*)?$")


def read_version(root: Optional[Path] = None) -> str:
    """Return version string from ``VERSION`` (fallback ``0.0.0``)."""
    path = (Path(root) if root else PROJECT_ROOT) / "VERSION"
    try:
        line = path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    except (OSError, IndexError):
        return "0.0.0"
    return line or "0.0.0"


def write_version(version: str, root: Optional[Path] = None) -> Path:
    """Write ``VERSION`` file; returns path written."""
    ver = version.strip().lstrip("vV")
    if not _SEMVER_RE.match(ver):
        raise ValueError(f"Invalid version (expect semver like 1.5.6): {version!r}")
    path = (Path(root) if root else PROJECT_ROOT) / "VERSION"
    path.write_text(ver + "\n", encoding="utf-8")
    return path


def sync_version_files(version: Optional[str] = None, root: Optional[Path] = None) -> str:
    """
    Propagate version into pyproject, installer iss, default configs, README, docs.

    ``maya_agent.__init__`` and ``install.py`` read ``VERSION`` at runtime — no copy needed.
    Returns the version that was applied.
    """
    base = Path(root) if root else PROJECT_ROOT
    ver = (version or read_version(base)).strip().lstrip("vV")
    if version:
        write_version(ver, base)
    else:
        # Ensure VERSION file exists / normalized
        write_version(ver, base)

    _sync_pyproject(base / "pyproject.toml", ver)
    _sync_iss(base / "installer" / "MayaAgent.iss", ver)
    _sync_json_app_version(base / "config" / "default_config.json", ver)
    _sync_yaml_app_version(base / "config" / "default_config.yaml", ver)
    _sync_readme(base / "README.md", ver)
    _sync_text_setup_name(base / "installer" / "README.md", ver)
    _sync_text_setup_name(base / "installer" / "VERIFY.md", ver)
    return ver


def _sync_pyproject(path: Path, ver: str) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    new, n = re.subn(
        r'(?m)^(version\s*=\s*")([^"]+)(")',
        rf"\g<1>{ver}\g<3>",
        text,
        count=1,
    )
    if n:
        path.write_text(new, encoding="utf-8")


def _sync_iss(path: Path, ver: str) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    new, n = re.subn(
        r'(?m)^(#define\s+MyAppVersion\s+")([^"]+)(")',
        rf"\g<1>{ver}\g<3>",
        text,
        count=1,
    )
    if n:
        path.write_text(new, encoding="utf-8")


def _sync_json_app_version(path: Path, ver: str) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    # Only the app.version field near the top
    new, n = re.subn(
        r'("version"\s*:\s*")([^"]+)(")',
        rf"\g<1>{ver}\g<3>",
        text,
        count=1,
    )
    if n:
        path.write_text(new, encoding="utf-8")


def _sync_yaml_app_version(path: Path, ver: str) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    new, n = re.subn(
        r'(?m)^(  version:\s*")([^"]+)(")',
        rf"\g<1>{ver}\g<3>",
        text,
        count=1,
    )
    if n:
        path.write_text(new, encoding="utf-8")


def _sync_readme(path: Path, ver: str) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    # Title badge: **v1.5.6**
    text2 = re.sub(r"\*\*v\d+\.\d+\.\d+[^*\s]*\*\*", f"**v{ver}**", text, count=1)
    # Setup exe mentions
    text2 = re.sub(
        r"MayaAgent-Setup-\d+\.\d+\.\d+[^\s`]*\.exe",
        f"MayaAgent-Setup-{ver}.exe",
        text2,
    )
    if text2 != text:
        path.write_text(text2, encoding="utf-8")


def _sync_text_setup_name(path: Path, ver: str) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    text2 = re.sub(
        r"MayaAgent-Setup-\d+\.\d+\.\d+[^\s`]*\.exe",
        f"MayaAgent-Setup-{ver}.exe",
        text,
    )
    if text2 != text:
        path.write_text(text2, encoding="utf-8")
