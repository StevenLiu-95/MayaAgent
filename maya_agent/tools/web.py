"""Web research tools: search pages/images and fetch content for the agent."""

from __future__ import annotations

import html
import ipaddress
import json
import re
import socket
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, quote, unquote, urlparse

import httpx

from maya_agent.llm.image_codec import MAX_IMAGES, attachment_from_bytes
from maya_agent.tools.registry import ToolResult, obj_schema, tool
from maya_agent.utils.config import get_config
from maya_agent.utils.logger import get_logger

log = get_logger("maya_agent.web")

_BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "::1",
        "metadata.google.internal",
        "metadata.google",
    }
)
_PRIVATE_NETWORKS = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


# ---------------------------------------------------------------------------
# Config / HTTP helpers
# ---------------------------------------------------------------------------


def _web_cfg() -> Dict[str, Any]:
    cfg = get_config()
    return {
        "enabled": bool(cfg.get("web.enabled", True)),
        "timeout": float(cfg.get("web.timeout", 20) or 20),
        "max_page_chars": int(cfg.get("web.max_page_chars", 12000) or 12000),
        "max_search_results": int(cfg.get("web.max_search_results", 8) or 8),
        "max_images": int(cfg.get("web.max_images", 4) or 4),
        "max_download_bytes": int(cfg.get("web.max_download_bytes", 5_000_000) or 5_000_000),
        "user_agent": str(
            cfg.get(
                "web.user_agent",
                "Mozilla/5.0 (compatible; MayaAgent/1.3; +https://localhost)",
            )
            or "Mozilla/5.0 MayaAgent/1.3"
        ),
    }


def _disabled_result() -> ToolResult:
    return ToolResult(
        ok=False,
        error="网络检索已在配置中关闭（web.enabled=false）。",
    )


def _headers(*, accept: str = "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8") -> Dict[str, str]:
    return {
        "User-Agent": _web_cfg()["user_agent"],
        "Accept": accept,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }


def _is_blocked_ip(ip: Any) -> bool:
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
        return True
    for net in _PRIVATE_NETWORKS:
        if ip in net:
            return True
    return False


def _validate_public_url(url: str) -> Tuple[bool, str]:
    raw = (url or "").strip()
    if not raw:
        return False, "URL 为空"
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        return False, "仅支持 http/https URL"
    host = (parsed.hostname or "").lower().strip(".")
    if not host:
        return False, "URL 缺少主机名"
    if host in _BLOCKED_HOSTS or host.endswith(".localhost") or host.endswith(".local"):
        return False, "禁止访问本地/内网地址"
    try:
        infos = socket.getaddrinfo(host, parsed.port or 80, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        return False, f"无法解析主机名: {e}"
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if _is_blocked_ip(ip):
            return False, "禁止访问私有/保留 IP（防 SSRF）"
    return True, ""


def _unwrap_redirect_url(url: str) -> str:
    """Unwrap DuckDuckGo / Bing redirect wrappers to the real destination."""
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        for key in ("uddg", "u", "url", "r", "q"):
            if key in qs and qs[key]:
                candidate = unquote(qs[key][0])
                if candidate.startswith("http"):
                    return candidate
        # /l/?kh=-1&uddg=...
        if "uddg=" in url:
            m = re.search(r"uddg=([^&]+)", url)
            if m:
                candidate = unquote(m.group(1))
                if candidate.startswith("http"):
                    return candidate
    except Exception:
        pass
    return url


def _http_get(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    accept: Optional[str] = None,
    follow_redirects: bool = True,
) -> httpx.Response:
    ok, err = _validate_public_url(url)
    if not ok:
        raise ValueError(err)
    cfg = _web_cfg()
    with httpx.Client(
        timeout=cfg["timeout"],
        follow_redirects=follow_redirects,
        headers=_headers(accept=accept or _headers()["Accept"]),
    ) as client:
        resp = client.get(url, params=params)
        # Re-validate final URL after redirects
        final = str(resp.url)
        ok2, err2 = _validate_public_url(final)
        if not ok2:
            raise ValueError(f"重定向目标不安全: {err2}")
        return resp


def _http_get_bytes(url: str, max_bytes: int, *, referer: str = "") -> Tuple[bytes, str]:
    ok, err = _validate_public_url(url)
    if not ok:
        raise ValueError(err)
    cfg = _web_cfg()
    headers = _headers(accept="image/avif,image/webp,image/apng,image/*,*/*;q=0.8")
    if referer:
        headers["Referer"] = referer
    else:
        # Many CDNs (Wikimedia etc.) reject empty/odd referrers
        parsed = urlparse(url)
        headers["Referer"] = f"{parsed.scheme}://{parsed.netloc}/"
    with httpx.Client(
        timeout=cfg["timeout"],
        follow_redirects=True,
        headers=headers,
    ) as client:
        with client.stream("GET", url) as resp:
            final = str(resp.url)
            ok2, err2 = _validate_public_url(final)
            if not ok2:
                raise ValueError(f"重定向目标不安全: {err2}")
            resp.raise_for_status()
            ctype = (resp.headers.get("content-type") or "application/octet-stream").split(";")[0].strip()
            chunks: List[bytes] = []
            total = 0
            for chunk in resp.iter_bytes():
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f"下载超过大小上限（{max_bytes} bytes）")
                chunks.append(chunk)
            return b"".join(chunks), ctype


