"""Anthropic Messages API provider."""

from __future__ import annotations

import json
from typing import Any, Dict, Generator, List, Optional, Union

import httpx

from maya_agent.llm.base import (
    BaseProvider,
    ChatMessage,
    ChatResponse,
    StreamChunk,
    ToolCall,
    ToolSpec,
    normalize_usage,
    raise_llm_http_error,
)


class AnthropicProvider(BaseProvider):
    name = "anthropic"
    supports_tools = True

    def chat(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[ToolSpec]] = None,
        stream: bool = False,
    ) -> Union[ChatResponse, Generator[StreamChunk, None, ChatResponse]]:
        system, converted = self._convert_messages(messages)
        payload: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens or 4096,
            "temperature": self.temperature,
            "messages": converted,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.parameters,
                }
                for t in tools
            ]
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }
        url = f"{self.base_url}/v1/messages"
        if stream:
            return self._stream(url, headers, payload)
        with httpx.Client(timeout=self.timeout) as client:
            r = client.post(url, headers=headers, json=payload)
            if r.status_code >= 400:
                raise_llm_http_error(
                    r.status_code,
                    r.text,
                    max_tokens=self.max_tokens,
                    model=self.model,
                    provider_label="Anthropic",
                )
            return self._parse(r.json())

    def _stream(self, url, headers, payload) -> Generator[StreamChunk, None, ChatResponse]:
        payload = dict(payload)
        payload["stream"] = True
        content_parts: List[str] = []
        thinking_parts: List[str] = []
        tool_calls: List[ToolCall] = []
        current_tool: Optional[Dict[str, Any]] = None
        finish_reason = ""
        usage: Dict[str, int] = {}

        with httpx.Client(timeout=self.timeout) as client:
            with client.stream("POST", url, headers=headers, json=payload) as r:
                if r.status_code >= 400:
                    body = r.read().decode("utf-8", errors="replace")
                    raise_llm_http_error(
                        r.status_code,
                        body,
                        max_tokens=self.max_tokens,
                        model=self.model,
                        provider_label="Anthropic",
                    )
                for line in r.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if not data_str:
                        continue
                    try:
                        event = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    et = event.get("type")
                    if et == "message_start":
                        msg = event.get("message") or {}
                        u = normalize_usage(msg.get("usage") or {})
                        if u:
                            usage.update(u)
                    elif et == "content_block_start":
                        block = event.get("content_block") or {}
                        if block.get("type") == "tool_use":
                            current_tool = {
                                "id": block.get("id", ""),
                                "name": block.get("name", ""),
                                "arguments": "",
                            }
                        elif block.get("type") == "thinking":
                            think = block.get("thinking") or ""
                            if think:
                                thinking_parts.append(think)
                                yield StreamChunk(thinking=think)
                    elif et == "content_block_delta":
                        delta = event.get("delta") or {}
                        dtype = delta.get("type")
                        if dtype == "text_delta":
                            piece = delta.get("text") or ""
                            if piece:
                                content_parts.append(piece)
                                yield StreamChunk(text=piece)
                        elif dtype == "thinking_delta":
                            think = delta.get("thinking") or ""
                            if think:
                                thinking_parts.append(think)
                                yield StreamChunk(thinking=think)
                        elif dtype == "input_json_delta" and current_tool:
                            current_tool["arguments"] += delta.get("partial_json") or ""
                    elif et == "content_block_stop":
                        if current_tool:
                            tool_calls.append(
                                ToolCall(
                                    id=current_tool["id"],
                                    name=current_tool["name"],
                                    arguments=current_tool["arguments"] or "{}",
                                )
                            )
                            current_tool = None
                    elif et == "message_delta":
                        finish_reason = (event.get("delta") or {}).get("stop_reason") or ""
                        u = normalize_usage(event.get("usage") or {})
                        if "completion_tokens" in u:
                            usage["completion_tokens"] = u["completion_tokens"]
                        if "prompt_tokens" in u and "prompt_tokens" not in usage:
                            usage["prompt_tokens"] = u["prompt_tokens"]
                        if usage.get("prompt_tokens") is not None or usage.get(
                            "completion_tokens"
                        ) is not None:
                            usage["total_tokens"] = int(
                                usage.get("prompt_tokens", 0)
                            ) + int(usage.get("completion_tokens", 0))

        return ChatResponse(
            content="".join(content_parts),
            thinking="".join(thinking_parts),
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=normalize_usage(usage),
        )

    @staticmethod
    def _convert_messages(messages: List[ChatMessage]):
        system_parts = []
        out = []
        for m in messages:
            if m.role == "system":
                system_parts.append(m.content)
                continue
            if m.role == "tool":
                out.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": m.tool_call_id or "",
                                "content": m.content or "",
                            }
                        ],
                    }
                )
                continue
            if m.role == "assistant" and m.tool_calls:
                content: List[Dict[str, Any]] = []
                if m.content:
                    content.append({"type": "text", "text": m.content})
                for tc in m.tool_calls:
                    fn = tc.get("function") or {}
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    content.append(
                        {
                            "type": "tool_use",
                            "id": tc.get("id") or "",
                            "name": fn.get("name") or "",
                            "input": args,
                        }
                    )
                out.append({"role": "assistant", "content": content})
                continue
            out.append({"role": m.role, "content": m.content or ""})
        return "\n\n".join(system_parts), out

    @staticmethod
    def _parse(data: Dict[str, Any]) -> ChatResponse:
        text_parts = []
        thinking_parts = []
        tool_calls = []
        for block in data.get("content") or []:
            btype = block.get("type")
            if btype == "text":
                text_parts.append(block.get("text") or "")
            elif btype == "thinking":
                thinking_parts.append(block.get("thinking") or "")
            elif btype == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.get("id") or "",
                        name=block.get("name") or "",
                        arguments=json.dumps(block.get("input") or {}, ensure_ascii=False),
                    )
                )
        usage = data.get("usage") or {}
        return ChatResponse(
            content="".join(text_parts),
            thinking="".join(thinking_parts),
            tool_calls=tool_calls,
            raw=data,
            finish_reason=data.get("stop_reason") or "",
            usage=normalize_usage(
                {
                    "input_tokens": int(usage.get("input_tokens") or 0),
                    "output_tokens": int(usage.get("output_tokens") or 0),
                }
            ),
        )
