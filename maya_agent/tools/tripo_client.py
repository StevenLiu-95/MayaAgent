"""Tripo REST API client (v3 async task create / poll / download)."""

from __future__ import annotations

import mimetypes
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

from maya_agent.utils.config import get_config
from maya_agent.utils.logger import get_logger

log = get_logger("maya_agent.tripo")

# Logical endpoint id → path under base_url (already includes /v3 when base is …/v3).
ENDPOINT_PATHS: Dict[str, str] = {
    "text-to-model": "/generation/text-to-model",
    "image-to-model": "/generation/image-to-model",
    "multiview-to-model": "/generation/multiview-to-model",
    "text-to-image": "/generation/text-to-image",
    "image-to-image": "/generation/image-to-image",
    "image-to-multiview": "/generation/image-to-multiview",
    "edit-multiview": "/generation/edit-multiview",
    "texture": "/models/texture",
    "convert": "/models/convert",
    "mesh-segment": "/mesh/segment",
    "mesh-complete": "/mesh/complete",
    "mesh-decimate": "/mesh/decimate",
    "rig-check": "/animations/rig-check",
    "rig": "/animations/rig",
    "retarget": "/animations/retarget",
}

TERMINAL_STATUSES = frozenset({"success", "failed", "cancelled"})
SUCCESS_STATUS = "success"

# Static animation presets from Tripo docs (no list API).
ANIMATION_PRESETS: Dict[str, List[str]] = {
    "rig_v2.5_biped": [
        "preset:idle",
        "preset:walk",
        "preset:run",
        "preset:dive",
        "preset:climb",
        "preset:jump",
        "preset:slash",
        "preset:shoot",
        "preset:hurt",
        "preset:fall",
        "preset:turn",
    ],
    "rig_v2.5_other": [
        "preset:quadruped:walk",
        "preset:hexapod:walk",
        "preset:octopod:walk",
        "preset:serpentine:march",
        "preset:aquatic:march",
    ],
    "rig_v1.0_biped": [
        "preset:biped:idle",
        "preset:biped:walk",
        "preset:biped:run",
        "preset:biped:jump",
        "preset:biped:wave_goodbye_01",
        "preset:biped:dance_01",
        "preset:biped:cheer",
        "preset:biped:sit",
        "preset:biped:slash",
        "preset:biped:shoot",
        "preset:biped:hurt",
        "preset:biped:fall",
        "preset:biped:turn",
        "preset:biped:greet_01",
        "preset:biped:victory_celebration",
    ],
}

_invalid_key_fp: Optional[str] = None


def _key_fingerprint(key: str) -> str:
    import hashlib

    return hashlib.sha256((key or "").encode("utf-8")).hexdigest()[:24]


def mark_tripo_key_invalid(key: Optional[str] = None) -> None:
    global _invalid_key_fp
    k = (key if key is not None else get_tripo_api_key()).strip()
    if k:
        _invalid_key_fp = _key_fingerprint(k)
        log.info("Tripo API key marked invalid (tools will be hidden from LLM)")


def mark_tripo_key_valid(key: Optional[str] = None) -> None:
    global _invalid_key_fp
    k = (key if key is not None else get_tripo_api_key()).strip()
    if not k:
        _invalid_key_fp = None
        return
    if _invalid_key_fp and _invalid_key_fp == _key_fingerprint(k):
        _invalid_key_fp = None
        log.info("Tripo API key marked valid")
    else:
        _invalid_key_fp = None


def clear_tripo_key_validity() -> None:
    global _invalid_key_fp
    _invalid_key_fp = None


def tripo_tools_available() -> bool:
    conf = tripo_cfg()
    if not conf["enabled"]:
        return False
    key = get_tripo_api_key()
    if not key:
        return False
    if _invalid_key_fp and _key_fingerprint(key) == _invalid_key_fp:
        return False
    return True


