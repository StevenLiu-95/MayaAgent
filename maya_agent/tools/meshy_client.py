"""Meshy REST API client (async task create / poll / download)."""

from __future__ import annotations

import base64
import mimetypes
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

from maya_agent.utils.config import get_config
from maya_agent.utils.logger import get_logger

log = get_logger("maya_agent.meshy")

# Logical kind → API collection path (under base_url).
KIND_PATHS: Dict[str, str] = {
    "text-to-3d": "/v2/text-to-3d",
    "image-to-3d": "/v1/image-to-3d",
    "multi-image-to-3d": "/v1/multi-image-to-3d",
    "retexture": "/v1/retexture",
    "remesh": "/v1/remesh",
    "convert": "/v1/convert",
    "resize": "/v1/resize",
    "uv-unwrap": "/v1/uv-unwrap",
    "rigging": "/v1/rigging",
    "animations": "/v1/animations",
}

TERMINAL_STATUSES = frozenset({"SUCCEEDED", "FAILED", "CANCELED"})

# Fingerprint of a key that returned HTTP 401 — hide meshy tools until key changes.
_invalid_key_fp: Optional[str] = None


def _key_fingerprint(key: str) -> str:
    import hashlib

    return hashlib.sha256((key or "").encode("utf-8")).hexdigest()[:24]


def mark_meshy_key_invalid(key: Optional[str] = None) -> None:
    """Remember that this API key failed auth (401)."""
    global _invalid_key_fp
    k = (key if key is not None else get_meshy_api_key()).strip()
    if k:
        _invalid_key_fp = _key_fingerprint(k)
        log.info("Meshy API key marked invalid (tools will be hidden from LLM)")


def mark_meshy_key_valid(key: Optional[str] = None) -> None:
    """Clear invalid flag after a successful authenticated call / test."""
    global _invalid_key_fp
    k = (key if key is not None else get_meshy_api_key()).strip()
    if not k:
        _invalid_key_fp = None
        return
    if _invalid_key_fp and _invalid_key_fp == _key_fingerprint(k):
        _invalid_key_fp = None
        log.info("Meshy API key marked valid")
    elif _invalid_key_fp is None:
        return
    else:
        # Different key succeeded — drop stale invalid marker
        _invalid_key_fp = None


def clear_meshy_key_validity() -> None:
    """Reset cached auth state (e.g. after user edits the key in settings)."""
    global _invalid_key_fp
    _invalid_key_fp = None


def meshy_tools_available() -> bool:
    """
    Whether meshy_* tools should be exposed to the LLM.

    Hidden when: meshy.enabled is false, no API key, or the current key
    previously returned HTTP 401.
    """
    conf = meshy_cfg()
    if not conf["enabled"]:
        return False
    key = get_meshy_api_key()
    if not key:
        return False
    if _invalid_key_fp and _key_fingerprint(key) == _invalid_key_fp:
        return False
    return True


def filter_system_prompt_meshy(text: str) -> str:
    """Strip Meshy guidance from the system prompt when tools are unavailable."""
    if meshy_tools_available():
        return text
    lines = text.splitlines(keepends=True)
    out: List[str] = []
    skipping = False
    for line in lines:
        stripped = line.lstrip()
        if not skipping and stripped.startswith("## Meshy"):
            skipping = True
            continue
        if skipping:
            if stripped.startswith("## ") and not stripped.startswith("## Meshy"):
                skipping = False
                out.append(line)
            continue
        # Drop table rows that only describe Meshy routing
        if stripped.startswith("|") and "Meshy" in line:
            continue
        out.append(line)
    return "".join(out)

_IMAGE_EXT = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
_MODEL_EXT = {
    ".glb": "application/octet-stream",
    ".gltf": "application/octet-stream",
    ".fbx": "application/octet-stream",
    ".obj": "application/octet-stream",
    ".stl": "application/octet-stream",
}


