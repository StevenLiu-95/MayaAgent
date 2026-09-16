"""LLM provider abstractions."""

from __future__ import annotations

import json
import re
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


# Normal completion reasons across OpenAI / Anthropic / Google — no user tip needed.
_NORMAL_FINISH_REASONS = frozenset(
    {
        "",
        "stop",
        "end_turn",
        "tool_calls",
        "tool_use",
        "function_call",
        "stop_sequence",
    }
)

_FINISH_REASON_NOTICES = {
    "length": "已停止：达到 Token / 输出长度上限，回复可能被截断。可继续追问让我接着完成。",
    "max_tokens": "已停止：达到 Token / 输出长度上限，回复可能被截断。可继续追问让我接着完成。",
    "content_filter": "已停止：触发了内容安全过滤，部分内容未能生成。",
    "safety": "已停止：触发了内容安全过滤，部分内容未能生成。",
    "refusal": "已停止：模型拒绝继续生成该内容。",
    "recitation": "已停止：模型因引用限制中断了生成。",
}


def describe_finish_reason(reason: Optional[str]) -> Optional[str]:
    """
    Map provider finish/stop reason to a short Chinese tip for the chat footer.
    Returns None when the turn completed normally.
    """
    raw = (reason or "").strip()
    if not raw:
        return None
    key = raw.lower().replace("-", "_").replace(" ", "_")
    if key in _NORMAL_FINISH_REASONS:
        return None
    if key in _FINISH_REASON_NOTICES:
        return _FINISH_REASON_NOTICES[key]
    return f"已停止：模型异常结束（{raw}）。"


def stop_notice_for_reason(reason: str) -> str:
    """Built-in notices for UI / Agent-level abort reasons (not LLM finish_reason)."""
    mapping = {
        "user_cancel": "已停止：用户取消了本次生成。",
        "max_tool_rounds": "已停止：达到最大工具调用轮次，请缩小任务范围后重试。",
        "llm_error": "已停止：大模型调用失败，请查看下方错误说明。",
        "worker_error": "已停止：后台任务异常退出。",
    }
    return mapping.get(reason, f"已停止：{reason}" if reason else "已停止。")


def _extract_api_error_fields(body: str) -> Dict[str, str]:
    """Pull message/code/type from common OpenAI-compat / vendor JSON error bodies."""
    text = (body or "").strip()
    out = {"message": "", "code": "", "type": "", "raw": text[:800]}
    if not text:
        return out
    try:
        data = json.loads(text)
    except Exception:
        out["message"] = text[:500]
        return out
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, dict):
        out["message"] = str(err.get("message") or err.get("msg") or "")
        out["code"] = str(err.get("code") or "")
        out["type"] = str(err.get("type") or "")
    elif isinstance(err, str):
        out["message"] = err
    elif isinstance(data, dict):
        out["message"] = str(
            data.get("message") or data.get("msg") or data.get("detail") or ""
        )
        out["code"] = str(data.get("code") or "")
    if not out["message"]:
        out["message"] = text[:500]
    return out


def format_llm_http_error(
    status_code: int,
    body: str,
    *,
    max_tokens: Optional[int] = None,
    model: str = "",
    provider_label: str = "LLM",
) -> str:
    """
    Turn raw HTTP error bodies into actionable Chinese tips for chat / test connection.
    Keeps a short original snippet for debugging.
    """
    fields = _extract_api_error_fields(body)
    msg = fields["message"]
    code = fields["code"]
    etype = fields["type"]
    blob = f"{msg} {code} {etype} {fields['raw']}".lower()
    model_hint = f"（模型 {model}）" if model else ""
    mt = int(max_tokens) if max_tokens else 0

    # max_tokens / maxOutputTokens range (Qwen DashScope, etc.)
    range_m = re.search(
        r"max[_ ]?(?:tokens|outputtokens)[^\d\[]{0,40}\[?\s*(\d+)\s*,\s*(\d+)\s*\]?",
        msg,
        re.I,
    ) or re.search(
        r"range of max_tokens should be\s*\[\s*(\d+)\s*,\s*(\d+)\s*\]",
        msg,
        re.I,
    )
    if range_m or (
        "max_tokens" in blob
        and any(k in blob for k in ("range", "should be", "invalidparameter", "invalid_parameter"))
    ):
        lo = range_m.group(1) if range_m else "1"
        hi = range_m.group(2) if range_m else "8192"
        cur = f"当前 Max Tokens = {mt}，" if mt else ""
        return (
            f"{provider_label} 参数错误{model_hint}：Max Tokens 超出允许范围 [{lo}, {hi}]。\n"
            f"{cur}请打开「设置 → 模型与 API」，将 Max Tokens 改为不超过 {hi} 后保存再试"
            f"（通义千问等接口常见上限为 8192）。\n"
            f"原始信息：{msg[:240]}"
        )

    if status_code in (401, 403) or any(
        k in blob for k in ("unauthorized", "invalid api key", "invalid_api_key", "authentication")
    ):
        return (
            f"{provider_label} 鉴权失败{model_hint}（HTTP {status_code}）。\n"
            f"请检查 API Key 是否正确、是否有该模型权限，以及是否选对了对应服务商。\n"
            f"原始信息：{msg[:240]}"
        )

    if status_code == 429 or any(
        k in blob for k in ("rate limit", "rate_limit", "too many requests", "quota")
    ):
        return (
            f"{provider_label} 请求过于频繁或额度不足{model_hint}（HTTP {status_code}）。\n"
            f"请稍后再试，或检查账户余额 / 限流配置。\n"
            f"原始信息：{msg[:240]}"
        )

    if status_code == 404 or "model" in blob and any(
        k in blob for k in ("not found", "does not exist", "unknown model", "invalid model")
    ):
        return (
            f"{provider_label} 找不到模型{model_hint}（HTTP {status_code}）。\n"
            f"请在设置中确认模型名称是否对该 API 有效。\n"
            f"原始信息：{msg[:240]}"
        )

    if status_code >= 500:
        return (
            f"{provider_label} 服务端异常{model_hint}（HTTP {status_code}）。\n"
            f"多为服务商临时故障，请稍后重试。\n"
            f"原始信息：{msg[:240]}"
        )

    if status_code == 400 or "invalid" in blob or "invalid_parameter" in blob:
        return (
            f"{provider_label} 请求参数无效{model_hint}（HTTP {status_code}）。\n"
            f"请检查 Max Tokens、模型名与上下文长度等设置是否符合该服务商限制。\n"
            f"原始信息：{msg[:240]}"
        )

    return (
        f"{provider_label} 调用失败{model_hint}（HTTP {status_code}）。\n"
        f"{msg[:400] or fields['raw'][:400]}"
    )


def raise_llm_http_error(
    status_code: int,
    body: str,
    *,
    max_tokens: Optional[int] = None,
    model: str = "",
    provider_label: str = "LLM",
) -> None:
    raise RuntimeError(
        format_llm_http_error(
            status_code,
            body,
            max_tokens=max_tokens,
            model=model,
            provider_label=provider_label,
        )
    )


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
