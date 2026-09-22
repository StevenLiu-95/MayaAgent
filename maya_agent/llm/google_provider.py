"""Google Gemini (Generative Language API) provider."""

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


class GoogleProvider(BaseProvider):
    name = "google"
    supports_tools = True

    def chat(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[ToolSpec]] = None,
        stream: bool = False,
    ) -> Union[ChatResponse, Generator[StreamChunk, None, ChatResponse]]:
        system, contents = self._convert(
            messages, include_images=self.supports_vision
        )
        body: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": self.max_tokens or 4096,
            },
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            body["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": t.name,
                            "description": t.description,
                            "parameters": t.parameters,
                        }
                        for t in tools
                    ]
                }
            ]
        action = "streamGenerateContent" if stream else "generateContent"
        url = (
            f"{self.base_url}/models/{self.model}:{action}"
            f"?key={self.api_key}"
        )
        if stream:
            url += "&alt=sse"
            return self._stream(url, body)
        with httpx.Client(timeout=self.timeout) as client:
            r = client.post(url, json=body)
            if r.status_code >= 400:
                raise_llm_http_error(
                    r.status_code,
                    r.text,
                    max_tokens=self.max_tokens,
                    model=self.model,
                    provider_label="Gemini",
                )
            return self._parse(r.json())

    def _stream(self, url, body) -> Generator[StreamChunk, None, ChatResponse]:
        content_parts: List[str] = []
        thinking_parts: List[str] = []
        tool_calls: List[ToolCall] = []
        usage: Dict[str, int] = {}
        with httpx.Client(timeout=self.timeout) as client:
            with client.stream("POST", url, json=body) as r:
                if r.status_code >= 400:
                    err = r.read().decode("utf-8", errors="replace")
                    raise_llm_http_error(
                        r.status_code,
                        err,
                        max_tokens=self.max_tokens,
                        model=self.model,
                        provider_label="Gemini",
                    )
                for line in r.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw:
                        continue
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    partial = self._parse(data)
                    if partial.usage:
                        # Gemini SSE usage is typically cumulative — keep latest
                        usage = dict(partial.usage)
                    if partial.thinking:
                        thinking_parts.append(partial.thinking)
                        yield StreamChunk(thinking=partial.thinking)
                    if partial.content:
                        content_parts.append(partial.content)
                        yield StreamChunk(text=partial.content)
                    tool_calls.extend(partial.tool_calls)
        return ChatResponse(
            content="".join(content_parts),
            thinking="".join(thinking_parts),
            tool_calls=tool_calls,
            usage=usage,
        )

    @staticmethod
    def _convert(messages: List[ChatMessage], include_images: bool = True):
        system_parts = []
        contents = []
        for m in messages:
            if m.role == "system":
                system_parts.append(m.content)
                continue
            if m.role == "tool":
                contents.append(
                    {
                        "role": "user",
                        "parts": [
                            {
                                "functionResponse": {
                                    "name": m.name or "tool",
                                    "response": {"result": m.content or ""},
                                }
                            }
                        ],
                    }
                )
                continue
            role = "model" if m.role == "assistant" else "user"
            parts: List[Dict[str, Any]] = []
            text = m.content or ""
            if m.role == "user" and m.images and not include_images:
                text = m._text_for_api(False)
            if text:
                parts.append({"text": text})
            if include_images and m.role == "user":
                for img in m.images or []:
                    if img.data_b64:
                        parts.append(img.to_gemini_part())
            if m.tool_calls:
                for tc in m.tool_calls:
                    fn = tc.get("function") or {}
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    parts.append(
                        {
                            "functionCall": {
                                "name": fn.get("name") or "",
                                "args": args,
                            }
                        }
                    )
            if parts:
                contents.append({"role": role, "parts": parts})
        return "\n\n".join(system_parts), GoogleProvider._merge_same_role(contents)

    @staticmethod
    def _merge_same_role(contents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []
        for msg in contents:
            if merged and merged[-1].get("role") == msg.get("role"):
                prev_parts = list(merged[-1].get("parts") or [])
                prev_parts.extend(msg.get("parts") or [])
                merged[-1] = {"role": msg["role"], "parts": prev_parts}
            else:
                merged.append(dict(msg))
        return merged

    @staticmethod
    def _parse(data: Dict[str, Any]) -> ChatResponse:
        cands = data.get("candidates") or []
        if not cands:
            return ChatResponse(content="", raw=data)
        parts = ((cands[0].get("content") or {}).get("parts")) or []
        texts = []
        thinking_parts = []
        tool_calls = []
        for i, p in enumerate(parts):
            if "text" in p:
                # Gemini thinking models mark thought parts with thought=true
                if p.get("thought"):
                    thinking_parts.append(p["text"])
                else:
                    texts.append(p["text"])
            if "functionCall" in p:
                fc = p["functionCall"]
                tool_calls.append(
                    ToolCall(
                        id=f"gemini_call_{i}",
                        name=fc.get("name") or "",
                        arguments=json.dumps(fc.get("args") or {}, ensure_ascii=False),
                    )
                )
        return ChatResponse(
            content="".join(texts),
            thinking="".join(thinking_parts),
            tool_calls=tool_calls,
            raw=data,
            finish_reason=(cands[0].get("finishReason") or ""),
            usage=normalize_usage(data.get("usageMetadata") or {}),
        )