# ---------------------------------------------------------------------------
# HTML text extraction
# ---------------------------------------------------------------------------


class _TextExtractor(HTMLParser):
    _SKIP = frozenset(
        {
            "script",
            "style",
            "noscript",
            "svg",
            "iframe",
            "canvas",
            "template",
            "head",
        }
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._parts: List[str] = []
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:
        t = tag.lower()
        if t in self._SKIP:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if t == "title":
            self._in_title = True
        if t in ("br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article"):
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
            return
        if t == "title":
            self._in_title = False
        if t in ("p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article"):
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title += text + " "
            return
        self._parts.append(text + " ")


def _html_to_text(raw_html: str) -> Tuple[str, str]:
    parser = _TextExtractor()
    try:
        parser.feed(raw_html)
        parser.close()
    except Exception:
        # Extremely broken HTML — fall back to tag strip
        text = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", " ", raw_html)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        text = html.unescape(text)
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return "", text.strip()
    title = re.sub(r"\s+", " ", parser.title).strip()
    body = "".join(parser._parts)
    body = html.unescape(body)
    body = re.sub(r"[ \t\r\f\v]+", " ", body)
    body = re.sub(r" *\n *", "\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return title, body.strip()


def _truncate(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    return text[: max(0, limit - 20)].rstrip() + "\n…(已截断)"


# ---------------------------------------------------------------------------
# Search backends
# ---------------------------------------------------------------------------


def _parse_ddg_html(page: str, limit: int) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    # Classic lite markup: <a class="result__a" href="...">title</a>
    for m in re.finditer(
        r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        page,
        flags=re.I | re.S,
    ):
        href = html.unescape(m.group(1))
        title = re.sub(r"<[^>]+>", "", m.group(2))
        title = html.unescape(re.sub(r"\s+", " ", title)).strip()
        url = _unwrap_redirect_url(href)
        if not url.startswith("http") or not title:
            continue
        # Snippet: next result__snippet after this anchor
        snip = ""
        tail = page[m.end() : m.end() + 1200]
        sm = re.search(
            r'class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</(?:a|td|div)>',
            tail,
            flags=re.I | re.S,
        )
        if sm:
            snip = re.sub(r"<[^>]+>", "", sm.group(1))
            snip = html.unescape(re.sub(r"\s+", " ", snip)).strip()
        results.append({"title": title, "url": url, "snippet": snip})
        if len(results) >= limit:
            break
    return results


def _parse_bing_html(page: str, limit: int) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    for block in re.finditer(r'<li class="b_algo"(.*?)</li>', page, flags=re.I | re.S):
        chunk = block.group(1)
        am = re.search(r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', chunk, flags=re.I | re.S)
        if not am:
            continue
        url = _unwrap_redirect_url(html.unescape(am.group(1)))
        title = re.sub(r"<[^>]+>", "", am.group(2))
        title = html.unescape(re.sub(r"\s+", " ", title)).strip()
        snip = ""
        pm = re.search(r'<p[^>]*>(.*?)</p>', chunk, flags=re.I | re.S)
        if pm:
            snip = re.sub(r"<[^>]+>", "", pm.group(1))
            snip = html.unescape(re.sub(r"\s+", " ", snip)).strip()
        if url.startswith("http") and title:
            results.append({"title": title, "url": url, "snippet": snip})
        if len(results) >= limit:
            break
    return results


def _ddg_instant(query: str) -> Dict[str, Any]:
    try:
        resp = _http_get(
            "https://api.duckduckgo.com/",
            params={
                "q": query,
                "format": "json",
                "no_html": "1",
                "skip_disambig": "1",
            },
            accept="application/json",
        )
        if resp.status_code != 200:
            return {}
        data = resp.json()
        if not isinstance(data, dict):
            return {}
        out: Dict[str, Any] = {}
        abstract = (data.get("AbstractText") or "").strip()
        if abstract:
            out["abstract"] = abstract
            out["abstract_source"] = data.get("AbstractSource") or ""
            out["abstract_url"] = data.get("AbstractURL") or ""
        answer = (data.get("Answer") or "").strip()
        if answer:
            out["answer"] = re.sub(r"<[^>]+>", "", answer)
        definition = (data.get("Definition") or "").strip()
        if definition:
            out["definition"] = definition
            out["definition_url"] = data.get("DefinitionURL") or ""
        related = []
        for item in data.get("RelatedTopics") or []:
            if isinstance(item, dict) and item.get("Text") and item.get("FirstURL"):
                related.append(
                    {
                        "text": item["Text"],
                        "url": item["FirstURL"],
                    }
                )
            if len(related) >= 5:
                break
        if related:
            out["related"] = related
        img = (data.get("Image") or "").strip()
        if img:
            if img.startswith("//"):
                img = "https:" + img
            elif img.startswith("/"):
                img = "https://duckduckgo.com" + img
            out["image"] = img
        return out
    except Exception as e:
        log.debug("ddg instant failed: %s", e)
        return {}


def _wikipedia_summary(query: str) -> Dict[str, Any]:
    """Lightweight zh/en Wikipedia opensearch + summary fallback."""
    for lang in ("zh", "en"):
        try:
            resp = _http_get(
                f"https://{lang}.wikipedia.org/w/api.php",
                params={
                    "action": "opensearch",
                    "search": query,
                    "limit": 1,
                    "namespace": 0,
                    "format": "json",
                },
                accept="application/json",
            )
            if resp.status_code != 200:
                continue
            data = resp.json()
            if not isinstance(data, list) or len(data) < 4 or not data[1]:
                continue
            title = data[1][0]
            url = data[3][0] if data[3] else ""
            sum_resp = _http_get(
                f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(title, safe='')}",
                accept="application/json",
            )
            if sum_resp.status_code != 200:
                return {"title": title, "url": url, "extract": data[2][0] if data[2] else ""}
            payload = sum_resp.json()
            extract = (payload.get("extract") or "").strip()
            page_url = (payload.get("content_urls") or {}).get("desktop", {}).get("page") or url
            thumb = ((payload.get("thumbnail") or {}).get("source") or "").strip()
            return {
                "title": payload.get("title") or title,
                "url": page_url,
                "extract": extract,
                "thumbnail": thumb,
                "lang": lang,
            }
        except Exception as e:
            log.debug("wikipedia %s failed: %s", lang, e)
            continue
    return {}


def _web_search_impl(query: str, limit: int) -> Tuple[List[Dict[str, str]], str, List[str]]:
    errors: List[str] = []
    # 1) DuckDuckGo HTML
    try:
        resp = _http_get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
        )
        if resp.status_code == 200:
            hits = _parse_ddg_html(resp.text, limit)
            if hits:
                return hits, "duckduckgo", errors
            errors.append("DuckDuckGo 未解析到结果")
        else:
            errors.append(f"DuckDuckGo HTTP {resp.status_code}")
    except Exception as e:
        errors.append(f"DuckDuckGo: {e}")

    # 2) Bing HTML fallback
    try:
        resp = _http_get(
            "https://www.bing.com/search",
            params={"q": query, "setlang": "zh-CN", "count": str(limit)},
        )
        if resp.status_code == 200:
            hits = _parse_bing_html(resp.text, limit)
            if hits:
                return hits, "bing", errors
            errors.append("Bing 未解析到结果")
        else:
            errors.append(f"Bing HTTP {resp.status_code}")
    except Exception as e:
        errors.append(f"Bing: {e}")

    return [], "", errors


def _ddg_vqd(query: str) -> str:
    resp = _http_get("https://duckduckgo.com/", params={"q": query})
    text = resp.text
    for pattern in (
        r'vqd=["\']([^"\']+)["\']',
        r"vqd=([\d-]+)&",
        r'"vqd":"([^"]+)"',
    ):
        m = re.search(pattern, text)
        if m:
            return m.group(1)
    raise ValueError("无法获取 DuckDuckGo vqd token")


def _search_images_ddg(query: str, limit: int) -> List[Dict[str, Any]]:
    vqd = _ddg_vqd(query)
    cfg = _web_cfg()
    ok, err = _validate_public_url("https://duckduckgo.com/i.js")
    if not ok:
        raise ValueError(err)
    with httpx.Client(
        timeout=cfg["timeout"],
        follow_redirects=True,
        headers={
            **_headers(accept="application/json, text/javascript, */*; q=0.01"),
            "Referer": "https://duckduckgo.com/",
        },
    ) as client:
        resp = client.get(
            "https://duckduckgo.com/i.js",
            params={
                "l": "us-en",
                "o": "json",
                "q": query,
                "vqd": vqd,
                "f": ",,,",
                "p": "1",
            },
        )
    if resp.status_code != 200:
        raise ValueError(f"DuckDuckGo 图片搜索 HTTP {resp.status_code}")
    try:
        data = resp.json()
    except json.JSONDecodeError:
        text = resp.text.strip()
        if text.startswith("{"):
            data = json.loads(text)
        else:
            raise ValueError("图片搜索返回非 JSON")
    results: List[Dict[str, Any]] = []
    for item in data.get("results") or []:
        if not isinstance(item, dict):
            continue
        image = (item.get("image") or "").strip()
        if not image.startswith("http"):
            continue
        results.append(
            {
                "title": (item.get("title") or "").strip(),
                "image_url": image,
                "thumbnail": (item.get("thumbnail") or "").strip(),
                "source_url": (item.get("url") or "").strip(),
                "width": item.get("width"),
                "height": item.get("height"),
            }
        )
        if len(results) >= limit:
            break
    return results


def _iter_bing_m_json(page: str):
    """Yield JSON objects from Bing image tile m=\"{...}\" attributes."""
    decoder = json.JSONDecoder()
    idx = 0
    n = len(page)
    while idx < n:
        i = page.find('m="', idx)
        if i < 0:
            break
        start = page.find("{", i)
        if start < 0:
            idx = i + 3
            continue
        # Attribute may contain HTML entities (&quot;)
        if page.startswith("{&quot;", start):
            end_attr = page.find('"', start + 1)
            if end_attr < 0:
                idx = start + 1
                continue
            raw = html.unescape(page[start:end_attr])
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                idx = start + 1
                continue
            if isinstance(obj, dict):
                yield obj
            idx = end_attr + 1
            continue
        try:
            obj, consumed = decoder.raw_decode(page[start:])
        except json.JSONDecodeError:
            idx = start + 1
            continue
        if isinstance(obj, dict):
            yield obj
        idx = start + consumed


def _search_images_bing(query: str, limit: int) -> List[Dict[str, Any]]:
    # Async endpoint returns denser, more stable tile metadata than the HTML page.
    resp = _http_get(
        "https://www.bing.com/images/async",
        params={"q": query, "first": "0", "count": str(max(limit * 3, 20)), "mmasync": "1"},
    )
    if resp.status_code != 200:
        raise ValueError(f"Bing 图片搜索 HTTP {resp.status_code}")
    results: List[Dict[str, Any]] = []
    seen = set()
    for obj in _iter_bing_m_json(resp.text):
        image = (obj.get("murl") or "").strip()
        if not image.startswith("http") or image in seen:
            continue
        seen.add(image)
        results.append(
            {
                "title": html.unescape((obj.get("t") or "").strip()),
                "image_url": image,
                "thumbnail": (obj.get("turl") or "").strip(),
                "source_url": (obj.get("purl") or "").strip(),
                "width": obj.get("w") or obj.get("width"),
                "height": obj.get("h") or obj.get("height"),
            }
        )
        if len(results) >= limit:
            break
    return results


def _search_images_impl(query: str, limit: int) -> Tuple[List[Dict[str, Any]], str, List[str]]:
    errors: List[str] = []
    # Bing async is currently more reliable than DDG i.js (often 403).
    try:
        hits = _search_images_bing(query, limit)
        if hits:
            return hits, "bing", errors
        errors.append("Bing 图片无结果")
    except Exception as e:
        errors.append(f"Bing: {e}")
    try:
        hits = _search_images_ddg(query, limit)
        if hits:
            return hits, "duckduckgo", errors
        errors.append("DuckDuckGo 图片无结果")
    except Exception as e:
        errors.append(f"DuckDuckGo: {e}")
    return [], "", errors


def _guess_name_from_url(url: str, mime: str) -> str:
    path = urlparse(url).path or ""
    base = path.rsplit("/", 1)[-1] if path else ""
    base = unquote(base).split("?")[0]
    if base and "." in base and len(base) < 120:
        return base
    ext = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }.get(mime, ".jpg")
    return f"web_image{ext}"


# ---------------------------------------------------------------------------
# Registered tools
# ---------------------------------------------------------------------------


@tool(
    name="web_search",
    description=(
        "在互联网上搜索与查询相关的网页结果（标题、链接、摘要）。"
        "适合查找官方文档、教程、规范、API 说明、引擎资产要求等公开信息。"
        "需要阅读某条结果全文时，再调用 fetch_webpage。"
    ),
    parameters=obj_schema(
        {
            "query": {
                "type": "string",
                "description": "搜索关键词或问题（建议具体，可含中英文）",
            },
            "limit": {
                "type": "integer",
                "default": 5,
                "description": "返回结果条数，1–10，默认 5",
            },
            "include_instant": {
                "type": "boolean",
                "default": True,
                "description": "是否附带百科/即时摘要（Wikipedia / Instant Answer）",
            },
        },
        required=["query"],
    ),
    category="web",
)
def web_search(
    query: str,
    limit: int = 5,
    include_instant: bool = True,
) -> ToolResult:
    if not _web_cfg()["enabled"]:
        return _disabled_result()
    q = (query or "").strip()
    if not q:
        return ToolResult(ok=False, error="query 不能为空")
    cfg = _web_cfg()
    limit = max(1, min(int(limit or 5), min(10, cfg["max_search_results"])))

    results, backend, errors = _web_search_impl(q, limit)
    data: Dict[str, Any] = {
        "query": q,
        "backend": backend or None,
        "results": results,
    }
    if include_instant:
        instant = _ddg_instant(q)
        wiki = _wikipedia_summary(q) if not instant.get("abstract") else {}
        if instant:
            data["instant"] = instant
        if wiki:
            data["wikipedia"] = wiki

    if not results and not data.get("instant") and not data.get("wikipedia"):
        detail = "；".join(errors) if errors else "无可用结果"
        return ToolResult(
            ok=False,
            error=f"网页搜索失败：{detail}",
            data=data,
        )

    msg_parts = [f"找到 {len(results)} 条网页结果"]
    if backend:
        msg_parts.append(f"（来源 {backend}）")
    if data.get("instant") or data.get("wikipedia"):
        msg_parts.append("，已附带摘要")
    return ToolResult(ok=True, data=data, message="".join(msg_parts))


@tool(
    name="fetch_webpage",
    description=(
        "抓取指定公开网页并提取可读正文（去掉脚本/样式）。"
        "用于阅读文档、教程、规范页面。仅支持 http/https 公网地址，禁止内网。"
        "长页面会截断；可用 start_chars 分段续读。"
    ),
    parameters=obj_schema(
        {
            "url": {
                "type": "string",
                "description": "要打开的网页 URL（http/https）",
            },
            "max_chars": {
                "type": "integer",
                "default": 8000,
                "description": "返回正文字符上限，默认 8000",
            },
            "start_chars": {
                "type": "integer",
                "default": 0,
                "description": "从正文第 N 个字符开始截取（用于续读）",
            },
        },
        required=["url"],
    ),
    category="web",
)
def fetch_webpage(
    url: str,
    max_chars: int = 8000,
    start_chars: int = 0,
) -> ToolResult:
    if not _web_cfg()["enabled"]:
        return _disabled_result()
    target = _unwrap_redirect_url((url or "").strip())
    ok, err = _validate_public_url(target)
    if not ok:
        return ToolResult(ok=False, error=err)

    cfg = _web_cfg()
    max_chars = max(500, min(int(max_chars or 8000), cfg["max_page_chars"]))
    start_chars = max(0, int(start_chars or 0))

    try:
        resp = _http_get(target)
        resp.raise_for_status()
    except Exception as e:
        return ToolResult(ok=False, error=f"抓取失败: {e}")

    ctype = (resp.headers.get("content-type") or "").lower()
    final_url = str(resp.url)
    raw = resp.text or ""

    if "application/json" in ctype:
        text = _truncate(raw, max_chars)
        return ToolResult(
            ok=True,
            data={
                "url": final_url,
                "content_type": ctype,
                "title": "",
                "text": text,
                "truncated": len(raw) > max_chars,
            },
            message="已获取 JSON 内容",
        )

    title, body = _html_to_text(raw) if ("html" in ctype or "<html" in raw[:500].lower()) else ("", raw)
    if start_chars:
        body = body[start_chars:]
    truncated = len(body) > max_chars
    text = _truncate(body, max_chars)
    return ToolResult(
        ok=True,
        data={
            "url": final_url,
            "content_type": ctype,
            "title": title,
            "text": text,
            "start_chars": start_chars,
            "truncated": truncated,
            "total_chars_from_start": len(body),
        },
        message=f"已提取网页正文「{title or final_url}」" + ("（已截断）" if truncated else ""),
    )


@tool(
    name="search_images",
    description=(
        "在互联网上搜索相关参考图片，返回图片直链、缩略图与来源页。"
        "适合查找姿势参考、概念图、材质参考、道具造型等。"
        "若当前模型支持视觉且需要仔细看图，再对感兴趣的 image_url 调用 fetch_image。"
    ),
    parameters=obj_schema(
        {
            "query": {
                "type": "string",
                "description": "图片搜索关键词（可含风格、视角，如「game character T-pose reference」）",
            },
            "limit": {
                "type": "integer",
                "default": 4,
                "description": "返回图片数量，1–8，默认 4",
            },
        },
        required=["query"],
    ),
    category="web",
)
def search_images(query: str, limit: int = 4) -> ToolResult:
    if not _web_cfg()["enabled"]:
        return _disabled_result()
    q = (query or "").strip()
    if not q:
        return ToolResult(ok=False, error="query 不能为空")
    cfg = _web_cfg()
    limit = max(1, min(int(limit or 4), min(8, cfg["max_images"] * 2)))

    results, backend, errors = _search_images_impl(q, limit)
    if not results:
        detail = "；".join(errors) if errors else "无可用结果"
        return ToolResult(ok=False, error=f"图片搜索失败：{detail}")

    return ToolResult(
        ok=True,
        data={"query": q, "backend": backend, "results": results},
        message=f"找到 {len(results)} 张图片（来源 {backend}）",
    )


@tool(
    name="fetch_image",
    description=(
        "下载一张公开网络图片并附带到对话中，供视觉模型分析。"
        "通常先 search_images 得到 image_url，再对本工具传入该 URL；"
        "建议同时传入 thumbnail 作为 fallback_url，直链被拒时自动改下缩略图。"
        "也可直接传入已知的图片直链。仅当当前模型支持视觉时可用。"
    ),
    parameters=obj_schema(
        {
            "url": {
                "type": "string",
                "description": "图片直链 URL（http/https）",
            },
            "fallback_url": {
                "type": "string",
                "default": "",
                "description": "备用图片 URL（通常填 search_images 返回的 thumbnail）",
            },
            "name": {
                "type": "string",
                "default": "",
                "description": "可选显示名，便于在对话中区分多张图",
            },
            "note": {
                "type": "string",
                "default": "",
                "description": "可选说明，记录下载意图（如「手臂姿势参考」）",
            },
            "referer": {
                "type": "string",
                "default": "",
                "description": "可选 Referer（部分图床需要来源页才能下载；可填 search_images 的 source_url）",
            },
        },
        required=["url"],
    ),
    category="web",
    requires_vision=True,
)
def fetch_image(
    url: str,
    fallback_url: str = "",
    name: str = "",
    note: str = "",
    referer: str = "",
) -> ToolResult:
    if not _web_cfg()["enabled"]:
        return _disabled_result()

    cfg = _web_cfg()
    ref = (referer or "").strip()
    if ref:
        ok_r, _ = _validate_public_url(ref)
        if not ok_r:
            ref = ""

    candidates: List[str] = []
    for candidate in (url, fallback_url):
        target = _unwrap_redirect_url((candidate or "").strip())
        if not target or target in candidates:
            continue
        ok, err = _validate_public_url(target)
        if not ok:
            if not candidates:
                return ToolResult(ok=False, error=err)
            continue
        candidates.append(target)
    if not candidates:
        return ToolResult(ok=False, error="未提供有效图片 URL")

    last_err = ""
    raw = b""
    ctype = ""
    used = ""
    for target in candidates:
        try:
            raw, ctype = _http_get_bytes(target, cfg["max_download_bytes"], referer=ref)
            used = target
            break
        except Exception as e:
            last_err = str(e)
            continue
    if not used:
        return ToolResult(ok=False, error=f"下载图片失败: {last_err}")

    if not ctype.startswith("image/"):
        # Some CDNs return octet-stream; sniff magic
        if raw[:3] == b"\xff\xd8\xff":
            ctype = "image/jpeg"
        elif raw[:8] == b"\x89PNG\r\n\x1a\n":
            ctype = "image/png"
        elif raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
            ctype = "image/webp"
        elif raw[:6] in (b"GIF87a", b"GIF89a"):
            ctype = "image/gif"
        else:
            return ToolResult(
                ok=False,
                error=f"URL 返回的不是图片（Content-Type: {ctype}）",
            )

    display = (name or "").strip() or _guess_name_from_url(used, ctype)
    try:
        attachment = attachment_from_bytes(raw, mime=ctype, name=display)
    except Exception as e:
        return ToolResult(ok=False, error=f"图片编码失败: {e}")

    msg = f"已下载网络图片：{display}"
    if used != candidates[0]:
        msg += "（已使用备用缩略图）"
    if note:
        msg = f"{msg}（{note}）"
    return ToolResult(
        ok=True,
        data={
            "url": used,
            "requested_url": candidates[0],
            "mime": attachment.mime,
            "name": attachment.name,
            "bytes": len(raw),
        },
        message=msg,
        images=[attachment],
    )


@tool(
    name="fetch_images",
    description=(
        "批量下载多张公开网络图片并附带到对话（最多 4 张），供视觉模型对比参考。"
        "仅当当前模型支持视觉时可用。失败的 URL 会在结果中标明。"
    ),
    parameters=obj_schema(
        {
            "urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": "图片直链 URL 列表",
            },
            "note": {
                "type": "string",
                "default": "",
                "description": "可选说明",
            },
        },
        required=["urls"],
    ),
    category="web",
    requires_vision=True,
)
def fetch_images(urls: List[str], note: str = "") -> ToolResult:
    if not _web_cfg()["enabled"]:
        return _disabled_result()
    items = [u.strip() for u in (urls or []) if isinstance(u, str) and u.strip()]
    if not items:
        return ToolResult(ok=False, error="urls 不能为空")
    items = items[:MAX_IMAGES]

    images = []
    details: List[Dict[str, Any]] = []
    for u in items:
        r = fetch_image(url=u, note="")
        if r.ok and r.images:
            images.extend(r.images)
            details.append({"url": u, "ok": True, "name": r.data.get("name") if isinstance(r.data, dict) else ""})
        else:
            details.append({"url": u, "ok": False, "error": r.error})

    if not images:
        return ToolResult(ok=False, error="全部图片下载失败", data={"items": details})

    msg = f"已下载 {len(images)}/{len(items)} 张网络图片"
    if note:
        msg = f"{msg}（{note}）"
    return ToolResult(
        ok=True,
        data={"items": details, "attached": len(images)},
        message=msg,
        images=images,
    )
