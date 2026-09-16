"""Cursor provider — OpenAI-compatible chat via Cursor API key + proxy.

Official Cursor Cloud Agents API (api.cursor.com/v1/agents) is an *agent harness*,
not raw chat/completions. MayaAgent needs function-calling chat completions to drive
Maya tools, so this provider:

1. Talks OpenAI Chat Completions to whatever Base URL you set (typically a local
   Cursor→OpenAI proxy such as http://127.0.0.1:4646/v1).
2. Accepts CURSOR_API_KEY (crsr_…) with Bearer or Basic auth.
3. Detects official api.cursor.com and returns a clear setup hint instead of a
   cryptic 404.
"""

from __future__ import annotations

import base64
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import httpx

from maya_agent.llm.openai_compat import OpenAICompatProvider


def _is_official_cursor_host(base_url: str) -> bool:
    try:
        host = (urlparse(base_url).hostname or "").lower()
    except Exception:
        host = ""
    return host in ("api.cursor.com", "www.cursor.com") or host.endswith(".cursor.com")


class CursorProvider(OpenAICompatProvider):
    """OpenAI-compatible client tuned for Cursor API keys and common proxies."""

    name = "cursor"
    supports_tools = True

    def __init__(self, *args: Any, auth_mode: str = "bearer", **kwargs: Any):
        super().__init__(*args, azure=False, **kwargs)
        mode = (auth_mode or "bearer").strip().lower()
        self.auth_mode = mode if mode in ("bearer", "basic", "auto") else "bearer"

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        key = (self.api_key or "").strip()
        mode = self.auth_mode
        if mode == "auto":
            # Official Cursor APIs accept Basic or Bearer; proxies usually want Bearer.
            mode = "basic" if _is_official_cursor_host(self.base_url) else "bearer"
        if mode == "basic":
            token = base64.b64encode(f"{key}:".encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {token}"
        else:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def _official_api_hint(self) -> str:
        return (
            "Cursor 官方 api.cursor.com 提供的是 Cloud Agents / SDK（/v1/agents），"
            "不是 OpenAI 风格的 /v1/chat/completions，无法直接驱动 MayaAgent 的工具调用。\n\n"
            "请任选其一：\n"
            "1) 将 Base URL 改为本地 Cursor→OpenAI 兼容代理"
            "（例如 http://127.0.0.1:4646/v1），API Key 填 CURSOR_API_KEY（crsr_…）；\n"
            "2) 或使用「自定义 OpenAI 兼容接口」指向你的代理地址。\n\n"
            "说明：官方文档确认目前没有公开的 Chat Completions 端点；"
            "代理需自行部署，且勿使用未授权的逆向客户端接口。"
        )

    def _api_root(self) -> str:
        """Strip trailing /v1 so we can hit /v1/me on the official host."""
        root = (self.base_url or "").rstrip("/")
        if root.endswith("/v1"):
            root = root[:-3]
        return root.rstrip("/")

    def _probe_official_key(self) -> Optional[Dict[str, Any]]:
        """Return me-payload if key works against official API; else None."""
        if not _is_official_cursor_host(self.base_url):
            return None
        url = f"{self._api_root()}/v1/me"
        try:
            with httpx.Client(timeout=min(30.0, float(self.timeout) or 30.0)) as client:
                r = client.get(url, headers=self._headers())
            if r.status_code >= 400:
                return None
            data = r.json()
            return data if isinstance(data, dict) else {"raw": data}
        except Exception:
            return None

    def chat(self, messages, tools=None, stream=False):
        if _is_official_cursor_host(self.base_url):
            raise RuntimeError(self._official_api_hint())
        return super().chat(messages, tools=tools, stream=stream)

    def test_connection(self) -> Dict[str, Any]:
        if _is_official_cursor_host(self.base_url):
            me = self._probe_official_key()
            if me is not None:
                who = (
                    me.get("email")
                    or me.get("userEmail")
                    or me.get("name")
                    or me.get("id")
                    or "ok"
                )
                return {
                    "ok": False,
                    "error": (
                        f"API Key 有效（账号: {who}），但官方 Cursor API 不能直接用于对话。\n\n"
                        + self._official_api_hint()
                    ),
                }
            # Key invalid or /v1/me unavailable — still explain the architecture
            try:
                with httpx.Client(timeout=min(20.0, float(self.timeout) or 20.0)) as client:
                    r = client.get(f"{self._api_root()}/v1/me", headers=self._headers())
                if r.status_code in (401, 403):
                    return {
                        "ok": False,
                        "error": (
                            f"Cursor API Key 无效或权限不足（HTTP {r.status_code}）。"
                            "请在 cursor.com/dashboard → API Keys 创建用户密钥（crsr_…）。\n\n"
                            "补充：即使 Key 有效，官方 api.cursor.com 也不能直接用于 MayaAgent 对话，"
                            "仍需将 Base URL 改为本地 OpenAI 兼容代理。"
                        ),
                    }
            except Exception as e:
                return {
                    "ok": False,
                    "error": f"无法连接 Cursor API: {e}\n\n{self._official_api_hint()}",
                }
            return {"ok": False, "error": self._official_api_hint()}

        # Proxy / custom OpenAI-compatible endpoint
        try:
            return super().test_connection()
        except Exception as e:
            return {
                "ok": False,
                "error": (
                    f"Cursor 兼容代理连接失败: {e}\n\n"
                    "请确认本地代理已启动，且 Base URL 形如 http://127.0.0.1:4646/v1。"
                ),
            }