class MeshyError(Exception):
    def __init__(self, message: str, *, status_code: int = 0, payload: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


def meshy_cfg() -> Dict[str, Any]:
    cfg = get_config()
    return {
        "enabled": bool(cfg.get("meshy.enabled", True)),
        "base_url": str(cfg.get("meshy.base_url") or "https://api.meshy.ai/openapi").rstrip("/"),
        "api_key_env": str(cfg.get("meshy.api_key_env") or "MESHY_API_KEY"),
        "timeout": float(cfg.get("meshy.timeout", 60) or 60),
        "poll_interval": float(cfg.get("meshy.poll_interval", 5) or 5),
        "wait_timeout": float(cfg.get("meshy.wait_timeout", 600) or 600),
        "download_dir": str(cfg.get("meshy.download_dir") or ""),
        "default_formats": list(cfg.get("meshy.default_formats") or ["fbx", "glb"]),
    }


def get_meshy_api_key() -> str:
    cfg = get_config()
    key = (cfg.get_api_key("meshy") or "").strip()
    if key:
        return key
    env_name = meshy_cfg()["api_key_env"]
    import os

    return (os.environ.get(env_name) or "").strip()


def download_dir() -> Path:
    """
    Meshy temp model download directory.

    Prefer ``meshy.download_dir`` when set; otherwise
    ``{agent_temp_root}/meshy_downloads``.
    """
    from maya_agent.utils.paths import agent_temp_subdir

    conf = meshy_cfg()
    raw = (conf.get("download_dir") or "").strip()
    if raw:
        path = Path(raw)
        path.mkdir(parents=True, exist_ok=True)
        return path
    return agent_temp_subdir("meshy_downloads")


def file_to_data_uri(path: str, *, as_model: bool = False) -> str:
    p = Path(path)
    if not p.is_file():
        raise MeshyError(f"文件不存在: {path}")
    suffix = p.suffix.lower()
    if as_model:
        mime = _MODEL_EXT.get(suffix) or "application/octet-stream"
    else:
        mime = _IMAGE_EXT.get(suffix) or mimetypes.guess_type(str(p))[0] or "application/octet-stream"
    data = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def resolve_image_input(*, image_url: str = "", image_path: str = "") -> str:
    url = (image_url or "").strip()
    path = (image_path or "").strip()
    if path:
        return file_to_data_uri(path, as_model=False)
    if url:
        if url.startswith("data:") or url.startswith("http://") or url.startswith("https://"):
            return url
        # Treat bare local path mistakenly passed as url
        if Path(url).is_file():
            return file_to_data_uri(url, as_model=False)
        return url
    raise MeshyError("需要提供 image_url 或 image_path")


def resolve_model_input(*, model_url: str = "", model_path: str = "") -> str:
    url = (model_url or "").strip()
    path = (model_path or "").strip()
    if path:
        return file_to_data_uri(path, as_model=True)
    if url:
        if url.startswith("data:") or url.startswith("http://") or url.startswith("https://"):
            return url
        if Path(url).is_file():
            return file_to_data_uri(url, as_model=True)
        return url
    raise MeshyError("需要提供 model_url 或 model_path")


def inspect_glb(path: str) -> Dict[str, Any]:
    """
    Lightweight GLB (glTF 2 binary) inspection for materials / embedded images.

    Used to catch Meshy convert/rig inputs that lost textures (white-mesh outcome).
    """
    import json
    import struct

    p = Path(path)
    if not p.is_file():
        raise MeshyError(f"文件不存在: {path}")
    data = p.read_bytes()
    if len(data) < 20 or data[:4] != b"glTF":
        raise MeshyError(f"不是有效的 GLB: {path}")
    _magic, version, length = struct.unpack_from("<4sII", data, 0)
    if version != 2:
        raise MeshyError(f"仅支持 glTF 2.0 GLB（version={version}）")
    offset = 12
    js: Optional[Dict[str, Any]] = None
    while offset + 8 <= len(data) and offset + 8 <= length:
        clen, ctype = struct.unpack_from("<I4s", data, offset)
        chunk = data[offset + 8 : offset + 8 + clen]
        offset += 8 + clen
        if ctype == b"JSON":
            try:
                js = json.loads(chunk.decode("utf-8"))
            except Exception as e:
                raise MeshyError(f"GLB JSON 解析失败: {e}") from e
            break
    if not isinstance(js, dict):
        raise MeshyError("GLB 中未找到 JSON chunk")

    materials = js.get("materials") or []
    images = js.get("images") or []
    textures = js.get("textures") or []
    textured = 0
    for mat in materials:
        if not isinstance(mat, dict):
            continue
        pbr = mat.get("pbrMetallicRoughness") or {}
        if isinstance(pbr, dict) and pbr.get("baseColorTexture"):
            textured += 1
            continue
        if mat.get("normalTexture") or mat.get("occlusionTexture") or mat.get("emissiveTexture"):
            textured += 1
    return {
        "path": str(p),
        "material_count": len(materials),
        "image_count": len(images),
        "texture_count": len(textures),
        "textured_material_count": textured,
        "material_names": [
            str(m.get("name") or "") for m in materials if isinstance(m, dict)
        ][:20],
        "has_images": len(images) > 0,
    }


def fbx_has_external_texture_refs(path: str) -> Dict[str, Any]:
    """
    Heuristic for whether an FBX will lose textures when uploaded as a lone data-URI.

    Note: ``FBXExportEmbeddedTextures`` still leaves original absolute path strings
    in the file. Presence of PNG/JPEG magic bytes indicates real embedded media —
    those must NOT be treated as external-only (false positive seen on 33MB embeds).
    """
    import re

    p = Path(path)
    if not p.is_file():
        raise MeshyError(f"文件不存在: {path}")
    raw = p.read_bytes()
    has_embedded_blobs = (b"\x89PNG\r\n\x1a\n" in raw) or (b"\xff\xd8\xff" in raw)
    # Collect printable strings that look like image paths
    strings = re.findall(rb"[\x20-\x7e]{8,}", raw)
    refs: List[str] = []
    for b in strings:
        s = b.decode("ascii", errors="ignore")
        low = s.lower().replace("\\", "/")
        if any(ext in low for ext in (".png", ".jpg", ".jpeg", ".tga", ".tif", ".tiff", ".bmp")):
            # Prefer path-like hits
            if "/" in low or ":/" in low or ":\\" in s or low.endswith(
                (".png", ".jpg", ".jpeg", ".tga", ".tif", ".tiff", ".bmp")
            ):
                refs.append(s.strip())
    # Dedup preserve order
    seen = set()
    uniq: List[str] = []
    for r in refs:
        key = r.lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    abs_refs = [
        r
        for r in uniq
        if re.match(r"^[A-Za-z]:[\\/]", r) or r.startswith("/") or "://" in r
    ]
    # External-only when path refs exist AND no embedded image blobs.
    likely_external_only = bool(abs_refs) and not has_embedded_blobs
    return {
        "path": str(p),
        "texture_ref_count": len(uniq),
        "absolute_texture_refs": abs_refs[:12],
        "has_embedded_image_blobs": has_embedded_blobs,
        "likely_external_only": likely_external_only,
    }


def ensure_model_has_textures_for_meshy(path: str) -> Optional[str]:
    """
    Return an error message if local model is unsafe for Meshy convert/rig
    (textures will be lost → white mesh). None means OK / not applicable.
    """
    p = Path(path)
    if not p.is_file():
        return f"文件不存在: {path}"
    suffix = p.suffix.lower()
    # Misnamed downloads: Meshy sometimes returns FBX bytes saved as .glb
    head = p.read_bytes()[:24]
    if suffix == ".glb" and head.startswith(b"Kaydara FBX"):
        return (
            f"{p.name} 扩展名是 .glb，但文件头是 FBX（Kaydara）。"
            "请用 meshy_download_model(prefer_format='glb') 重新下载，或改扩展名为 .fbx。"
        )
    if suffix == ".glb":
        try:
            info = inspect_glb(str(p))
        except MeshyError as e:
            return str(e)
        if not info.get("has_images"):
            return (
                "GLB 内没有嵌入贴图（images=0）。继续绑骨/转换会导致白模。"
                "请用 export_fbx(embed_textures=true) 重新导出带嵌入贴图的 FBX，"
                "再 meshy_convert 成 GLB 后重试。"
            )
        return None
    if suffix == ".fbx":
        try:
            info = fbx_has_external_texture_refs(str(p))
        except MeshyError as e:
            return str(e)
        if info.get("likely_external_only"):
            samples = ", ".join(info.get("absolute_texture_refs") or [])[:240]
            return (
                "FBX 引用了外部贴图路径且未检测到嵌入的贴图二进制，上传 Meshy 时贴图不会带走，"
                "convert/rig 结果会是白模。"
                "请先 export_fbx(..., embed_textures=true) 导出嵌入贴图的 FBX，再调用本工具。"
                + (f" 检测到路径示例: {samples}" if samples else "")
            )
        return None
    return None


def multi_material_rig_warning(path: str) -> Optional[str]:
    """
    Meshy rig often collapses multi-material GLBs to a single material/texture
    (keeps first/body map, drops head/hair maps) without rebaking a unified atlas.
    """
    p = Path(path)
    if not p.is_file() or p.suffix.lower() != ".glb":
        return None
    try:
        info = inspect_glb(str(p))
    except MeshyError:
        return None
    n_mat = int(info.get("material_count") or 0)
    n_img = int(info.get("image_count") or 0)
    if n_mat <= 1 and n_img <= 1:
        return None
    names = ", ".join(info.get("material_names") or [])
    return (
        f"⚠ 输入 GLB 有 {n_mat} 个材质 / {n_img} 张贴图"
        + (f"（{names}）" if names else "")
        + "。Meshy 绑骨常会折叠成单一材质并只保留其中一张贴图（多为第一张/身体），"
        "头/发/面饰 UV 仍按原布局采样错误贴图 → 局部花屏。"
        "更稳妥：绑骨后把权重拷回未合并的原始多材质网格；"
        "或先烘焙成单 atlas 再送 Meshy。"
    )

def _format_http_error(status: int, body: Any) -> str:
    msg = ""
    if isinstance(body, dict):
        msg = (
            body.get("message")
            or (body.get("task_error") or {}).get("message")
            or body.get("error")
            or ""
        )
        if isinstance(msg, dict):
            msg = msg.get("message") or str(msg)
    elif isinstance(body, str):
        msg = body
    msg = (msg or "").strip()
    if status == 401:
        return "Meshy 鉴权失败（401）：请检查设置中的 Meshy API Key 或环境变量 MESHY_API_KEY。"
    if status == 402:
        return f"Meshy 积分不足（402）{('：' + msg) if msg else '。请充值后再试。'}"
    if status == 429:
        return f"Meshy 请求过于频繁（429）{('：' + msg) if msg else '。请稍后重试。'}"
    if status == 409:
        return f"Meshy 冲突（409）{('：' + msg) if msg else ''}。"
    if msg:
        return f"Meshy API 错误（{status}）：{msg}"
    return f"Meshy API 错误（{status}）"


class MeshyClient:
    def __init__(self, api_key: Optional[str] = None) -> None:
        conf = meshy_cfg()
        if not conf["enabled"]:
            raise MeshyError("Meshy 已在配置中关闭（meshy.enabled=false）。")
        self.api_key = (api_key or get_meshy_api_key()).strip()
        if not self.api_key:
            raise MeshyError(
                "未配置 Meshy API Key。请在「模型 → Meshy」填写，"
                f"或设置环境变量 {conf['api_key_env']}。"
            )
        self.base_url = conf["base_url"]
        self.timeout = conf["timeout"]
        self.poll_interval = conf["poll_interval"]
        self.wait_timeout = conf["wait_timeout"]
        self.default_formats = list(conf["default_formats"] or ["fbx", "glb"])

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "MayaAgent/1.4 MeshyClient",
        }

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.base_url}{path}"

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Any, httpx.Headers]:
        url = self._url(path)
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                resp = client.request(
                    method.upper(),
                    url,
                    headers=self._headers(),
                    json=json_body,
                    params=params,
                )
        except httpx.TimeoutException as e:
            raise MeshyError(f"Meshy 请求超时：{e}") from e
        except httpx.HTTPError as e:
            raise MeshyError(f"Meshy 网络错误：{e}") from e

        body: Any
        try:
            body = resp.json() if resp.content else None
        except Exception:
            body = (resp.text or "")[:500]

        if resp.status_code >= 400:
            if resp.status_code == 401:
                mark_meshy_key_invalid(self.api_key)
            raise MeshyError(
                _format_http_error(resp.status_code, body),
                status_code=resp.status_code,
                payload=body,
            )
        mark_meshy_key_valid(self.api_key)
        return body, resp.headers

    def create(self, kind: str, body: Dict[str, Any]) -> str:
        path = KIND_PATHS.get(kind)
        if not path:
            raise MeshyError(f"未知任务类型: {kind}。可选: {', '.join(sorted(KIND_PATHS))}")
        data, _ = self.request("POST", path, json_body=body or {})
        task_id = ""
        if isinstance(data, dict):
            task_id = str(data.get("result") or data.get("id") or "")
        if not task_id:
            raise MeshyError(f"创建任务未返回 id：{data}")
        return task_id

    def get(self, kind: str, task_id: str) -> Tuple[Dict[str, Any], Optional[float]]:
        path = KIND_PATHS.get(kind)
        if not path:
            raise MeshyError(f"未知任务类型: {kind}")
        tid = (task_id or "").strip()
        if not tid:
            raise MeshyError("task_id 为空")
        data, headers = self.request("GET", f"{path}/{tid}")
        if not isinstance(data, dict):
            raise MeshyError(f"任务响应异常：{data}")
        retry_after = None
        raw = headers.get("retry-after") or headers.get("Retry-After")
        if raw:
            try:
                retry_after = float(raw)
            except ValueError:
                retry_after = None
        return data, retry_after

    def wait(
        self,
        kind: str,
        task_id: str,
        *,
        timeout: Optional[float] = None,
        poll_interval: Optional[float] = None,
        on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        limit = float(timeout if timeout is not None else self.wait_timeout)
        interval = float(poll_interval if poll_interval is not None else self.poll_interval)
        deadline = time.monotonic() + max(5.0, limit)
        last: Dict[str, Any] = {}
        last_status = ""
        last_progress: Any = object()

        def _emit() -> None:
            if on_progress is None:
                return
            status = str(last.get("status") or "")
            progress = last.get("progress")
            nonlocal last_status, last_progress
            if status == last_status and progress == last_progress:
                return
            last_status = status
            last_progress = progress
            try:
                on_progress(
                    {
                        "kind": kind,
                        "task_id": task_id,
                        "status": status,
                        "progress": progress,
                    }
                )
            except Exception:
                pass

        while True:
            last, retry_after = self.get(kind, task_id)
            status = str(last.get("status") or "")
            _emit()
            if status in TERMINAL_STATUSES:
                if status != "SUCCEEDED":
                    err = ""
                    te = last.get("task_error") or {}
                    if isinstance(te, dict):
                        err = te.get("message") or ""
                    raise MeshyError(
                        f"Meshy 任务 {status}" + (f"：{err}" if err else ""),
                        payload=last,
                    )
                return last
            if time.monotonic() >= deadline:
                raise MeshyError(
                    f"等待 Meshy 任务超时（{limit:.0f}s），当前 status={status or '未知'} "
                    f"progress={last.get('progress')}",
                    payload=last,
                )
            sleep_s = retry_after if retry_after and retry_after > 0 else interval
            time.sleep(max(1.0, sleep_s))

    def balance(self) -> Dict[str, Any]:
        data, _ = self.request("GET", "/v1/balance")
        if not isinstance(data, dict):
            raise MeshyError(f"余额响应异常：{data}")
        return data

    def list_animations(self) -> Any:
        data, _ = self.request("GET", "/v1/animations/library")
        return data

    def download(self, url: str, dest: Path) -> Path:
        u = (url or "").strip()
        if not u:
            raise MeshyError("下载 URL 为空")
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with httpx.Client(timeout=max(self.timeout, 120.0), follow_redirects=True) as client:
                with client.stream("GET", u, headers={"User-Agent": "MayaAgent/1.4 MeshyClient"}) as resp:
                    if resp.status_code >= 400:
                        raise MeshyError(f"下载失败（{resp.status_code}）")
                    with open(dest, "wb") as f:
                        for chunk in resp.iter_bytes():
                            if chunk:
                                f.write(chunk)
        except MeshyError:
            raise
        except httpx.HTTPError as e:
            raise MeshyError(f"下载网络错误：{e}") from e
        return dest


def summarize_task(task: Dict[str, Any]) -> Dict[str, Any]:
    """Compact task payload for tool results (drop huge nested noise)."""
    out: Dict[str, Any] = {
        "id": task.get("id"),
        "type": task.get("type"),
        "status": task.get("status"),
        "progress": task.get("progress"),
        "consumed_credits": task.get("consumed_credits"),
        "preceding_tasks": task.get("preceding_tasks"),
    }
    if task.get("model_urls"):
        out["model_urls"] = task["model_urls"]
    if task.get("thumbnail_url"):
        out["thumbnail_url"] = task["thumbnail_url"]
    if task.get("alpha_thumbnail_url"):
        out["alpha_thumbnail_url"] = task["alpha_thumbnail_url"]
    if task.get("result") is not None:
        out["result"] = task["result"]
    te = task.get("task_error")
    if isinstance(te, dict) and te.get("message"):
        out["task_error"] = te
    return out


def pick_model_url(
    task: Dict[str, Any],
    *,
    prefer: Optional[List[str]] = None,
) -> Tuple[str, str]:
    """
    Return (format, url) from a SUCCEEDED task.
    Prefer formats in ``prefer`` (default fbx then glb).
    """
    prefs = prefer or meshy_cfg().get("default_formats") or ["fbx", "glb"]
    urls = task.get("model_urls") if isinstance(task.get("model_urls"), dict) else {}
    result = task.get("result") if isinstance(task.get("result"), dict) else {}

    # Standard model_urls
    for fmt in prefs:
        u = (urls or {}).get(fmt)
        if u:
            return fmt, str(u)
    if urls:
        for fmt, u in urls.items():
            if u:
                return str(fmt), str(u)

    # Rigging / animation nested result
    for key, fmt in (
        ("rigged_character_fbx_url", "fbx"),
        ("rigged_character_glb_url", "glb"),
        ("animation_fbx_url", "fbx"),
        ("animation_glb_url", "glb"),
    ):
        u = result.get(key)
        if u:
            return fmt, str(u)
    # Any *_fbx_url / *_glb_url
    for key, val in (result or {}).items():
        if not isinstance(val, str) or not val:
            continue
        if key.endswith("_fbx_url") or key == "fbx":
            return "fbx", val
        if key.endswith("_glb_url") or key == "glb":
            return "glb", val
    raise MeshyError("任务结果中没有可下载的模型 URL（model_urls / result）")


def drop_none(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None and v != ""}