def filter_system_prompt_tripo(text: str) -> str:
    """Strip Tripo guidance when tools are unavailable."""
    if tripo_tools_available():
        return text
    lines = text.splitlines(keepends=True)
    out: List[str] = []
    skipping = False
    for line in lines:
        stripped = line.lstrip()
        is_heading = stripped.startswith("#") and not stripped.startswith("#" * 7)
        heading_text = ""
        if is_heading:
            # e.g. "# Tripo" / "### 工具开发"
            heading_text = stripped.lstrip("#").strip()
        if not skipping and is_heading and heading_text.startswith("Tripo"):
            skipping = True
            continue
        if skipping:
            if is_heading and not heading_text.startswith("Tripo"):
                skipping = False
                out.append(line)
            continue
        if stripped.startswith("|") and "Tripo" in line:
            continue
        out.append(line)
    return "".join(out)


class TripoError(Exception):
    def __init__(self, message: str, *, status_code: int = 0, payload: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


def tripo_cfg() -> Dict[str, Any]:
    cfg = get_config()
    return {
        "enabled": bool(cfg.get("tripo.enabled", True)),
        "base_url": str(
            cfg.get("tripo.base_url") or "https://openapi.tripo3d.com/v3"
        ).rstrip("/"),
        "api_key_env": str(cfg.get("tripo.api_key_env") or "TRIPO_API_KEY"),
        "timeout": float(cfg.get("tripo.timeout", 60) or 60),
        "upload_timeout": float(cfg.get("tripo.upload_timeout", 180) or 180),
        "upload_timeout_per_mb": float(cfg.get("tripo.upload_timeout_per_mb", 15) or 15),
        "upload_timeout_max": float(cfg.get("tripo.upload_timeout_max", 900) or 900),
        "upload_retries": int(cfg.get("tripo.upload_retries", 2) or 2),
        "poll_interval": float(cfg.get("tripo.poll_interval", 5) or 5),
        "wait_timeout": float(cfg.get("tripo.wait_timeout", 600) or 600),
        "download_dir": str(cfg.get("tripo.download_dir") or ""),
        "default_model": str(cfg.get("tripo.default_model") or "v3.1-20260211"),
        "default_image_model": str(
            cfg.get("tripo.default_image_model") or "seedream_v4"
        ),
        "default_formats": list(cfg.get("tripo.default_formats") or ["fbx", "glb"]),
    }


def get_tripo_api_key() -> str:
    cfg = get_config()
    key = (cfg.get_api_key("tripo") or "").strip()
    if key:
        return key
    import os

    env_name = tripo_cfg()["api_key_env"]
    return (os.environ.get(env_name) or "").strip()


def download_dir() -> Path:
    from maya_agent.utils.paths import agent_temp_subdir

    conf = tripo_cfg()
    raw = (conf.get("download_dir") or "").strip()
    if raw:
        path = Path(raw)
        path.mkdir(parents=True, exist_ok=True)
        return path
    return agent_temp_subdir("tripo_downloads")


def httpx_timeout_for_upload(
    file_bytes: int,
    *,
    base_timeout: Optional[float] = None,
) -> httpx.Timeout:
    conf = tripo_cfg()
    base = float(base_timeout if base_timeout is not None else conf["timeout"])
    if file_bytes <= 256 * 1024:
        return httpx.Timeout(base)
    upload_base = float(conf["upload_timeout"])
    per_mb = float(conf["upload_timeout_per_mb"])
    upload_max = float(conf["upload_timeout_max"])
    mb = file_bytes / (1024.0 * 1024.0)
    write = min(upload_max, max(upload_base, mb * per_mb))
    read = max(base, 120.0)
    return httpx.Timeout(connect=30.0, read=read, write=write, pool=30.0)


def _is_transient_error(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, TripoError):
        msg = str(exc).lower()
        return (
            "请求超时" in str(exc)
            or "timed out" in msg
            or "disconnected" in msg
            or "网络错误" in str(exc)
        )
    return False


def _unwrap_response(body: Any, *, http_status: int) -> Any:
    """Tripo wraps payloads as {code, data, message, suggestion}."""
    if not isinstance(body, dict):
        return body
    if "code" not in body:
        return body
    code = body.get("code")
    try:
        code_i = int(code)
    except (TypeError, ValueError):
        code_i = -1
    if code_i == 0:
        return body.get("data")
    msg = str(body.get("message") or "").strip()
    suggestion = str(body.get("suggestion") or "").strip()
    parts = [f"Tripo API 错误（code={code_i}"]
    if http_status:
        parts[0] += f", http={http_status}"
    parts[0] += "）"
    if msg:
        parts.append(msg)
    if suggestion:
        parts.append(f"建议：{suggestion}")
    raise TripoError(
        "：".join(parts) if len(parts) == 1 else f"{parts[0]}：{'；'.join(parts[1:])}",
        status_code=http_status or code_i,
        payload=body,
    )


def _format_http_error(status: int, body: Any) -> str:
    msg = ""
    suggestion = ""
    if isinstance(body, dict):
        msg = str(body.get("message") or body.get("error") or "").strip()
        suggestion = str(body.get("suggestion") or "").strip()
        if not msg and body.get("code") is not None:
            msg = f"code={body.get('code')}"
    elif isinstance(body, str):
        msg = body.strip()
    if status == 401:
        return "Tripo 鉴权失败（401）：请检查设置中的 Tripo API Key 或环境变量 TRIPO_API_KEY。"
    if status == 402:
        return f"Tripo 积分不足（402）{('：' + msg) if msg else '。请充值后再试。'}"
    if status == 429:
        return f"Tripo 请求过于频繁（429）{('：' + msg) if msg else '。请稍后重试。'}"
    extra = msg
    if suggestion:
        extra = f"{extra}；建议：{suggestion}" if extra else f"建议：{suggestion}"
    if extra:
        return f"Tripo API 错误（{status}）：{extra}"
    return f"Tripo API 错误（{status}）"


def drop_none(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None and v != ""}


def summarize_task(task: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(task, dict):
        return {"raw": task}
    out: Dict[str, Any] = {
        "task_id": task.get("task_id") or task.get("id"),
        "type": task.get("type"),
        "status": task.get("status"),
        "progress": task.get("progress"),
        "credits_consumed": task.get("credits_consumed"),
        "created_at": task.get("created_at"),
        "completed_at": task.get("completed_at"),
    }
    output = task.get("output")
    if isinstance(output, dict):
        slim: Dict[str, Any] = {}
        for key in (
            "model_url",
            "pbr_model_url",
            "rendered_image_url",
            "generated_image_url",
            "riggable",
            "rig_type",
        ):
            if key in output and output[key] is not None:
                slim[key] = output[key]
        # Multiview / extra urls
        for key, val in output.items():
            if key.endswith("_url") and key not in slim and val:
                slim[key] = val
            if key in ("images", "image_urls", "multiview_images") and val:
                slim[key] = val
        if slim:
            out["output"] = slim
    err = task.get("error") or task.get("message")
    if err:
        out["error"] = err
    return out


def pick_output_urls(task: Dict[str, Any]) -> Dict[str, str]:
    """Collect downloadable URLs from a succeeded task output."""
    output = task.get("output") if isinstance(task.get("output"), dict) else {}
    urls: Dict[str, str] = {}
    for key, val in (output or {}).items():
        if isinstance(val, str) and val.startswith(("http://", "https://")):
            urls[key] = val
        elif isinstance(val, list):
            for i, item in enumerate(val):
                if isinstance(item, str) and item.startswith(("http://", "https://")):
                    urls[f"{key}_{i}"] = item
                elif isinstance(item, dict):
                    for ik, iv in item.items():
                        if isinstance(iv, str) and iv.startswith(("http://", "https://")):
                            urls[f"{key}_{i}_{ik}"] = iv
    return urls


def pick_model_url(
    task: Dict[str, Any],
    *,
    prefer: Optional[List[str]] = None,
) -> Tuple[str, str]:
    """
    Return (format, url) for a succeeded model task.

    Prefer FBX when URL path suggests it; otherwise use output.model_url / pbr_model_url.
    """
    prefs = [p.lower() for p in (prefer or tripo_cfg().get("default_formats") or ["fbx", "glb"])]
    urls = pick_output_urls(task)
    if not urls:
        raise TripoError("任务结果中没有可下载的模型 URL（output）")

    def _fmt_from_url(u: str) -> str:
        low = u.lower().split("?", 1)[0]
        for ext in ("fbx", "glb", "gltf", "obj", "stl", "usdz", "png", "jpg", "jpeg", "webp"):
            if low.endswith("." + ext):
                return "jpg" if ext == "jpeg" else ext
        return "glb"

    # Prefer keys that look like model urls, ordered by format preference
    candidates: List[Tuple[str, str, str]] = []  # fmt, key, url
    for key, url in urls.items():
        fmt = _fmt_from_url(url)
        candidates.append((fmt, key, url))

    for pref in prefs:
        for fmt, key, url in candidates:
            if fmt == pref and "model" in key:
                return fmt, url
        for fmt, key, url in candidates:
            if fmt == pref:
                return fmt, url

    # Fallback: any model_url-like
    for fmt, key, url in candidates:
        if "model" in key:
            return fmt, url
    fmt, _key, url = candidates[0]
    return fmt, url


def pick_image_urls(task: Dict[str, Any]) -> List[str]:
    urls = pick_output_urls(task)
    out: List[str] = []
    preferred_keys = (
        "generated_image_url",
        "rendered_image_url",
        "image_url",
    )
    for key in preferred_keys:
        if key in urls:
            out.append(urls[key])
    for key, url in urls.items():
        if url in out:
            continue
        low = key.lower()
        if "image" in low or url.lower().split("?", 1)[0].endswith(
            (".png", ".jpg", ".jpeg", ".webp")
        ):
            out.append(url)
    return out


class TripoClient:
    def __init__(self, api_key: Optional[str] = None) -> None:
        conf = tripo_cfg()
        if not conf["enabled"]:
            raise TripoError("Tripo 已在配置中关闭（tripo.enabled=false）。")
        self.api_key = (api_key or get_tripo_api_key()).strip()
        if not self.api_key:
            raise TripoError(
                "未配置 Tripo API Key。请在「模型 → Tripo」填写，"
                f"或设置环境变量 {conf['api_key_env']}。"
            )
        self.base_url = conf["base_url"]
        self.timeout = conf["timeout"]
        self.upload_retries = int(conf.get("upload_retries", 2) or 2)
        self.poll_interval = conf["poll_interval"]
        self.wait_timeout = conf["wait_timeout"]
        self.default_model = conf["default_model"]
        self.default_image_model = conf["default_image_model"]
        self.default_formats = list(conf["default_formats"] or ["fbx", "glb"])

    def _auth_headers(self, *, json_body: bool = True) -> Dict[str, str]:
        h = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "User-Agent": "MayaAgent/1.5 TripoClient",
        }
        if json_body:
            h["Content-Type"] = "application/json"
        return h

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{path}"

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[httpx.Timeout] = None,
        retries: int = 0,
        files: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Any, httpx.Headers]:
        url = self._url(path)
        req_timeout = timeout or httpx.Timeout(self.timeout)
        attempts = max(1, int(retries) + 1)
        last_exc: Optional[BaseException] = None
        use_json = files is None

        for attempt in range(attempts):
            try:
                with httpx.Client(timeout=req_timeout, follow_redirects=True) as client:
                    kwargs: Dict[str, Any] = {
                        "headers": self._auth_headers(json_body=use_json),
                        "params": params,
                    }
                    if files is not None:
                        kwargs["files"] = files
                    elif json_body is not None:
                        kwargs["json"] = json_body
                    resp = client.request(method.upper(), url, **kwargs)
            except httpx.TimeoutException as e:
                last_exc = e
                if attempt + 1 < attempts and _is_transient_error(e):
                    log.warning(
                        "Tripo timeout %s %s attempt %s/%s: %s",
                        method,
                        path,
                        attempt + 1,
                        attempts,
                        e,
                    )
                    time.sleep(min(8.0, 1.5 * (2**attempt)))
                    continue
                raise TripoError(f"Tripo 请求超时：{e}") from e
            except httpx.HTTPError as e:
                last_exc = e
                if attempt + 1 < attempts and _is_transient_error(e):
                    log.warning(
                        "Tripo transport error %s %s attempt %s/%s: %s",
                        method,
                        path,
                        attempt + 1,
                        attempts,
                        e,
                    )
                    time.sleep(min(8.0, 1.5 * (2**attempt)))
                    continue
                raise TripoError(f"Tripo 网络错误：{e}") from e

            body: Any
            try:
                body = resp.json() if resp.content else None
            except Exception:
                body = (resp.text or "")[:500]

            if resp.status_code >= 400:
                if resp.status_code == 401:
                    mark_tripo_key_invalid(self.api_key)
                if (
                    resp.status_code >= 500
                    and attempt + 1 < attempts
                    and method.upper() == "POST"
                ):
                    log.warning(
                        "Tripo HTTP %s on %s %s attempt %s/%s — retrying",
                        resp.status_code,
                        method,
                        path,
                        attempt + 1,
                        attempts,
                    )
                    time.sleep(min(8.0, 1.5 * (2**attempt)))
                    continue
                raise TripoError(
                    _format_http_error(resp.status_code, body),
                    status_code=resp.status_code,
                    payload=body,
                )

            try:
                data = _unwrap_response(body, http_status=resp.status_code)
            except TripoError as e:
                # Business error with HTTP 200 but code != 0
                if e.status_code == 2010 or "Insufficient credits" in str(e):
                    raise
                raise

            mark_tripo_key_valid(self.api_key)
            return data, resp.headers

        raise TripoError(f"Tripo 请求失败：{last_exc}")

    def upload_file(self, path: str) -> str:
        p = Path(path)
        if not p.is_file():
            raise TripoError(f"文件不存在: {path}")
        size = p.stat().st_size
        mime = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
        retries = self.upload_retries if size > 256 * 1024 else 0
        timeout = httpx_timeout_for_upload(size, base_timeout=self.timeout)
        log.info(
            "Tripo upload %s (%.1fMB, write_timeout=%s, retries=%s)",
            p.name,
            size / (1024.0 * 1024.0),
            getattr(timeout, "write", None),
            retries,
        )
        with open(p, "rb") as f:
            data, _ = self.request(
                "POST",
                "/files",
                files={"file": (p.name, f, mime)},
                timeout=timeout,
                retries=retries,
            )
        token = ""
        if isinstance(data, dict):
            token = str(data.get("file_token") or data.get("token") or "")
        elif isinstance(data, str):
            token = data
        if not token:
            raise TripoError(f"上传未返回 file_token：{data}")
        return token

    def create(self, endpoint: str, body: Dict[str, Any]) -> str:
        path = ENDPOINT_PATHS.get(endpoint)
        if not path:
            raise TripoError(
                f"未知端点: {endpoint}。可选: {', '.join(sorted(ENDPOINT_PATHS))}"
            )
        data, _ = self.request("POST", path, json_body=body or {})
        task_id = ""
        if isinstance(data, dict):
            task_id = str(data.get("task_id") or data.get("id") or "")
        if not task_id:
            raise TripoError(f"创建任务未返回 task_id：{data}")
        return task_id

    def get_task(self, task_id: str) -> Dict[str, Any]:
        tid = (task_id or "").strip()
        if not tid:
            raise TripoError("task_id 为空")
        data, _ = self.request("GET", f"/tasks/{tid}")
        if not isinstance(data, dict):
            raise TripoError(f"任务响应异常：{data}")
        return data

    def list_tasks(self, body: Optional[Dict[str, Any]] = None) -> Any:
        data, _ = self.request("POST", "/tasks/list", json_body=body or {})
        return data

    def wait(
        self,
        task_id: str,
        *,
        timeout: Optional[float] = None,
        poll_interval: Optional[float] = None,
        on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
        endpoint: str = "",
    ) -> Dict[str, Any]:
        limit = float(timeout if timeout is not None else self.wait_timeout)
        interval = float(
            poll_interval if poll_interval is not None else self.poll_interval
        )
        deadline = time.monotonic() + max(5.0, limit)
        last: Dict[str, Any] = {}
        last_status = ""
        last_progress: Any = object()

        def _progress_value(task: Dict[str, Any]) -> Any:
            """Read progress from top-level or nested output (API variants)."""
            if task.get("progress") is not None:
                return task.get("progress")
            output = task.get("output")
            if isinstance(output, dict) and output.get("progress") is not None:
                return output.get("progress")
            return None

        def _emit() -> None:
            if on_progress is None:
                return
            status = str(last.get("status") or "")
            progress = _progress_value(last)
            nonlocal last_status, last_progress
            if status == last_status and progress == last_progress:
                return
            last_status = status
            last_progress = progress
            try:
                on_progress(
                    {
                        "endpoint": endpoint,
                        "task_id": task_id,
                        "status": status,
                        "progress": progress,
                    }
                )
            except Exception:
                log.exception(
                    "Tripo on_progress callback failed (task_id=%s status=%s)",
                    task_id,
                    status,
                )

        while True:
            last = self.get_task(task_id)
            status = str(last.get("status") or "").lower()
            _emit()
            if status in TERMINAL_STATUSES:
                if status != SUCCESS_STATUS:
                    err = ""
                    if isinstance(last.get("output"), dict):
                        err = str(last["output"].get("error") or "")
                    err = err or str(last.get("message") or last.get("error") or "")
                    raise TripoError(
                        f"Tripo 任务 {status}" + (f"：{err}" if err else ""),
                        payload=last,
                    )
                return last
            if time.monotonic() >= deadline:
                raise TripoError(
                    f"等待 Tripo 任务超时（{limit:.0f}s），当前 status={status or '未知'} "
                    f"progress={last.get('progress')}",
                    payload=last,
                )
            time.sleep(max(1.0, interval))

    def balance(self) -> Dict[str, Any]:
        data, _ = self.request("GET", "/account/balance")
        if not isinstance(data, dict):
            raise TripoError(f"余额响应异常：{data}")
        return data

    def usage(self) -> Any:
        data, _ = self.request("GET", "/account/usage")
        return data

    def download(self, url: str, dest: Path) -> Path:
        u = (url or "").strip()
        if not u:
            raise TripoError("下载 URL 为空")
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with httpx.Client(
                timeout=max(self.timeout, 120.0), follow_redirects=True
            ) as client:
                with client.stream(
                    "GET",
                    u,
                    headers={"User-Agent": "MayaAgent/1.5 TripoClient"},
                ) as resp:
                    if resp.status_code >= 400:
                        raise TripoError(f"下载失败（{resp.status_code}）")
                    with open(dest, "wb") as f:
                        for chunk in resp.iter_bytes():
                            if chunk:
                                f.write(chunk)
        except TripoError:
            raise
        except httpx.HTTPError as e:
            raise TripoError(f"下载网络错误：{e}") from e
        return dest

    def resolve_file_input(
        self,
        *,
        url: str = "",
        path: str = "",
        file_token: str = "",
        task_id: str = "",
    ) -> str:
        """
        Resolve to a Tripo ``input`` value: task_id, file_token, or public URL.

        Local paths are uploaded via POST /files.
        """
        tid = (task_id or "").strip()
        if tid:
            return tid
        token = (file_token or "").strip()
        if token:
            return token
        local = (path or "").strip()
        if local:
            if not Path(local).is_file():
                raise TripoError(f"文件不存在: {local}")
            return self.upload_file(local)
        u = (url or "").strip()
        if u:
            if u.startswith(("http://", "https://")):
                return u
            if u.startswith("file_") or u.startswith("task_"):
                return u
            if Path(u).is_file():
                return self.upload_file(u)
            return u
        raise TripoError("需要提供 task_id、file_token、url 或本地 path 之一")
