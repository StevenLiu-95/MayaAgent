"""UI internationalization for Maya Agent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

__all__ = [
    "SUPPORTED_LANGUAGES",
    "get_language",
    "init_from_config",
    "list_languages",
    "set_language",
    "t",
]

# (code, native_label)
SUPPORTED_LANGUAGES: Tuple[Tuple[str, str], ...] = (
    ("zh-CN", "简体中文"),
    ("zh-TW", "繁體中文"),
    ("en-US", "English"),
    ("ja-JP", "日本語"),
    ("ko-KR", "한국어"),
    ("fr-FR", "Français"),
    ("de-DE", "Deutsch"),
    ("es-ES", "Español"),
    ("pt-BR", "Português"),
    ("ru-RU", "Русский"),
)

_DEFAULT_LANG = "zh-CN"
_FALLBACK_LANG = "en-US"

_lang: str = _DEFAULT_LANG
_catalogs: Dict[str, Dict[str, str]] = {}


def _locales_dir() -> Path:
    # maya_agent/i18n/__init__.py -> project root / resources / locales
    return Path(__file__).resolve().parents[2] / "resources" / "locales"


def _load_catalog(code: str) -> Dict[str, str]:
    if code in _catalogs:
        return _catalogs[code]
    path = _locales_dir() / f"{code}.json"
    data: Dict[str, str] = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = {str(k): str(v) for k, v in raw.items() if isinstance(v, str)}
        except (json.JSONDecodeError, OSError):
            data = {}
    _catalogs[code] = data
    return data


def list_languages() -> List[Tuple[str, str]]:
    return list(SUPPORTED_LANGUAGES)


def get_language() -> str:
    return _lang


def set_language(code: str) -> str:
    """Set active UI language. Unknown codes fall back to zh-CN."""
    global _lang
    supported = {c for c, _ in SUPPORTED_LANGUAGES}
    _lang = code if code in supported else _DEFAULT_LANG
    _load_catalog(_lang)
    if _lang != _FALLBACK_LANG:
        _load_catalog(_FALLBACK_LANG)
    if _lang != _DEFAULT_LANG:
        _load_catalog(_DEFAULT_LANG)
    return _lang


def init_from_config() -> str:
    from maya_agent.utils.config import get_config

    return set_language(str(get_config().get("app.language", _DEFAULT_LANG) or _DEFAULT_LANG))


def t(key: str, default: Optional[str] = None, **kwargs) -> str:
    """Translate key for the active language. Falls back to en-US, then zh-CN, then key."""
    for code in (_lang, _FALLBACK_LANG, _DEFAULT_LANG):
        catalog = _load_catalog(code)
        text = catalog.get(key)
        if text:
            break
    else:
        text = default if default is not None else key
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, ValueError, IndexError):
            pass
    return text


def reply_language_name(code: Optional[str] = None) -> str:
    """Human-readable language name for system-prompt instructions."""
    code = code or _lang
    return {
        "zh-CN": "简体中文",
        "zh-TW": "繁體中文",
        "en-US": "English",
        "ja-JP": "日本語",
        "ko-KR": "한국어",
        "fr-FR": "Français",
        "de-DE": "Deutsch",
        "es-ES": "Español",
        "pt-BR": "Português (Brasil)",
        "ru-RU": "Русский",
    }.get(code, "English")


def system_prompt_relpath(code: Optional[str] = None) -> str:
    """Relative prompt path under resources/ for the given UI language."""
    code = code or _lang
    if code in ("zh-CN", "zh-TW"):
        return "prompts/system_zh.md"
    return "prompts/system_en.md"
