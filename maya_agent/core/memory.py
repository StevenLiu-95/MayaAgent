"""Conversation memory with OpenAI-compatible tool-call sequence integrity."""

from __future__ import annotations

from typing import Any, Dict, List

from maya_agent.core.message_codec import message_from_dict, messages_to_dicts
from maya_agent.llm.base import ChatMessage


class ConversationMemory:
    def __init__(self, limit: int = 40) -> None:
        self.limit = limit
        self.messages: List[ChatMessage] = []

    def add(self, message: ChatMessage) -> None:
        self.messages.append(message)
        self._trim()

    def extend(self, messages: List[ChatMessage]) -> None:
        self.messages.extend(messages)
        self._trim()

    def clear(self) -> None:
        self.messages.clear()

    def to_serializable(self) -> List[Dict[str, Any]]:
        return messages_to_dicts(self.messages)

    def load_from_serializable(self, data: List[Dict[str, Any]]) -> None:
        self.clear()
        for item in data or []:
            self.messages.append(message_from_dict(item))

    def replace_conversation(self, messages: List[ChatMessage]) -> None:
        """Replace non-system messages, keeping a single fresh system prompt slot."""
        self.clear()
        self.messages.extend(messages)

    def as_list(self) -> List[ChatMessage]:
        """Return a sanitized copy safe to send to the LLM API."""
        return self._sanitized_copy(self.messages)

    def drop_incomplete_tool_round(self) -> None:
        """
        If the last assistant asked for tools but results are incomplete
        (e.g. user clicked Stop), convert/drop so the next turn is valid.
        """
        rest = [m for m in self.messages if m.role != "system"]
        system = [m for m in self.messages if m.role == "system"]
        if not rest:
            return

        # Find last assistant-with-tools
        idx = None
        for i in range(len(rest) - 1, -1, -1):
            if rest[i].role == "assistant" and rest[i].tool_calls:
                idx = i
                break
        if idx is None:
            return

        msg = rest[idx]
        expected = []
        for tc in msg.tool_calls or []:
            if isinstance(tc, dict) and tc.get("id"):
                expected.append(tc["id"])
        results = []
        j = idx + 1
        while j < len(rest) and rest[j].role == "tool":
            results.append(rest[j])
            j += 1

        # If more messages after tools (user/assistant), round already closed
        if j < len(rest):
            return

        have = {r.tool_call_id for r in results if r.tool_call_id}
        if expected and len(have) >= len(expected):
            return  # complete

        # Incomplete trailing round — keep text only
        new_rest = rest[:idx]
        if msg.content:
            new_rest.append(ChatMessage(role="assistant", content=msg.content))
        self.messages = system + new_rest

    @staticmethod
    def _sanitized_copy(messages: List[ChatMessage]) -> List[ChatMessage]:
        """
        Build a clean message list for the API:
        - every tool message follows assistant.tool_calls
        - every tool_call has a matching tool result
        - orphan tool messages are removed
        """
        system = [m for m in messages if m.role == "system"]
        rest = [m for m in messages if m.role != "system"]
        fixed: List[ChatMessage] = []
        i = 0
        while i < len(rest):
            msg = rest[i]

            if msg.role == "tool":
                i += 1
                continue

            if msg.role == "assistant" and msg.tool_calls:
                # Normalize call ids
                fixed_calls = []
                for idx, tc in enumerate(msg.tool_calls):
                    if not isinstance(tc, dict):
                        continue
                    tc = dict(tc)
                    fn = dict(tc.get("function") or {})
                    fn.setdefault("name", "tool")
                    fn.setdefault("arguments", "{}")
                    tc["function"] = fn
                    tc["type"] = tc.get("type") or "function"
                    if not tc.get("id"):
                        tc["id"] = f"call_auto_{idx}"
                    fixed_calls.append(tc)

                results_raw: List[ChatMessage] = []
                j = i + 1
                while j < len(rest) and rest[j].role == "tool":
                    results_raw.append(rest[j])
                    j += 1

                by_id = {
                    r.tool_call_id: r
                    for r in results_raw
                    if r.tool_call_id
                }
                results: List[ChatMessage] = []
                for idx, tc in enumerate(fixed_calls):
                    tid = tc["id"]
                    if tid in by_id:
                        r = by_id[tid]
                        results.append(
                            ChatMessage(
                                role="tool",
                                content=r.content or "",
                                name=r.name or tc["function"]["name"],
                                tool_call_id=tid,
                            )
                        )
                    elif idx < len(results_raw) and not results_raw[idx].tool_call_id:
                        r = results_raw[idx]
                        results.append(
                            ChatMessage(
                                role="tool",
                                content=r.content or "",
                                name=r.name or tc["function"]["name"],
                                tool_call_id=tid,
                            )
                        )
                    else:
                        results.append(
                            ChatMessage(
                                role="tool",
                                content='{"ok":false,"error":"tool result missing"}',
                                name=tc["function"]["name"],
                                tool_call_id=tid,
                            )
                        )

                # If this is a trailing incomplete round mid-execution, still OK
                # for API as long as we filled placeholders above.
                if not fixed_calls:
                    if msg.content:
                        fixed.append(ChatMessage(role="assistant", content=msg.content))
                    i = j
                    continue

                fixed.append(
                    ChatMessage(
                        role="assistant",
                        content=msg.content or "",
                        tool_calls=fixed_calls,
                    )
                )
                fixed.extend(results)
                i = j
                continue

            fixed.append(msg)
            i += 1

        return system + fixed

    def _trim(self) -> None:
        """Trim oldest turns without splitting assistant/tool sequences."""
        if len(self.messages) <= self.limit:
            return

        system = [m for m in self.messages if m.role == "system"]
        rest = [m for m in self.messages if m.role != "system"]
        budget = max(4, self.limit - len(system))

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
                # orphan while trimming — skip
                i += 1
            else:
                groups.append([msg])
                i += 1

        kept: List[ChatMessage] = []
        for group in reversed(groups):
            if len(kept) + len(group) > budget and kept:
                break
            kept = group + kept

        self.messages = system + kept
