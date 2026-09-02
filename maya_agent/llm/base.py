"""LLM provider abstractions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Generator, List, Optional, Union


@dataclass
class ChatMessage:
    role: str  # system | user | assistant | tool
    content: str = ""
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None

    def to_openai(self) -> Dict[str, Any]:
        msg: Dict[str, Any] = {"role": self.role}
        if self.role == "assistant" and self.tool_calls:
            # Many providers (DeepSeek etc.) prefer null over "" when calling tools
            msg["content"] = self.content if self.content else None
            msg["tool_calls"] = self.tool_calls
        else:
            msg["content"] = self.content if self.content is not None else ""
        if self.name and self.role == "tool":
            msg["name"] = self.name
        if self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id
        return msg


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema

    def to_openai(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # JSON string


@dataclass
class ChatResponse:
    content: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    raw: Any = None
    finish_reason: str = ""
    usage: Dict[str, int] = field(default_factory=dict)


class BaseProvider:
    """Unified chat completion interface."""

    name: str = "base"
    supports_tools: bool = True

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        timeout: float = 120.0,
        **kwargs: Any,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.extra = kwargs

    def chat(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[ToolSpec]] = None,
        stream: bool = False,
    ) -> Union[ChatResponse, Generator[str, None, ChatResponse]]:
        raise NotImplementedError

    def test_connection(self) -> Dict[str, Any]:
        try:
            resp = self.chat(
                [ChatMessage(role="user", content="Reply with OK only.")],
                tools=None,
                stream=False,
            )
            assert isinstance(resp, ChatResponse)
            return {"ok": True, "preview": (resp.content or "")[:80]}
        except Exception as e:
            return {"ok": False, "error": str(e)}
