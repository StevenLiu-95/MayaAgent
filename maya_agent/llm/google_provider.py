"""Google Gemini (Generative Language API) provider."""

from __future__ import annotations

import json
from typing import Any, Dict, Generator, List, Optional, Union

import httpx

from maya_agent.llm.base import (
    BaseProvider,
    ChatMessage,
    ChatResponse,
    ToolCall,
    ToolSpec,
)


class GoogleProvider(BaseProvider):
    name = "google"
    supports_tools = True

    def chat(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[ToolSpec]] = None,
        stream: bool = False,
    ) -> Union[ChatResponse, Generator[str, None, ChatResponse]]:
        system, contents = self._convert(messages)
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
                raise RuntimeError(f"Gemini HTTP {r.status_code}: {r.text[:500]}")
            return self._parse(r.json())

    def _stream(self, url, body) -> Generator[str, None, ChatResponse]:
        content_parts: List[str] = []
        tool_calls: List[ToolCall] = []
        with httpx.Client(timeout=self.timeout) as client:
            with client.stream("POST", url, json=body) as r:
                if r.status_code >= 400:
                    err = r.read().decode("utf-8", errors="replace")
                    raise RuntimeError(f"Gemini HTTP {r.status_code}: {err[:500]}")
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
                    if partial.content:
                        content_parts.append(partial.content)
                        yield partial.content
                    tool_calls.extend(partial.tool_calls)
        return ChatResponse(content="".join(content_parts), tool_calls=tool_calls)

    @staticmethod
    def _convert(messages: List[ChatMessage]):
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
            if m.content:
                parts.append({"text": m.content})
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
        return "\n\n".join(system_parts), contents

    @staticmethod
    def _parse(data: Dict[str, Any]) -> ChatResponse:
        cands = data.get("candidates") or []
        if not cands:
            return ChatResponse(content="", raw=data)
        parts = ((cands[0].get("content") or {}).get("parts")) or []
        texts = []
        tool_calls = []
        for i, p in enumerate(parts):
            if "text" in p:
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
            tool_calls=tool_calls,
            raw=data,
            finish_reason=(cands[0].get("finishReason") or ""),
        )
