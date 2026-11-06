"""Per-turn tool loop guards: readonly dedup + consecutive same-call fuse."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from maya_agent.tools.registry import ToolResult, get_tool


def tool_signature(name: str, arguments_json: str) -> str:
    """Stable signature for name + JSON arguments (sorted keys)."""
    raw = (arguments_json or "").strip() or "{}"
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            norm = json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        else:
            norm = json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        norm = raw
    digest = hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]
    return f"{name or ''}::{digest}"


def _is_readonly_name(name: str) -> bool:
    reg = get_tool(name)
    if reg is not None:
        try:
            from maya_agent.core.agent_mode import is_readonly_tool

            return bool(is_readonly_tool(reg))
        except Exception:
            pass
    # Fallback prefixes when registry not loaded
    prefixes = (
        "get_",
        "list_",
        "check_",
        "preflight_",
        "describe_",
        "lookup_",
        "search_",
        "capture_",
        "read_",
        "web_search",
        "fetch_",
        "generate_chart",
        "verify_",
        "path_info",
    )
    return any(name.startswith(p) or name == p for p in prefixes)


@dataclass
class GuardDecision:
    """Outcome of evaluating one tool call against the turn guard."""

    skip_execute: bool = False
    result: Optional[ToolResult] = None
    break_remaining: bool = False
    deduplicated: bool = False
    fused: bool = False


@dataclass
class TurnLoopGuard:
    """State for one ``MayaAgent.chat`` turn."""

    enabled: bool = True
    consecutive_limit: int = 3
    dedup_readonly: bool = True
    _last_sig: str = ""
    _consecutive: int = 0
    _cache: Dict[str, str] = field(default_factory=dict)
    break_tools: bool = False

    @classmethod
    def from_config(cls, cfg: Any = None) -> "TurnLoopGuard":
        if cfg is None:
            from maya_agent.utils.config import get_config

            cfg = get_config()

        def _get(key: str, default: Any) -> Any:
            try:
                return cfg.get(key, default)
            except Exception:
                return default

        return cls(
            enabled=bool(_get("agent.loop_guard", True)),
            consecutive_limit=max(1, int(_get("agent.consecutive_same_call_limit", 3))),
            dedup_readonly=bool(_get("agent.turn_dedup_readonly", True)),
        )

    def evaluate(self, name: str, arguments_json: str) -> GuardDecision:
        if not self.enabled:
            return GuardDecision()

        if self.break_tools:
            return GuardDecision(
                skip_execute=True,
                break_remaining=True,
                fused=True,
                result=ToolResult(
                    ok=False,
                    error=(
                        "本轮已触发连续相同工具调用熔断，跳过剩余工具。"
                        "请换策略或直接给出结论。"
                    ),
                ),
            )

        sig = tool_signature(name, arguments_json)

        # Consecutive same-call counter (before execute)
        if sig == self._last_sig:
            self._consecutive += 1
        else:
            self._last_sig = sig
            self._consecutive = 1

        if self._consecutive >= self.consecutive_limit:
            self.break_tools = True
            return GuardDecision(
                skip_execute=True,
                break_remaining=True,
                fused=True,
                result=ToolResult(
                    ok=False,
                    error=(
                        f"连续相同工具调用已达上限（{self.consecutive_limit} 次："
                        f"`{name}`）。请换策略或直接给出结论，不要重复同一调用。"
                    ),
                ),
            )

        # Readonly dedup after consecutive check so 3rd identical read still fuses
        if (
            self.dedup_readonly
            and _is_readonly_name(name)
            and sig in self._cache
        ):
            cached = self._cache[sig]
            return GuardDecision(
                skip_execute=True,
                deduplicated=True,
                result=ToolResult(
                    ok=True,
                    message=(
                        f"deduplicated: reused prior result for `{name}` this turn"
                    ),
                    data={"deduplicated": True, "cached_result": cached},
                ),
            )

        return GuardDecision()

    def remember_success(self, name: str, arguments_json: str, result_text: str) -> None:
        """Cache successful readonly tool output for this turn."""
        if not self.enabled or not self.dedup_readonly:
            return
        if not _is_readonly_name(name):
            return
        # Only cache successful-looking payloads
        text = result_text or ""
        if '"ok": false' in text.lower() or '"ok":false' in text.lower():
            return
        sig = tool_signature(name, arguments_json)
        self._cache[sig] = text
