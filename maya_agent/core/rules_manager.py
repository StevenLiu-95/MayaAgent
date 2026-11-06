"""User Rules — persistent custom instructions injected into the system prompt."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from maya_agent.utils.paths import project_rules_dir, user_rules_path

_ui_rules_cache: Optional[List[Dict[str, Any]]] = None


def _new_rule(title: str = "", content: str = "", enabled: bool = True) -> Dict[str, Any]:
    return {
        "id": uuid.uuid4().hex[:12],
        "title": title,
        "content": content,
        "enabled": enabled,
        "created_at": time.time(),
        "source": "ui",
    }


def _load_ui_rules() -> List[Dict[str, Any]]:
    path = user_rules_path()
    if not path.is_file():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def _save_ui_rules(rules: List[Dict[str, Any]]) -> None:
    path = user_rules_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rules, f, ensure_ascii=False, indent=2)


def get_rules_dir() -> Path:
    return project_rules_dir()


def ensure_rules_dir() -> Path:
    path = project_rules_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _scan_file_rules() -> List[Dict[str, Any]]:
    rules_dir = project_rules_dir()
    if not rules_dir.is_dir():
        return []
    result: List[Dict[str, Any]] = []
    for ext in ("*.md", "*.txt"):
        for f in sorted(rules_dir.glob(ext)):
            if f.name.startswith("_"):
                continue
            try:
                content = f.read_text(encoding="utf-8").strip()
            except Exception:
                continue
            if not content:
                continue
            result.append(
                {
                    "id": f"file:{f.name}",
                    "title": f.stem,
                    "content": content,
                    "enabled": True,
                    "source": "file",
                    "file_path": str(f),
                }
            )
    return result


def get_all_rules(force_reload: bool = False) -> List[Dict[str, Any]]:
    global _ui_rules_cache
    if force_reload or _ui_rules_cache is None:
        _ui_rules_cache = _load_ui_rules()
    ui_rules = []
    for r in _ui_rules_cache:
        rule = dict(r)
        rule.setdefault("source", "ui")
        ui_rules.append(rule)
    return ui_rules + _scan_file_rules()


def get_ui_rules() -> List[Dict[str, Any]]:
    global _ui_rules_cache
    if _ui_rules_cache is None:
        _ui_rules_cache = _load_ui_rules()
    return list(_ui_rules_cache)


def add_rule(title: str = "", content: str = "") -> Dict[str, Any]:
    global _ui_rules_cache
    if _ui_rules_cache is None:
        _ui_rules_cache = _load_ui_rules()
    rule = _new_rule(title=title, content=content, enabled=True)
    _ui_rules_cache.append(rule)
    _save_ui_rules(_ui_rules_cache)
    return rule


def update_rule(rule_id: str, **kwargs: Any) -> bool:
    global _ui_rules_cache
    if _ui_rules_cache is None:
        _ui_rules_cache = _load_ui_rules()
    for r in _ui_rules_cache:
        if r.get("id") == rule_id:
            for k in ("title", "content", "enabled"):
                if k in kwargs:
                    r[k] = kwargs[k]
            _save_ui_rules(_ui_rules_cache)
            return True
    return False


def delete_rule(rule_id: str) -> bool:
    global _ui_rules_cache
    if _ui_rules_cache is None:
        _ui_rules_cache = _load_ui_rules()
    before = len(_ui_rules_cache)
    _ui_rules_cache = [r for r in _ui_rules_cache if r.get("id") != rule_id]
    if len(_ui_rules_cache) < before:
        _save_ui_rules(_ui_rules_cache)
        return True
    return False


def save_all_ui_rules(rules: List[Dict[str, Any]]) -> None:
    global _ui_rules_cache
    cleaned: List[Dict[str, Any]] = []
    for r in rules or []:
        if not isinstance(r, dict):
            continue
        item = dict(r)
        item["source"] = "ui"
        item.setdefault("id", uuid.uuid4().hex[:12])
        item.setdefault("enabled", True)
        cleaned.append(item)
    _ui_rules_cache = cleaned
    _save_ui_rules(_ui_rules_cache)


def reload_rules() -> None:
    global _ui_rules_cache
    _ui_rules_cache = None


def get_rules_for_prompt(max_chars: Optional[int] = None) -> str:
    """
    Merge enabled rules into a ``<user_rules>`` block for the system prompt.

    Returns empty string when nothing is enabled.
    """
    from maya_agent.utils.config import get_config

    cfg = get_config()
    if not bool(cfg.get("agent.user_rules_enabled", True)):
        return ""
    if max_chars is None:
        max_chars = int(cfg.get("agent.user_rules_max_chars", 8000) or 8000)
    max_chars = max(500, int(max_chars))

    enabled = [r for r in get_all_rules() if r.get("enabled", True)]
    if not enabled:
        return ""

    parts: List[str] = []
    for r in enabled:
        title = str(r.get("title") or "").strip()
        content = str(r.get("content") or "").strip()
        if not content:
            continue
        if title:
            parts.append(f"## {title}\n{content}")
        else:
            parts.append(content)
    if not parts:
        return ""

    body = "\n\n".join(parts)
    header = (
        "<user_rules>\n"
        "The following are custom rules defined by the user. "
        "You MUST follow them in every response "
        "(unless they conflict with Ask/Plan safety or tool allowlists).\n\n"
    )
    footer = "\n</user_rules>"
    overhead = len(header) + len(footer)
    budget = max(200, max_chars - overhead)
    if len(body) > budget:
        body = body[: budget - 40].rstrip() + "\n…[user rules truncated]"
    return header + body + footer
