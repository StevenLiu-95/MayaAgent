"""Filesystem path helpers (no third-party imports — safe at plug-in bootstrap)."""

from __future__ import annotations

import os
from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = _PACKAGE_ROOT.parent


def package_root() -> Path:
    return _PACKAGE_ROOT


def project_root() -> Path:
    return _PROJECT_ROOT


def user_config_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    path = base / "MayaAgent"
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_config_path() -> Path:
    return user_config_dir() / "settings.json"


def user_secrets_path() -> Path:
    return user_config_dir() / "secrets.json"


def default_config_json() -> Path:
    return _PROJECT_ROOT / "config" / "default_config.json"


def default_config_yaml() -> Path:
    return _PROJECT_ROOT / "config" / "default_config.yaml"
