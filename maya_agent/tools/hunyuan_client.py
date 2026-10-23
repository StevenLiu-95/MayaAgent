"""Tencent Hunyuan 3D (ai3d) REST client — TC3-HMAC-SHA256 + async jobs."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

from maya_agent.utils.config import get_config
from maya_agent.utils.logger import get_logger

log = get_logger("maya_agent.hunyuan")

API_VERSION = "2025-05-13"
SERVICE = "ai3d"

# Logical job kind → Query/Describe Action
JOB_QUERY_ACTIONS: Dict[str, str] = {
    "pro": "QueryHunyuanTo3DProJob",
    "rapid": "QueryHunyuanTo3DRapidJob",
    "texture": "DescribeTextureTo3DJob",
    "reduce_face": "DescribeReduceFaceJob",
    "part": "QueryHunyuan3DPartJob",
    "uv": "DescribeHunyuanTo3DUVJob",
    "motion": "DescribeHunyuanTo3DMotionJob",
    "auto_rig": "DescribeAutoRiggingJob",
    "profile": "DescribeProfileTo3DJob",
}

JOB_KINDS = frozenset(JOB_QUERY_ACTIONS.keys())

TERMINAL_STATUSES = frozenset({"DONE", "FAIL"})
SUCCESS_STATUS = "DONE"

# Auto-rig MotionType presets (1-based index from docs)
MOTION_PRESETS: List[Dict[str, Any]] = [
    {"id": 1, "name": "回旋踢"},
    {"id": 2, "name": "左勾拳"},
    {"id": 3, "name": "蓄力攻击"},
    {"id": 4, "name": "蓄力出拳"},
    {"id": 5, "name": "二连击打"},
    {"id": 6, "name": "二连击打-2"},
    {"id": 7, "name": "后撤"},
    {"id": 8, "name": "受击"},
    {"id": 9, "name": "受击-2"},
    {"id": 10, "name": "受击-3"},
    {"id": 11, "name": "受击倒地-1"},
    {"id": 12, "name": "受击倒地-2"},
    {"id": 13, "name": "落地"},
    {"id": 14, "name": "沮丧"},
    {"id": 15, "name": "割喉"},
    {"id": 16, "name": "刺拳"},
    {"id": 17, "name": "连续击打"},
    {"id": 18, "name": "踢腿"},
    {"id": 19, "name": "侧踢"},
    {"id": 20, "name": "打太极"},
    {"id": 21, "name": "后空翻"},
    {"id": 22, "name": "蹲姿转体"},
    {"id": 23, "name": "走路-1"},
    {"id": 24, "name": "走路-2"},
    {"id": 25, "name": "走路-3"},
    {"id": 26, "name": "待机-1"},
    {"id": 27, "name": "待机-2"},
    {"id": 28, "name": "街舞"},
    {"id": 29, "name": "扭扭舞"},
    {"id": 30, "name": "左转弯"},
    {"id": 31, "name": "右转弯"},
    {"id": 32, "name": "慢跑"},
    {"id": 33, "name": "慢跑-2"},
    {"id": 34, "name": "奔跑"},
    {"id": 35, "name": "冲刺跑-1"},
    {"id": 36, "name": "冲刺跑-2"},
    {"id": 37, "name": "冲刺跑-3"},
    {"id": 38, "name": "原地跳-1"},
    {"id": 39, "name": "滑铲"},
    {"id": 40, "name": "向前大跳"},
    {"id": 41, "name": "向前大跳-2"},
    {"id": 42, "name": "跨越"},
    {"id": 43, "name": "恐吓"},
    {"id": 44, "name": "向前跌倒"},
    {"id": 45, "name": "右转"},
    {"id": 46, "name": "原地跳-2"},
    {"id": 47, "name": "转身"},
    {"id": 48, "name": "发送冲击波"},
]

PROFILE_TEMPLATES = [
    "basketball",
    "badminton",
    "pingpong",
    "gymnastics",
    "pilidance",
    "tennis",
    "athletics",
    "footballboykicking1",
    "footballboykicking2",
    "guitar",
    "footballboy",
    "skateboard",
    "futuresoilder",
    "explorer",
    "beardollgirl",
    "bibpantsboy",
    "womansitpose",
    "womanstandpose2",
    "mysteriousprincess",
    "manstandpose2",
]

_invalid_key_fp: Optional[str] = None


def _key_fingerprint(secret_id: str) -> str:
    return hashlib.sha256((secret_id or "").encode("utf-8")).hexdigest()[:24]


def mark_hunyuan_key_invalid(secret_id: Optional[str] = None) -> None:
    global _invalid_key_fp
    sid = (secret_id if secret_id is not None else get_hunyuan_secret_id()).strip()
    if sid:
        _invalid_key_fp = _key_fingerprint(sid)
        log.info("Hunyuan credentials marked invalid (tools will be hidden from LLM)")


def mark_hunyuan_key_valid(secret_id: Optional[str] = None) -> None:
    global _invalid_key_fp
    sid = (secret_id if secret_id is not None else get_hunyuan_secret_id()).strip()
    if not sid:
        _invalid_key_fp = None
        return
    if _invalid_key_fp and _invalid_key_fp == _key_fingerprint(sid):
        _invalid_key_fp = None
        log.info("Hunyuan credentials marked valid")
    else:
        _invalid_key_fp = None


def clear_hunyuan_key_validity() -> None:
    global _invalid_key_fp
    _invalid_key_fp = None


def hunyuan_tools_available() -> bool:
    conf = hunyuan_cfg()
    if not conf["enabled"]:
        return False
    sid = get_hunyuan_secret_id()
    skey = get_hunyuan_secret_key()
    if not sid or not skey:
        return False
    if _invalid_key_fp and _key_fingerprint(sid) == _invalid_key_fp:
        return False
    return True


def filter_system_prompt_hunyuan(text: str) -> str:
    """Strip Hunyuan guidance when tools are unavailable."""
    if hunyuan_tools_available():
        return text
    lines = text.splitlines(keepends=True)
    out: List[str] = []
    skipping = False
    for line in lines:
        stripped = line.lstrip()
        is_heading = stripped.startswith("#") and not stripped.startswith("#" * 7)
        heading_text = ""
        if is_heading:
            heading_text = stripped.lstrip("#").strip()
        if not skipping and is_heading and (
            heading_text.startswith("混元") or heading_text.lower().startswith("hunyuan")
        ):
            skipping = True
            continue
        if skipping:
            if is_heading and not (
                heading_text.startswith("混元")
                or heading_text.lower().startswith("hunyuan")
            ):
                skipping = False
                out.append(line)
            continue
        if stripped.startswith("|") and ("混元" in line or "Hunyuan" in line):
            continue
        out.append(line)
    return "".join(out)


class HunyuanError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 0,
        error_code: str = "",
        payload: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code or ""
        self.payload = payload


def hunyuan_cfg() -> Dict[str, Any]:
    cfg = get_config()
    return {
        "enabled": bool(cfg.get("hunyuan.enabled", True)),
        "endpoint": str(
            cfg.get("hunyuan.endpoint") or "ai3d.tencentcloudapi.com"
        ).strip().rstrip("/"),
        "region": str(cfg.get("hunyuan.region") or "ap-guangzhou").strip(),
        "version": str(cfg.get("hunyuan.version") or API_VERSION).strip(),
        "secret_id_env": str(
            cfg.get("hunyuan.secret_id_env") or "TENCENTCLOUD_SECRET_ID"
        ),
        "secret_key_env": str(
            cfg.get("hunyuan.secret_key_env") or "TENCENTCLOUD_SECRET_KEY"
        ),
        "timeout": float(cfg.get("hunyuan.timeout", 60) or 60),
        "poll_interval": float(cfg.get("hunyuan.poll_interval", 5) or 5),
        "wait_timeout": float(cfg.get("hunyuan.wait_timeout", 600) or 600),
        "download_dir": str(cfg.get("hunyuan.download_dir") or ""),
        "default_formats": list(
            cfg.get("hunyuan.default_formats") or ["fbx", "glb", "obj"]
        ),
    }


def get_hunyuan_secret_id() -> str:
    cfg = get_config()
    key = (cfg.get_api_key("hunyuan_secret_id") or "").strip()
    if key:
        return key
    import os

    return (os.environ.get(hunyuan_cfg()["secret_id_env"]) or "").strip()


def get_hunyuan_secret_key() -> str:
    cfg = get_config()
    key = (cfg.get_api_key("hunyuan_secret_key") or "").strip()
    if key:
        return key
    import os

    return (os.environ.get(hunyuan_cfg()["secret_key_env"]) or "").strip()


def download_dir() -> Path:
    from maya_agent.utils.paths import agent_temp_subdir

    conf = hunyuan_cfg()
    raw = (conf.get("download_dir") or "").strip()
    if raw:
        path = Path(raw)
        path.mkdir(parents=True, exist_ok=True)
        return path
    return agent_temp_subdir("hunyuan_downloads")


def drop_none(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None and v != ""}


def normalize_job_progress(value: Any) -> Optional[int]:
    """Map API progress field to 0–100 int; None if missing/invalid."""
    if value is None or value == "":
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    # Open interval (0, 1) → fraction; keep integer 1 as 1%.
    if 0.0 < num < 1.0:
        num = num * 100.0
    return max(0, min(100, int(round(num))))


def estimate_status_progress(
    status: str,
    *,
    elapsed: float = 0.0,
    timeout: float = 600.0,
) -> int:
    """
    Hunyuan Query APIs document Status only (WAIT/RUN/FAIL/DONE), no Progress.

    Synthesize a determinate 0–100 value so the UI bar is not stuck at 0%.
    During RUN, ease toward ~92% based on elapsed time.
    """
    st = (status or "").strip().upper()
    if st == "DONE":
        return 100
    if st in ("FAIL", "FAILED", "CANCELED", "CANCELLED"):
        return 100
    if st == "WAIT":
        return 8
    if st == "RUN":
        expected = max(60.0, min(float(timeout) * 0.6, 480.0))
        frac = min(1.0, max(0.0, float(elapsed)) / expected)
        eased = 1.0 - (1.0 - frac) ** 1.5
        return max(15, min(92, int(round(15 + 77 * eased))))
    return 5


def job_progress_from_task(
    task: Dict[str, Any],
    *,
    elapsed: float = 0.0,
    timeout: float = 600.0,
) -> int:
    """Prefer real Progress fields; otherwise estimate from Status + elapsed."""
    if not isinstance(task, dict):
        return estimate_status_progress("", elapsed=elapsed, timeout=timeout)
    for key in ("Progress", "progress", "Percent", "percent", "ProgressPercent"):
        if key in task and task.get(key) is not None:
            n = normalize_job_progress(task.get(key))
            if n is not None:
                return n
    # Nested output (future-proof)
    output = task.get("Output") or task.get("output")
    if isinstance(output, dict):
        for key in ("Progress", "progress", "Percent", "percent"):
            if key in output and output.get(key) is not None:
                n = normalize_job_progress(output.get(key))
                if n is not None:
                    return n
    return estimate_status_progress(
        str(task.get("Status") or task.get("status") or ""),
        elapsed=elapsed,
        timeout=timeout,
    )


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def tc3_authorization(
    *,
    secret_id: str,
    secret_key: str,
    host: str,
    service: str,
    action: str,
    payload: str,
    timestamp: int,
    content_type: str = "application/json; charset=utf-8",
) -> str:
    """
    Build TC3-HMAC-SHA256 Authorization header value.

    ``payload`` must be the exact JSON body string that will be sent.
    """
    date = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")
    canonical_uri = "/"
    canonical_querystring = ""
    ct = content_type.lower()
    action_l = action.lower()
    host_l = host.lower()
    canonical_headers = (
        f"content-type:{ct}\n"
        f"host:{host_l}\n"
        f"x-tc-action:{action_l}\n"
    )
    signed_headers = "content-type;host;x-tc-action"
    hashed_payload = _sha256_hex(payload.encode("utf-8"))
    canonical_request = (
        "POST\n"
        f"{canonical_uri}\n"
        f"{canonical_querystring}\n"
        f"{canonical_headers}\n"
        f"{signed_headers}\n"
        f"{hashed_payload}"
    )
    credential_scope = f"{date}/{service}/tc3_request"
    string_to_sign = (
        "TC3-HMAC-SHA256\n"
        f"{timestamp}\n"
        f"{credential_scope}\n"
        f"{_sha256_hex(canonical_request.encode('utf-8'))}"
    )
    secret_date = _hmac_sha256(("TC3" + secret_key).encode("utf-8"), date)
    secret_service = _hmac_sha256(secret_date, service)
    secret_signing = _hmac_sha256(secret_service, "tc3_request")
    signature = hmac.new(
        secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return (
        "TC3-HMAC-SHA256 "
        f"Credential={secret_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, "
        f"Signature={signature}"
    )


def summarize_task(task: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(task, dict):
        return {"raw": task}
    out: Dict[str, Any] = {
        "status": task.get("Status") or task.get("status"),
        "error_code": task.get("ErrorCode") or "",
        "error_message": task.get("ErrorMessage") or "",
        "request_id": task.get("RequestId"),
        "result_credit_consumed": task.get("ResultCreditConsumed"),
        "result_credit_details": task.get("ResultCreditDetails"),
    }
    files = task.get("ResultFile3Ds") or task.get("result_file_3ds")
    if isinstance(files, list):
        slim = []
        for f in files:
            if not isinstance(f, dict):
                continue
            slim.append(
                {
                    "Type": f.get("Type") or f.get("type"),
                    "Url": f.get("Url") or f.get("url"),
                    "PreviewImageUrl": f.get("PreviewImageUrl")
                    or f.get("preview_image_url"),
                }
            )
        out["ResultFile3Ds"] = slim
    if task.get("ResultFile3D"):
        out["ResultFile3D"] = task.get("ResultFile3D")
    if task.get("JobId"):
        out["JobId"] = task.get("JobId")
    return out


def pick_result_url(
    task: Dict[str, Any],
    *,
    prefer: Optional[List[str]] = None,
) -> Tuple[str, str]:
    """
    Return (type_lower, url) from a DONE job payload.
    Prefer types in ``prefer`` (e.g. fbx, glb, obj).
    """
    prefs = [p.lower() for p in (prefer or hunyuan_cfg().get("default_formats") or [])]
    files = task.get("ResultFile3Ds") if isinstance(task, dict) else None
    if not isinstance(files, list):
        files = []
    entries: List[Tuple[str, str]] = []
    for f in files:
        if not isinstance(f, dict):
            continue
        url = str(f.get("Url") or f.get("url") or "").strip()
        typ = str(f.get("Type") or f.get("type") or "").strip()
        if not url:
            continue
        if not typ:
            # Guess from URL path
            path = url.split("?", 1)[0].lower()
            for ext in ("fbx", "glb", "obj", "stl", "usdz", "zip", "mp4", "gif"):
                if path.endswith("." + ext):
                    typ = ext
                    break
        entries.append((typ.lower(), url))

    # Sync convert returns a single URL
    single = ""
    if isinstance(task, dict):
        single = str(task.get("ResultFile3D") or "").strip()
    if single and not entries:
        path = single.split("?", 1)[0].lower()
        typ = ""
        for ext in ("fbx", "glb", "obj", "stl", "usdz", "zip", "mp4", "gif"):
            if path.endswith("." + ext):
                typ = ext
                break
        return typ or "bin", single

    for pref in prefs:
        for typ, url in entries:
            if typ == pref or typ.endswith(pref):
                return typ, url
    if entries:
        return entries[0]
    raise HunyuanError("任务结果中没有可用的 ResultFile3Ds / ResultFile3D URL")


def resolve_image_fields(
    *,
    image_url: str = "",
    image_path: str = "",
) -> Dict[str, str]:
    """
    Build Pro/Rapid image fields: ImageUrl or ImageBase64 (raw base64, no data: prefix).
    """
    path = (image_path or "").strip()
    url = (image_url or "").strip()
    if path:
        p = Path(path)
        if not p.is_file():
            raise HunyuanError(f"图片不存在: {path}")
        data = p.read_bytes()
        if len(data) > 6 * 1024 * 1024:
            raise HunyuanError(
                f"本地图片过大（{len(data) / (1024 * 1024):.1f}MB），混元 ImageBase64 建议 ≤6MB"
            )
        return {"ImageBase64": base64.b64encode(data).decode("ascii")}
    if url:
        if url.startswith(("http://", "https://")):
            return {"ImageUrl": url}
        # Treat as local path mistaken for url
        if Path(url).is_file():
            return resolve_image_fields(image_path=url)
        return {"ImageUrl": url}
    raise HunyuanError("需要 image_url 或 image_path")


def resolve_profile_image(
    *,
    image_url: str = "",
    image_path: str = "",
) -> Dict[str, str]:
    """Profile Image object: Url and/or Base64."""
    path = (image_path or "").strip()
    url = (image_url or "").strip()
    if url and url.startswith(("http://", "https://")):
        return {"Url": url}
    if path or (url and Path(url).is_file()):
        p = Path(path or url)
        if not p.is_file():
            raise HunyuanError(f"图片不存在: {p}")
        data = p.read_bytes()
        return {"Base64": base64.b64encode(data).decode("ascii")}
    if url:
        return {"Url": url}
    raise HunyuanError("需要 image_url 或 image_path")


def guess_file_type_from_url(url: str, fallback: str = "GLB") -> str:
    path = (url or "").split("?", 1)[0].lower()
    for ext, typ in (
        (".fbx", "FBX"),
        (".glb", "GLB"),
        (".obj", "OBJ"),
        (".stl", "STL"),
        (".usdz", "USDZ"),
        (".zip", "OBJ"),
    ):
        if path.endswith(ext):
            return typ
    return (fallback or "GLB").upper()


class HunyuanClient:
    def __init__(
        self,
        secret_id: Optional[str] = None,
        secret_key: Optional[str] = None,
    ) -> None:
        conf = hunyuan_cfg()
        if not conf["enabled"]:
            raise HunyuanError("混元生3D 已在配置中关闭（hunyuan.enabled=false）。")
        self.secret_id = (secret_id or get_hunyuan_secret_id()).strip()
        self.secret_key = (secret_key or get_hunyuan_secret_key()).strip()
        if not self.secret_id or not self.secret_key:
            raise HunyuanError(
                "未配置混元 SecretId/SecretKey。"
                "请在「模型 → 混元」填写，或设置环境变量 "
                f"{conf['secret_id_env']} / {conf['secret_key_env']}。"
            )
        self.host = conf["endpoint"].replace("https://", "").replace("http://", "")
        self.region = conf["region"]
        self.version = conf["version"]
        self.timeout = conf["timeout"]
        self.poll_interval = conf["poll_interval"]
        self.wait_timeout = conf["wait_timeout"]
        self.default_formats = list(conf["default_formats"] or ["fbx", "glb", "obj"])

    def call(self, action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        action = (action or "").strip()
        if not action:
            raise HunyuanError("Action 为空")
        body_obj = drop_none(params or {})
        # Compact JSON for stable hashing (no spaces)
        payload = json.dumps(body_obj, ensure_ascii=False, separators=(",", ":"))
        timestamp = int(time.time())
        content_type = "application/json; charset=utf-8"
        authorization = tc3_authorization(
            secret_id=self.secret_id,
            secret_key=self.secret_key,
            host=self.host,
            service=SERVICE,
            action=action,
            payload=payload,
            timestamp=timestamp,
            content_type=content_type,
        )
        headers = {
            "Authorization": authorization,
            "Content-Type": content_type,
            "Host": self.host,
            "X-TC-Action": action,
            "X-TC-Timestamp": str(timestamp),
            "X-TC-Version": self.version,
            "X-TC-Region": self.region,
            "User-Agent": "MayaAgent/1.5 HunyuanClient",
        }
        url = f"https://{self.host}/"
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                resp = client.post(url, headers=headers, content=payload.encode("utf-8"))
        except httpx.TimeoutException as e:
            raise HunyuanError(f"混元请求超时：{e}") from e
        except httpx.HTTPError as e:
            raise HunyuanError(f"混元网络错误：{e}") from e

        try:
            body = resp.json() if resp.content else {}
        except Exception:
            body = {"raw": (resp.text or "")[:500]}

        if resp.status_code >= 400:
            err = self._extract_error(body)
            if err.get("code", "").startswith("AuthFailure"):
                mark_hunyuan_key_invalid(self.secret_id)
            raise HunyuanError(
                self._format_error(resp.status_code, err, body),
                status_code=resp.status_code,
                error_code=err.get("code", ""),
                payload=body,
            )

        if not isinstance(body, dict):
            raise HunyuanError(f"混元响应异常：{body}", payload=body)

        response = body.get("Response")
        if not isinstance(response, dict):
            raise HunyuanError(f"混元响应缺少 Response：{body}", payload=body)

        err_obj = response.get("Error")
        if isinstance(err_obj, dict) and err_obj.get("Code"):
            code = str(err_obj.get("Code") or "")
            msg = str(err_obj.get("Message") or "")
            if code.startswith("AuthFailure"):
                mark_hunyuan_key_invalid(self.secret_id)
            raise HunyuanError(
                f"混元 API 错误（{code}）：{msg}" if msg else f"混元 API 错误（{code}）",
                status_code=resp.status_code,
                error_code=code,
                payload=response,
            )

        mark_hunyuan_key_valid(self.secret_id)
        return response

    @staticmethod
    def _extract_error(body: Any) -> Dict[str, str]:
        if not isinstance(body, dict):
            return {"code": "", "message": str(body)[:200]}
        resp = body.get("Response")
        if isinstance(resp, dict) and isinstance(resp.get("Error"), dict):
            e = resp["Error"]
            return {
                "code": str(e.get("Code") or ""),
                "message": str(e.get("Message") or ""),
            }
        return {
            "code": str(body.get("Code") or ""),
            "message": str(body.get("Message") or body.get("message") or ""),
        }

    @staticmethod
    def _format_error(status: int, err: Dict[str, str], body: Any) -> str:
        code = err.get("code") or ""
        msg = err.get("message") or ""
        if code.startswith("AuthFailure") or status == 401:
            return (
                "混元鉴权失败：请检查设置中的 SecretId / SecretKey "
                "或环境变量 TENCENTCLOUD_SECRET_ID / TENCENTCLOUD_SECRET_KEY。"
                + (f"（{code}: {msg}）" if code or msg else "")
            )
        if code or msg:
            return f"混元 API 错误（HTTP {status}{', ' + code if code else ''}）：{msg or body}"
        return f"混元 API 错误（HTTP {status}）"

    def submit(self, action: str, body: Dict[str, Any]) -> str:
        data = self.call(action, body)
        job_id = str(data.get("JobId") or "").strip()
        if not job_id:
            raise HunyuanError(f"创建任务未返回 JobId：{data}", payload=data)
        return job_id

    def get_job(self, kind: str, job_id: str) -> Dict[str, Any]:
        k = (kind or "").strip().lower()
        action = JOB_QUERY_ACTIONS.get(k)
        if not action:
            raise HunyuanError(
                f"未知任务类型 kind={kind!r}。可选: {', '.join(sorted(JOB_KINDS))}"
            )
        tid = (job_id or "").strip()
        if not tid:
            raise HunyuanError("job_id 为空")
        return self.call(action, {"JobId": tid})

    def wait(
        self,
        kind: str,
        job_id: str,
        *,
        timeout: Optional[float] = None,
        poll_interval: Optional[float] = None,
        on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        limit = float(timeout if timeout is not None else self.wait_timeout)
        interval = float(
            poll_interval if poll_interval is not None else self.poll_interval
        )
        started = time.monotonic()
        deadline = started + max(5.0, limit)
        last: Dict[str, Any] = {}
        last_status = ""
        last_progress: Optional[int] = None

        def _emit(*, force: bool = False) -> None:
            if on_progress is None:
                return
            status = str(last.get("Status") or "")
            elapsed = time.monotonic() - started
            progress = job_progress_from_task(
                last, elapsed=elapsed, timeout=limit
            )
            nonlocal last_status, last_progress
            if (
                not force
                and status == last_status
                and progress == last_progress
            ):
                return
            last_status = status
            last_progress = progress
            try:
                on_progress(
                    {
                        "kind": kind,
                        "job_id": job_id,
                        "status": status,
                        "progress": progress,
                    }
                )
            except Exception:
                pass

        while True:
            last = self.get_job(kind, job_id)
            status = str(last.get("Status") or "").upper()
            _emit()
            if status in TERMINAL_STATUSES or status == SUCCESS_STATUS:
                if status != SUCCESS_STATUS:
                    err = str(last.get("ErrorMessage") or last.get("ErrorCode") or "")
                    raise HunyuanError(
                        f"混元任务 {status}" + (f"：{err}" if err else ""),
                        error_code=str(last.get("ErrorCode") or ""),
                        payload=last,
                    )
                # Ensure UI reaches 100% on success
                last = dict(last)
                last["Status"] = SUCCESS_STATUS
                _emit(force=True)
                return last
            if time.monotonic() >= deadline:
                raise HunyuanError(
                    f"等待混元任务超时（{limit:.0f}s），当前 status={status or '未知'}",
                    payload=last,
                )
            time.sleep(max(1.0, interval))

    def convert(self, file_url: str, fmt: str) -> Dict[str, Any]:
        return self.call(
            "Convert3DFormat",
            {"File3D": (file_url or "").strip(), "Format": (fmt or "").strip().upper()},
        )

    def resolve_file3d(
        self,
        *,
        file_url: str = "",
        file_type: str = "",
        input_job_id: str = "",
        input_job_kind: str = "",
        prefer_types: Optional[List[str]] = None,
        as_input_file: bool = False,
    ) -> Dict[str, str]:
        """
        Build File3D / InputFile3D dict from public URL or a previous job's ResultFile3Ds.

        Local paths are rejected (B1 — no COS upload).
        """
        url = (file_url or "").strip()
        typ = (file_type or "").strip().upper()
        jid = (input_job_id or "").strip()
        jkind = (input_job_kind or "").strip().lower()

        if url and not url.startswith(("http://", "https://")):
            raise HunyuanError(
                "file_url 必须是公网 http(s) URL。"
                "混元不支持本地 FBX/GLB 直传；请自备公网地址，"
                "或传入 input_job_id + input_job_kind 串联上一任务结果。"
            )

        if not url and jid:
            if not jkind:
                raise HunyuanError(
                    "使用 input_job_id 时必须同时提供 input_job_kind"
                    f"（{', '.join(sorted(JOB_KINDS))}）"
                )
            task = self.get_job(jkind, jid)
            status = str(task.get("Status") or "").upper()
            if status and status != SUCCESS_STATUS:
                raise HunyuanError(
                    f"上游任务尚未成功（status={status}），无法取 ResultFile3Ds"
                )
            typ_picked, url = pick_result_url(
                task, prefer=prefer_types or self.default_formats
            )
            if not typ:
                typ = typ_picked.upper() if typ_picked else guess_file_type_from_url(url)

        if not url:
            raise HunyuanError(
                "需要 file_url，或 input_job_id + input_job_kind。"
                "本地网格请先放到公网可访问的 URL。"
            )

        if not typ:
            typ = guess_file_type_from_url(url)

        if as_input_file:
            return {"Url": url, "Type": typ}
        return {"Url": url, "Type": typ}

    def test_connection(self) -> Dict[str, Any]:
        """
        Validate credentials with a signed Query call using a dummy JobId.
        AuthFailure → invalid; other business errors → credentials OK.
        """
        try:
            self.call("QueryHunyuanTo3DProJob", {"JobId": "0"})
            return {"ok": True, "message": "连接成功"}
        except HunyuanError as e:
            code = (e.error_code or "").strip()
            if code.startswith("AuthFailure") or "鉴权失败" in str(e):
                raise
            # Parameter / resource errors mean the signature was accepted
            mark_hunyuan_key_valid(self.secret_id)
            return {
                "ok": True,
                "message": "连接成功（密钥有效）",
                "probe_error": code or str(e)[:120],
            }

    def download(self, url: str, dest: Path) -> Path:
        u = (url or "").strip()
        if not u:
            raise HunyuanError("下载 URL 为空")
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with httpx.Client(
                timeout=max(self.timeout, 120.0), follow_redirects=True
            ) as client:
                with client.stream(
                    "GET",
                    u,
                    headers={"User-Agent": "MayaAgent/1.5 HunyuanClient"},
                ) as resp:
                    if resp.status_code >= 400:
                        raise HunyuanError(f"下载失败（{resp.status_code}）")
                    with open(dest, "wb") as f:
                        for chunk in resp.iter_bytes():
                            if chunk:
                                f.write(chunk)
        except HunyuanError:
            raise
        except httpx.HTTPError as e:
            raise HunyuanError(f"下载网络错误：{e}") from e
        return dest
