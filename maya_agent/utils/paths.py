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


def default_agent_temp_root() -> Path:
    """Sibling of the MayaAgent project: .../MayaAgentTempFile."""
    return _PROJECT_ROOT.parent / "MayaAgentTempFile"


def agent_temp_root() -> Path:
    """
    Unified temp root for chat images, file tools, Meshy downloads,
    viewport captures, and untitled scene sessions.

    Reads ``ui.temp_dir`` from config when set; otherwise
    ``default_agent_temp_root()``.
    """
    raw = ""
    try:
        from maya_agent.utils.config import get_config

        raw = str(get_config().get("ui.temp_dir") or "").strip()
    except Exception:
        raw = ""
    if raw:
        path = Path(os.path.expandvars(os.path.expanduser(raw)))
    else:
        path = default_agent_temp_root()
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return path


def agent_temp_subdir(name: str) -> Path:
    """Ensure and return a named subdirectory under ``agent_temp_root()``."""
    path = agent_temp_root() / name
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return path


def default_models_root() -> Path:
    """Sibling of the MayaAgent project: .../MayaAgentModels."""
    return _PROJECT_ROOT.parent / "MayaAgentModels"


def models_root() -> Path:
    """
    Root directory for manually downloaded local model weights.

    Reads ``local.models_dir`` when set; otherwise ``default_models_root()``.
    """
    raw = ""
    try:
        from maya_agent.utils.config import get_config

        raw = str(get_config().get("local.models_dir") or "").strip()
    except Exception:
        raw = ""
    if raw:
        path = Path(os.path.expandvars(os.path.expanduser(raw)))
    else:
        path = default_models_root()
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return path


def local_runtime_install_root() -> Path:
    """Default install location for the isolated Local Runtime venv."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "MayaAgent" / "local_runtime"
