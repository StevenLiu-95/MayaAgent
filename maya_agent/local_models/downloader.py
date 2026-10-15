"""Manual weight downloader — never called automatically by the Agent."""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from maya_agent.local_models.availability import backend_dir, backend_ready
from maya_agent.local_models.catalog import get_backend
from maya_agent.utils.logger import get_logger

log = get_logger("maya_agent.local_models.download")

ProgressCb = Callable[[Dict[str, Any]], None]

_LOCK = threading.Lock()
_JOBS: Dict[str, Dict[str, Any]] = {}


def _set_job(backend_id: str, **fields: Any) -> None:
    with _LOCK:
        row = _JOBS.setdefault(backend_id, {"id": backend_id, "status": "idle"})
        row.update(fields)


def get_download_job(backend_id: str) -> Dict[str, Any]:
    with _LOCK:
        return dict(_JOBS.get(backend_id) or {"id": backend_id, "status": "idle"})


def _sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _download_url(
    url: str,
    dest: Path,
    *,
    expected_sha: str = "",
    on_progress: Optional[ProgressCb] = None,
    backend_id: str = "",
) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "MayaAgent-LocalModels/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            with open(tmp, "wb") as out:
                while True:
                    block = resp.read(1024 * 256)
                    if not block:
                        break
                    out.write(block)
                    done += len(block)
                    pct = int(done * 100 / total) if total else 0
                    payload = {
                        "type": "download_progress",
                        "backend_id": backend_id,
                        "path": str(dest),
                        "bytes_done": done,
                        "bytes_total": total,
                        "progress": pct,
                    }
                    _set_job(
                        backend_id,
                        status="downloading",
                        progress=pct,
                        bytes_done=done,
                        bytes_total=total,
                        message=f"下载中 {dest.name}",
                    )
                    if on_progress:
                        on_progress(payload)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {url}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"网络错误: {e.reason}") from e

    if expected_sha:
        digest = _sha256_file(tmp)
        if digest.lower() != expected_sha.lower():
            try:
                tmp.unlink()
            except OSError:
                pass
            raise RuntimeError(
                f"校验失败: {dest.name} sha256={digest} expected={expected_sha}"
            )
    tmp.replace(dest)


def _write_installed_marker(path: Path, meta: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "installed": True,
        "meta": meta,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _download_hf_repo(
    repo_id: str,
    dest_dir: Path,
    *,
    subdir: str = "",
    on_progress: Optional[ProgressCb] = None,
    backend_id: str = "",
) -> None:
    """Prefer huggingface_hub when available; otherwise leave a clear error."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        from huggingface_hub import snapshot_download
    except ImportError as e:
        raise RuntimeError(
            "下载 Hugging Face 仓库需要 huggingface_hub。"
            "请先安装 Local Runtime（其中包含该依赖），"
            "或在系统 Python 执行: pip install huggingface_hub"
        ) from e

    def _hook(progress: Any) -> None:
        # snapshot_download tqdm hooks vary; keep job alive
        _set_job(
            backend_id,
            status="downloading",
            message=f"HF snapshot {repo_id}",
            progress=int(getattr(progress, "n", 0) or 0) % 100,
        )
        if on_progress:
            on_progress(
                {
                    "type": "download_progress",
                    "backend_id": backend_id,
                    "message": f"HF {repo_id}",
                }
            )

    allow = [f"{subdir}/*", f"{subdir}/**"] if subdir else None
    snapshot_download(
        repo_id=repo_id,
        local_dir=str(dest_dir),
        local_dir_use_symlinks=False,
        allow_patterns=allow,
        resume_download=True,
    )
    _ = _hook


def download_backend(
    backend_id: str,
    *,
    on_progress: Optional[ProgressCb] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Download all files for a whitelist backend into models_dir/{id}/.
    Must only be triggered from UI / installer — never from Agent tools.
    """
    bid = (backend_id or "").strip()
    meta = get_backend(bid)
    if not meta:
        return {"ok": False, "error": f"未知后端: {bid}"}
    if backend_ready(bid) and not force:
        return {"ok": True, "message": "已下载", "path": str(backend_dir(bid))}

    root = backend_dir(bid)
    root.mkdir(parents=True, exist_ok=True)
    _set_job(bid, status="starting", progress=0, message="开始下载", error="")

    try:
        files: List[Dict[str, Any]] = list(meta.get("files") or [])
        for idx, entry in enumerate(files):
            rel = str(entry.get("relpath") or "").strip()
            url = str(entry.get("url") or "").strip()
            sha = str(entry.get("sha256") or "").strip()
            hf_repo = str(entry.get("hf_repo") or "").strip()
            hf_subdir = str(entry.get("hf_subdir") or "").strip()
            dest = root / rel

            _set_job(
                bid,
                status="downloading",
                progress=int(idx * 100 / max(1, len(files))),
                message=f"({idx + 1}/{len(files)}) {rel}",
            )

            if url.startswith("manifest://") or hf_repo:
                if not hf_repo:
                    raise RuntimeError(f"{bid}: 缺少 hf_repo，无法解析 {url}")
                target = dest.parent if rel.endswith(".installed") else dest
                if rel.endswith(".installed"):
                    target = root / Path(rel).parent
                _download_hf_repo(
                    hf_repo,
                    target if target.suffix == "" else target.parent,
                    subdir=hf_subdir,
                    on_progress=on_progress,
                    backend_id=bid,
                )
                if rel.endswith(".installed") or rel.endswith("/.installed"):
                    marker = root / Path(rel)
                    if marker.name != ".installed":
                        marker = marker.parent / ".installed"
                    _write_installed_marker(
                        marker if marker.name == ".installed" else (target / ".installed"),
                        {"hf_repo": hf_repo, "hf_subdir": hf_subdir},
                    )
                else:
                    _write_installed_marker(
                        (root / Path(rel).parent / ".installed"),
                        {"hf_repo": hf_repo},
                    )
            else:
                if not url:
                    raise RuntimeError(f"{bid}: 文件 {rel} 缺少 url")
                _download_url(
                    url,
                    dest,
                    expected_sha=sha,
                    on_progress=on_progress,
                    backend_id=bid,
                )

        _write_installed_marker(root / ".installed", {"backend_id": bid})
        _set_job(bid, status="ready", progress=100, message="下载完成")
        return {"ok": True, "message": "下载完成", "path": str(root), "ready": True}
    except Exception as e:
        log.exception("download failed for %s", bid)
        _set_job(bid, status="error", error=str(e), message=str(e))
        return {"ok": False, "error": str(e), "path": str(root)}


def start_download_async(
    backend_id: str,
    *,
    on_progress: Optional[ProgressCb] = None,
    on_done: Optional[Callable[[Dict[str, Any]], None]] = None,
    force: bool = False,
) -> None:
    def _run() -> None:
        result = download_backend(backend_id, on_progress=on_progress, force=force)
        if on_done:
            on_done(result)

    threading.Thread(
        target=_run, name=f"local_model_dl:{backend_id}", daemon=True
    ).start()


def delete_backend(backend_id: str) -> Dict[str, Any]:
    bid = (backend_id or "").strip()
    if not get_backend(bid):
        return {"ok": False, "error": f"未知后端: {bid}"}
    root = backend_dir(bid)
    if not root.exists():
        return {"ok": True, "message": "目录不存在，视为已删除"}
    try:
        shutil.rmtree(root)
        _set_job(bid, status="idle", progress=0, message="已删除", error="")
        return {"ok": True, "message": f"已删除 {root}"}
    except OSError as e:
        return {"ok": False, "error": str(e)}
