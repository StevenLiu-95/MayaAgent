"""Provider registry — create LLM clients from config."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from maya_agent.llm.anthropic_provider import AnthropicProvider
from maya_agent.llm.base import BaseProvider
from maya_agent.llm.cursor_provider import CursorProvider
from maya_agent.llm.google_provider import GoogleProvider
from maya_agent.llm.openai_compat import OpenAICompatProvider
from maya_agent.utils.config import get_config


def list_providers() -> List[Dict[str, Any]]:
    cfg = get_config()
    providers = cfg.get("providers", {}) or {}
    result = []
    for key, conf in providers.items():
        if not conf.get("enabled", True):
            continue
        result.append(
            {
                "id": key,
                "label": conf.get("label", key),
                "models": conf.get("models", []),
                "default_model": conf.get("default_model", ""),
                "base_url": conf.get("base_url", ""),
                "has_key": bool(cfg.get_api_key(key)),
            }
        )
    return result


def create_provider(
    provider_id: Optional[str] = None,
    model: Optional[str] = None,
    **overrides: Any,
) -> BaseProvider:
    cfg = get_config()
    pid = provider_id or cfg.get("llm.active_provider", "deepseek")
    pconf = cfg.get(f"providers.{pid}", {}) or {}
    if not pconf:
        raise ValueError(f"Unknown provider: {pid}")

    api_key = overrides.pop("api_key", None) or cfg.get_api_key(pid)
    if not api_key and pid != "ollama":
        # Ollama often needs no key; others do
        if pid != "custom":
            raise ValueError(
                f"未配置 {pconf.get('label', pid)} 的 API Key。"
                f"请在设置中填写，或设置环境变量 {pconf.get('api_key_env', '')}。"
            )
        api_key = api_key or "EMPTY"

    base_url = overrides.pop("base_url", None) or pconf.get("base_url", "")
    model_name = model or overrides.pop("model", None) or pconf.get("default_model", "")
    temperature = float(overrides.pop("temperature", cfg.get("llm.temperature", 0.3)))
    max_tokens = int(overrides.pop("max_tokens", cfg.get("llm.max_tokens", 4096)))
    timeout = float(overrides.pop("timeout", cfg.get("llm.timeout", 120)))

    common = dict(
        api_key=api_key or "EMPTY",
        base_url=base_url,
        model=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        **overrides,
    )

    if pid == "anthropic":
        return AnthropicProvider(**common)
    if pid == "google":
        return GoogleProvider(**common)
    if pid == "cursor":
        return CursorProvider(
            auth_mode=pconf.get("auth_mode", "auto"),
            **common,
        )
    if pid == "azure_openai":
        return OpenAICompatProvider(
            azure=True,
            api_version=pconf.get("api_version", "2024-06-01"),
            **common,
        )
    # OpenAI-compatible endpoints (and unknown custom ids)
    return OpenAICompatProvider(**common)
