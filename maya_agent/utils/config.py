"""Configuration loader and user settings persistence."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from maya_agent.utils.paths import (
    default_config_json,
    default_config_yaml,
    user_config_dir,
    user_config_path,
    user_secrets_path,
)

__all__ = [
    "Config",
    "get_config",
    "user_config_dir",
    "user_config_path",
    "user_secrets_path",
]


class Config:
    """Merged default + user settings with API key vault."""

    def __init__(self) -> None:
        self._data: Dict[str, Any] = {}
        self._secrets: Dict[str, str] = {}
        self.reload()

    def reload(self) -> None:
        self._data = self._load_default_config()
        # Keep app.version aligned with package
        try:
            from maya_agent import __version__

            self._data.setdefault("app", {})["version"] = __version__
        except Exception:
            pass
        user_file = user_config_path()
        if user_file.exists():
            try:
                with open(user_file, "r", encoding="utf-8") as f:
                    user = json.load(f)
                self._deep_merge(self._data, user)
            except (json.JSONDecodeError, OSError):
                pass
        secrets_file = user_secrets_path()
        if secrets_file.exists():
            try:
                with open(secrets_file, "r", encoding="utf-8") as f:
                    self._secrets = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._secrets = {}

    @staticmethod
    def _load_default_config() -> Dict[str, Any]:
        """Prefer JSON (no third-party deps). Fall back to YAML if PyYAML is present."""
        json_path = default_config_json()
        if json_path.exists():
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
            except (json.JSONDecodeError, OSError):
                pass

        yaml_path = default_config_yaml()
        if yaml_path.exists():
            try:
                import yaml  # optional

                with open(yaml_path, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
            except Exception:
                pass
        return {}

    @staticmethod
    def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> None:
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                Config._deep_merge(base[key], value)
            else:
                base[key] = value

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, dotted: str, value: Any) -> None:
        parts = dotted.split(".")
        node = self._data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    def as_dict(self) -> Dict[str, Any]:
        return copy.deepcopy(self._data)

    def save_user(self) -> None:
        # Persist only user-overridable slices
        payload = {
            "llm": self._data.get("llm", {}),
            "ui": self._data.get("ui", {}),
            "agent": self._data.get("agent", {}),
            "maya": {
                "auto_undo": self.get("maya.auto_undo", True),
                "confirm_destructive": self.get("maya.confirm_destructive", True),
                "max_tool_rounds": self.get("maya.max_tool_rounds", 30),
            },
            "providers": {},
        }
        for name, conf in (self._data.get("providers") or {}).items():
            payload["providers"][name] = {
                "enabled": conf.get("enabled", True),
                "base_url": conf.get("base_url", ""),
                "default_model": conf.get("default_model", ""),
                "models": conf.get("models", []),
                "api_version": conf.get("api_version", ""),
                "vision_policy": conf.get("vision_policy", "auto"),
            }
        with open(user_config_path(), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def reset_user_settings(self) -> None:
        """Drop local settings.json and reload defaults. API keys (secrets.json) are kept."""
        path = user_config_path()
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass
        self.reload()

    def get_api_key(self, provider: str) -> str:
        if provider in self._secrets and self._secrets[provider]:
            return self._secrets[provider]
        env_name = self.get(f"providers.{provider}.api_key_env", "")
        if env_name:
            return os.environ.get(env_name, "")
        return ""

    def set_api_key(self, provider: str, key: str) -> None:
        self._secrets[provider] = key or ""
        with open(user_secrets_path(), "w", encoding="utf-8") as f:
            json.dump(self._secrets, f, ensure_ascii=False, indent=2)

    def system_prompt(self) -> str:
        prompt_rel = self.get("llm.system_prompt_file", "prompts/system_zh.md")
        from maya_agent.utils.paths import project_root

        path = project_root() / "resources" / prompt_rel
        if path.exists():
            return path.read_text(encoding="utf-8")
        return "You are Maya Agent, an expert Autodesk Maya assistant for game development."


_CONFIG: Optional[Config] = None


def get_config() -> Config:
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = Config()
    return _CONFIG
