"""Compress older tool results before sending history to the LLM."""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from maya_agent.llm.base import ChatMessage

_TRUNC_MARK = "\n…[tool result truncated for context]…\n"
_ERROR_SOFT_LIMIT = 2500


def estimate_chars_tokens(text: str) -> int:
    """Rough token heuristic (~3 chars/token). For logging only."""
    if not text:
        return 0
    return max(1, len(text) // 3)


def _looks_like_error(content: str) -> bool:
    c = content or ""
    low = c.lower()
    if '"ok": false' in low or '"ok":false' in low:
        return True
    if '"error"' in low and ("true" in low or len(c) < 4000):
        # Prefer keeping error payloads
        if '"error": ""' in low or '"error":""' in low:
            return False
        return True
    return False


def _truncate_middle(content: str, head: int, tail: int) -> str:
    if head < 0:
        head = 0
    if tail < 0:
        tail = 0
    if head + tail >= len(content):
        return content
    return content[:head] + _TRUNC_MARK + content[-tail:]


def _compress_tool_content(
    content: str,
    *,
    soft_limit: int,
    head_chars: int,
    tail_chars: int,
    error_limit: int = _ERROR_SOFT_LIMIT,
) -> str:
    text = content or ""
    limit = error_limit if _looks_like_error(text) else soft_limit
    if len(text) <= limit:
        return text
    return _truncate_middle(text, head_chars, tail_chars)


def _group_messages(rest: List[ChatMessage]) -> List[List[ChatMessage]]:
    """Split non-system messages into groups; assistant+tools stay together."""
    groups: List[List[ChatMessage]] = []
    i = 0
    while i < len(rest):
        msg = rest[i]
        if msg.role == "assistant" and msg.tool_calls:
            group = [msg]
            i += 1
            while i < len(rest) and rest[i].role == "tool":
                group.append(rest[i])
                i += 1
            groups.append(group)
        elif msg.role == "tool":
            # orphan — keep as its own group so we can still shrink it
            groups.append([msg])
            i += 1
        else:
            groups.append([msg])
            i += 1
    return groups


def compress_messages_for_llm(
    messages: List[ChatMessage],
    *,
    enabled: bool = True,
    protect_recent_groups: int = 2,
    soft_limit: int = 1200,
    head_chars: int = 600,
    tail_chars: int = 200,
    strip_old_images: bool = True,
    keep_recent_image_users: int = 1,
) -> List[ChatMessage]:
    """
    Return a deep-ish copy with older tool payloads shrunk.

    Never mutates system / user / assistant text or tool_calls structure;
    only shortens ``role=tool`` content for groups older than the protect window.
    """
    if not enabled or not messages:
        return list(messages)

    protect = max(0, int(protect_recent_groups))
    system = [m for m in messages if m.role == "system"]
    rest = [m for m in messages if m.role != "system"]
    groups = _group_messages(rest)
    n = len(groups)
    protect_start = max(0, n - protect)

    out_rest: List[ChatMessage] = []
    for gi, group in enumerate(groups):
        compress_tools = gi < protect_start
        for msg in group:
            if msg.role == "tool" and compress_tools:
                out_rest.append(
                    ChatMessage(
                        role="tool",
                        content=_compress_tool_content(
                            msg.content or "",
                            soft_limit=soft_limit,
                            head_chars=head_chars,
                            tail_chars=tail_chars,
                        ),
                        name=msg.name,
                        tool_call_id=msg.tool_call_id,
                    )
                )
            else:
                # Shallow copy message; may clear images below
                out_rest.append(
                    ChatMessage(
                        role=msg.role,
                        content=msg.content or "",
                        name=msg.name,
                        tool_call_id=msg.tool_call_id,
                        tool_calls=copy.deepcopy(msg.tool_calls)
                        if msg.tool_calls
                        else None,
                        images=list(msg.images) if msg.images else None,
                    )
                )

    if strip_old_images and keep_recent_image_users >= 0:
        # Keep images only on the last N user messages that have images.
        imaged_idxs = [
            i
            for i, m in enumerate(out_rest)
            if m.role == "user" and m.images
        ]
        keep = set(imaged_idxs[-keep_recent_image_users:]) if keep_recent_image_users else set()
        for i, m in enumerate(out_rest):
            if m.role == "user" and m.images and i not in keep:
                out_rest[i] = ChatMessage(
                    role=m.role,
                    content=m.content or "",
                    name=m.name,
                    tool_call_id=m.tool_call_id,
                    tool_calls=m.tool_calls,
                    images=None,
                )

    return system + out_rest


def compress_from_config(
    messages: List[ChatMessage],
    cfg: Optional[Any] = None,
) -> List[ChatMessage]:
    """Apply compress settings from Config / dict-like ``cfg``."""
    if cfg is None:
        from maya_agent.utils.config import get_config

        cfg = get_config()

    def _get(key: str, default: Any) -> Any:
        try:
            return cfg.get(key, default)
        except Exception:
            if isinstance(cfg, dict):
                # support flat or nested
                parts = key.split(".")
                cur: Any = cfg
                for p in parts:
                    if not isinstance(cur, dict) or p not in cur:
                        return default
                    cur = cur[p]
                return cur
            return default

    enabled = bool(_get("agent.context_compress", True))
    return compress_messages_for_llm(
        messages,
        enabled=enabled,
        protect_recent_groups=int(_get("agent.context_protect_recent_groups", 2)),
        soft_limit=int(_get("agent.context_tool_soft_limit", 1200)),
        head_chars=int(_get("agent.context_tool_head_chars", 600)),
        tail_chars=int(_get("agent.context_tool_tail_chars", 200)),
        strip_old_images=bool(_get("agent.context_strip_old_images", True)),
        keep_recent_image_users=1,
    )
