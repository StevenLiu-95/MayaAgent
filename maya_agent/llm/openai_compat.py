"""OpenAI-compatible Chat Completions provider (works for most Chinese/Intl APIs)."""

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
    extract_thinking_text,
    normalize_usage,
)


class OpenAICompatProvider(BaseProvider):
    """
    Implements OpenAI Chat Completions API.
    Compatible with: OpenAI, DeepSeek, Qwen(DashScope compatible), Zhipu,
    Moonshot, Doubao(Ark), Baichuan, SiliconFlow, Ollama, Azure (with path tweak), Custom.
    """

    name = "openai_compat"
    supports_tools = True

    def __init__(self, *args: Any, azure: bool = False, api_version: str = "", **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.azure = azure
        self.api_version = api_version or "2024-06-01"

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
        }
        if self.azure:
            headers["api-key"] = self.api_key
        else:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _url(self) -> str:
        if self.azure:
            # base_url should be like https://xxx.openai.azure.com
            return (
                f"{self.base_url}/openai/deployments/{self.model}"
                f"/chat/completions?api-version={self.api_version}"
            )
        return f"{self.base_url}/chat/completions"

    def _payload(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[ToolSpec]],
        stream: bool,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "messages": [m.to_openai() for m in messages],
            "temperature": self.temperature,
            "stream": stream,
        }
        if not self.azure:
            payload["model"] = self.model
        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens
        if tools:
            payload["tools"] = [t.to_openai() for t in tools]
            payload["tool_choice"] = "auto"
        if stream:
            # Ask compatible APIs to include usage on the final SSE chunk
            payload["stream_options"] = {"include_usage": True}
        return payload

    def chat(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[ToolSpec]] = None,
        stream: bool = False,
    ) -> Union[ChatResponse, Generator[StreamChunk, None, ChatResponse]]:
        if stream:
            return self._stream(messages, tools)
        return self._complete(messages, tools)

    def _complete(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[ToolSpec]],
    ) -> ChatResponse:
        with httpx.Client(timeout=self.timeout) as client:
            r = client.post(
                self._url(),
                headers=self._headers(),
                json=self._payload(messages, tools, stream=False),
            )
            if r.status_code >= 400:
                raise RuntimeError(f"LLM HTTP {r.status_code}: {r.text[:500]}")
            data = r.json()
        return self._parse_response(data)

    def _stream(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[ToolSpec]],
    ) -> Generator[StreamChunk, None, ChatResponse]:
        content_parts: List[str] = []
        thinking_parts: List[str] = []
        tool_acc: Dict[int, Dict[str, Any]] = {}
        finish_reason = ""
        usage: Dict[str, int] = {}

        with httpx.Client(timeout=self.timeout) as client:
            with client.stream(
                "POST",
                self._url(),
                headers=self._headers(),
                json=self._payload(messages, tools, stream=True),
            ) as r:
                if r.status_code >= 400:
                    body = r.read().decode("utf-8", errors="replace")
                    raise RuntimeError(f"LLM HTTP {r.status_code}: {body[:500]}")
                for line in r.iter_lines():
                    if not line:
                        continue
                    if line.startswith("data:"):
                        line = line[5:].strip()
                    if line == "[DONE]":
                        break
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if "usage" in chunk and chunk["usage"]:
                        usage = normalize_usage(chunk["usage"])
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    fr = choices[0].get("finish_reason")
                    if fr:
                        finish_reason = fr
                    think = extract_thinking_text(delta)
                    piece = delta.get("content") or ""
                    if think or piece:
                        if think:
                            thinking_parts.append(think)
                        if piece:
                            content_parts.append(piece)
                        yield StreamChunk(text=piece or "", thinking=think or "")
                    for tc in delta.get("tool_calls") or []:
                        idx = tc.get("index", 0)
                        slot = tool_acc.setdefault(
                            idx, {"id": "", "name": "", "arguments": ""}
                        )
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] = fn["name"]
                        if fn.get("arguments"):
                            slot["arguments"] += fn["arguments"]

        tool_calls = [
            ToolCall(
                id=v["id"] or f"call_{i}",
                name=v["name"],
                arguments=v["arguments"] or "{}",
            )
            for i, v in sorted(tool_acc.items())
            if v.get("name")
        ]
        return ChatResponse(
            content="".join(content_parts),
            thinking="".join(thinking_parts),
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
        )

    @staticmethod
    def _parse_response(data: Dict[str, Any]) -> ChatResponse:
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"Empty LLM response: {data}")
        msg = choices[0].get("message") or {}
        tool_calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            tool_calls.append(
                ToolCall(
                    id=tc.get("id") or "",
                    name=fn.get("name") or "",
                    arguments=fn.get("arguments") or "{}",
                )
            )
        usage_raw = data.get("usage") or {}
        return ChatResponse(
            content=msg.get("content") or "",
            thinking=extract_thinking_text(msg),
            tool_calls=tool_calls,
            raw=data,
            finish_reason=choices[0].get("finish_reason") or "",
            usage=normalize_usage(usage_raw),
        )

