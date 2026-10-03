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
                self._migrate_ui_scale(user)
            except (json.JSONDecodeError, OSError):
                pass
        secrets_file = user_secrets_path()
        if secrets_file.exists():
            try:
                with open(secrets_file, "r", encoding="utf-8") as f:
                    self._secrets = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._secrets = {}

    def _migrate_ui_scale(self, user: Dict[str, Any]) -> None:
        """Convert legacy ui.font_size to ui.ui_scale when user never saved ui_scale."""
        user_ui = user.get("ui") if isinstance(user, dict) else None
        if not isinstance(user_ui, dict):
            return
        if "ui_scale" in user_ui or "font_size" not in user_ui:
            return
        try:
            scale = int(round(float(user_ui["font_size"]) / 13 * 100))
        except (TypeError, ValueError):
            return
        ui = self._data.setdefault("ui", {})
        ui["ui_scale"] = max(75, min(175, scale))
        ui.pop("font_size", None)

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
            "app": {
                "language": self.get("app.language", "zh-CN"),
            },
            "llm": self._data.get("llm", {}),
            "ui": self._data.get("ui", {}),
            "agent": self._data.get("agent", {}),
            "maya": {
                "auto_undo": self.get("maya.auto_undo", True),
                "confirm_destructive": self.get("maya.confirm_destructive", True),
                "max_tool_rounds": self.get("maya.max_tool_rounds", 30),
            },
            "meshy": {
                "enabled": self.get("meshy.enabled", True),
                "base_url": self.get("meshy.base_url", "https://api.meshy.ai/openapi"),
                "timeout": self.get("meshy.timeout", 60),
                "poll_interval": self.get("meshy.poll_interval", 5),
                "wait_timeout": self.get("meshy.wait_timeout", 600),
                "download_dir": self.get("meshy.download_dir", ""),
                "default_formats": self.get("meshy.default_formats", ["fbx", "glb"]),
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
        from maya_agent.i18n import (
            get_language,
            reply_language_name,
            system_prompt_relpath,
        )
        from maya_agent.utils.paths import project_root

        lang = str(self.get("app.language") or get_language() or "zh-CN")
        configured = self.get("llm.system_prompt_file", "")
        # Always use Chinese system prompt unless user set a custom file.
        rel = "prompts/system_zh.md"
        if configured and configured not in (
            "prompts/system_zh.md",
            "prompts/system_en.md",
            "",
        ):
            rel = configured
        else:
            rel = system_prompt_relpath(lang)

        path = project_root() / "resources" / rel
        if not path.exists():
            path = project_root() / "resources" / "prompts" / "system_zh.md"
        if path.exists():
            text = path.read_text(encoding="utf-8")
        else:
            text = (
                "你是 Maya Agent，面向 Autodesk Maya 游戏管线的 AI 助手。"
            )

        try:
            from maya_agent.tools.meshy_client import filter_system_prompt_meshy

            text = filter_system_prompt_meshy(text)
        except Exception:
            pass

        reply_name = reply_language_name(lang)
        if lang == "zh-CN":
            return text
        if lang == "zh-TW":
            return (
                text
                + "\n\n## 輸出語言\n請使用繁體中文回覆使用者。"
            )
        if lang == "en-US":
            return (
                text
                + "\n\n## Output language\nAlways reply to the user in English."
            )
        return (
            text
            + f"\n\n## Output language\nAlways reply to the user in {reply_name}."
        )


_CONFIG: Optional[Config] = None


def get_config() -> Config:
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = Config()
    return _CONFIG
