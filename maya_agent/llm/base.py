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
class StreamChunk:
    """One streamed delta — text reply and/or model thinking/reasoning."""

    text: str = ""
    thinking: str = ""


@dataclass
class ChatResponse:
    content: str = ""
    thinking: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    raw: Any = None
    finish_reason: str = ""
    usage: Dict[str, int] = field(default_factory=dict)


def extract_thinking_text(payload: Dict[str, Any]) -> str:
    """Pick reasoning/thinking text from OpenAI-compat delta or message dicts."""
    if not payload:
        return ""
    for key in ("reasoning_content", "reasoning", "thinking"):
        val = payload.get(key)
        if isinstance(val, str) and val:
            return val
    return ""


def normalize_usage(usage: Optional[Dict[str, Any]]) -> Dict[str, int]:
    """Normalize provider usage dicts to prompt/completion/total tokens."""
    if not usage:
        return {}
    out: Dict[str, int] = {}
    for k, v in usage.items():
        if isinstance(v, (int, float)):
            out[str(k)] = int(v)

    prompt = out.get("prompt_tokens")
    if prompt is None:
        prompt = out.get("input_tokens")
    if prompt is None and "promptTokenCount" in out:
        prompt = out.get("promptTokenCount")

    completion = out.get("completion_tokens")
    if completion is None:
        completion = out.get("output_tokens")
    if completion is None and "candidatesTokenCount" in out:
        completion = out.get("candidatesTokenCount")

    total = out.get("total_tokens")
    if total is None and "totalTokenCount" in out:
        total = out.get("totalTokenCount")

    result: Dict[str, int] = {}
    if prompt is not None:
        result["prompt_tokens"] = int(prompt)
    if completion is not None:
        result["completion_tokens"] = int(completion)
    if total is not None:
        result["total_tokens"] = int(total)
    elif result:
        result["total_tokens"] = int(result.get("prompt_tokens", 0)) + int(
            result.get("completion_tokens", 0)
        )
    # Keep reasoning / cached extras if present
    for extra in ("reasoning_tokens", "cached_tokens"):
        if extra in out:
            result[extra] = out[extra]
    return result


def merge_usage(acc: Dict[str, int], usage: Optional[Dict[str, Any]]) -> Dict[str, int]:
    """Add one response's usage into an accumulator (mutates and returns acc).

    Only prompt/completion (and reasoning) are summed across LLM rounds.
    total_tokens is always recomputed so it cannot drift from double-counted
    provider totals.
    """
    norm = normalize_usage(usage)
    for key in ("prompt_tokens", "completion_tokens", "reasoning_tokens", "cached_tokens"):
        if key in norm:
            acc[key] = int(acc.get(key, 0)) + int(norm[key])
    prompt = int(acc.get("prompt_tokens", 0))
    completion = int(acc.get("completion_tokens", 0))
    if prompt or completion:
        acc["total_tokens"] = prompt + completion
    elif "total_tokens" in norm and "total_tokens" not in acc:
        # Fallback when a provider only reports a single total
        acc["total_tokens"] = int(norm["total_tokens"])
    return acc


def format_turn_meta(
    model: str = "",
    usage: Optional[Dict[str, Any]] = None,
    llm_calls: int = 0,
) -> str:
    """Small footer line: model name + token counts for one user turn."""
    model = (model or "").strip() or "未知模型"
    norm = normalize_usage(usage)
    bits = [model]
    calls = int(llm_calls or 0)
    if calls <= 0 and norm:
        # Older sessions without llm_calls — infer nothing, just show tokens
        calls = 0
    if calls > 1:
        bits.append(f"{calls} 次请求")
    if not norm:
        return " · ".join(bits)
    prompt = int(norm.get("prompt_tokens") or 0)
    completion = int(norm.get("completion_tokens") or 0)
    total = int(norm.get("total_tokens") or (prompt + completion))
    if prompt or completion or total:
        # Multi-round Agent turns re-send tools/history each request; summed
        # prompt_tokens is the real billable input across those calls.
        if prompt or completion:
            bits.append(f"输入 {prompt}")
            bits.append(f"输出 {completion}")
        bits.append(f"合计 {total}")
    return " · ".join(bits)


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
    ) -> Union[ChatResponse, Generator[StreamChunk, None, ChatResponse]]:
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
