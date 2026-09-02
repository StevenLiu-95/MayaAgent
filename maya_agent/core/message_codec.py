"""Serialize / deserialize chat messages for session persistence."""

from __future__ import annotations

from typing import Any, Dict, List

from maya_agent.llm.base import ChatMessage


def message_to_dict(msg: ChatMessage) -> Dict[str, Any]:
    d: Dict[str, Any] = {"role": msg.role, "content": msg.content or ""}
    if msg.name:
        d["name"] = msg.name
    if msg.tool_call_id:
        d["tool_call_id"] = msg.tool_call_id
    if msg.tool_calls:
        d["tool_calls"] = msg.tool_calls
    return d


def message_from_dict(data: Dict[str, Any]) -> ChatMessage:
    return ChatMessage(
        role=str(data.get("role") or "user"),
        content=str(data.get("content") or ""),
        name=data.get("name"),
        tool_call_id=data.get("tool_call_id"),
        tool_calls=data.get("tool_calls"),
    )


def messages_to_dicts(messages: List[ChatMessage]) -> List[Dict[str, Any]]:
    return [message_to_dict(m) for m in messages]


def messages_from_dicts(data: List[Dict[str, Any]]) -> List[ChatMessage]:
    return [message_from_dict(d) for d in (data or [])]
