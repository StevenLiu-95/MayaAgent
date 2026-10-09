"""Shared filesystem helpers for Agent file tools (whitelist + chat image staging)."""

from __future__ import annotations

import base64
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

from maya_agent.utils.logger import get_logger
from maya_agent.utils.paths import (
    agent_temp_root,
    agent_temp_subdir,
    project_root,
)

log = get_logger("maya_agent.fsutil")

DEFAULT_READ_MAX = 512_000  # ~500 KB text
HARD_READ_MAX = 2_000_000
DEFAULT_LIST_LIMIT = 200

# Process-local index of recently staged chat images (newest last).
_RECENT_CHAT_IMAGES: List[Dict[str, Any]] = []
_LAST_USER_ATTACHMENTS: List[Any] = []
_CHAT_INDEX_NAME = "index.json"


class FsError(Exception):
    """User-facing filesystem error."""


def workspace_root() -> Path:
    """
    Agent file workspace under the configured temp root.

    Layout: ``{agent_temp_root}/`` with ``temp/`` and ``chat_images/``.
    """
    root = agent_temp_root()
    (root / "temp").mkdir(parents=True, exist_ok=True)
    (root / "chat_images").mkdir(parents=True, exist_ok=True)
    return root


def chat_images_dir() -> Path:
    return agent_temp_subdir("chat_images")


def temp_dir() -> Path:
    return agent_temp_subdir("temp")


def _maya_roots() -> List[Path]:
    roots: List[Path] = []
    try:
        from maya_agent.utils.maya_compat import in_maya

        if not in_maya():
            return roots
        import maya.cmds as cmds

        for getter in (
            lambda: cmds.internalVar(userScriptDir=True),
            lambda: cmds.internalVar(userAppDir=True),
            lambda: cmds.internalVar(userPrefDir=True),
            lambda: cmds.workspace(q=True, rootDirectory=True),
            lambda: os.path.dirname(cmds.file(query=True, sceneName=True) or ""),
        ):
            try:
                raw = getter() or ""
            except Exception:
                raw = ""
            raw = str(raw).strip()
            if not raw:
                continue
            p = Path(raw).resolve()
            if p.is_dir() and p not in roots:
                roots.append(p)
    except Exception:
        pass
    return roots


def allowed_write_roots() -> List[Path]:
    roots: List[Path] = [
        agent_temp_root().resolve(),
        project_root().resolve(),
    ]
    # Legacy locations (pre-unified temp root) remain writable
    for legacy in (
        project_root().parent / "maya_agent_files",
        project_root().parent / "meshy_downloads",
    ):
        try:
            legacy_r = legacy.resolve()
            if legacy_r not in roots:
                roots.append(legacy_r)
        except Exception:
            pass
    for r in _maya_roots():
        if r not in roots:
            roots.append(r)
    return roots


def _norm(path: Union[str, Path]) -> Path:
    return Path(os.path.expanduser(str(path))).resolve()


def is_under_roots(path: Union[str, Path], roots: Optional[Sequence[Path]] = None) -> bool:
    target = _norm(path)
    for root in roots or allowed_write_roots():
        try:
            root_r = root.resolve()
            target.relative_to(root_r)
            return True
        except ValueError:
            continue
        except Exception:
            continue
    return False


def assert_writable(path: Union[str, Path]) -> Path:
    p = _norm(path)
    if not is_under_roots(p):
        raise FsError(
            f"路径不在可写白名单内: {p}。"
            "允许写入 maya_agent_files / meshy_downloads / MayaAgent 工程 / "
            "场景目录 / Maya workspace / userScript 等。"
        )
    return p


def resolve_path(
    path: str,
    *,
    must_exist: bool = False,
    base: Optional[Union[str, Path]] = None,
) -> Path:
    raw = (path or "").strip()
    if not raw:
        raise FsError("路径为空")
    expanded = os.path.expanduser(raw)
    p = Path(expanded)
    if not p.is_absolute():
        root = Path(base) if base else workspace_root()
        p = root / p
    p = p.resolve()
    if must_exist and not p.exists():
        raise FsError(f"路径不存在: {p}")
    return p


def file_info(path: Union[str, Path]) -> Dict[str, Any]:
    p = _norm(path) if not isinstance(path, Path) else path.resolve()
    info: Dict[str, Any] = {
        "path": str(p).replace("\\", "/"),
        "exists": p.exists(),
        "writable_zone": is_under_roots(p),
    }
    if not p.exists():
        return info
    try:
        st = p.stat()
        info.update(
            {
                "is_file": p.is_file(),
                "is_dir": p.is_dir(),
                "size_bytes": st.st_size if p.is_file() else None,
                "mtime": st.st_mtime,
                "name": p.name,
                "suffix": p.suffix.lower(),
            }
        )
    except OSError as e:
        info["error"] = str(e)
    return info


def list_dir(
    directory: Union[str, Path],
    *,
    pattern: str = "",
    recursive: bool = False,
    limit: int = DEFAULT_LIST_LIMIT,
    files_only: bool = False,
) -> Dict[str, Any]:
    root = resolve_path(str(directory), must_exist=True)
    if not root.is_dir():
        raise FsError(f"不是目录: {root}")
    limit = max(1, min(int(limit), 1000))
    pat = (pattern or "").lower()
    entries: List[Dict[str, Any]] = []

    def _match(name: str) -> bool:
        if not pat:
            return True
        n = name.lower()
        if pat.startswith("*."):
            return n.endswith(pat[1:])
        if pat.startswith("."):
            return n.endswith(pat)
        return pat in n

    if recursive:
        for dirpath, dirnames, filenames in os.walk(root):
            if not files_only:
                for dn in dirnames:
                    if not _match(dn):
                        continue
                    fp = Path(dirpath) / dn
                    entries.append(
                        {
                            "path": str(fp).replace("\\", "/"),
                            "name": dn,
                            "is_dir": True,
                        }
                    )
                    if len(entries) >= limit:
                        break
            for fn in filenames:
                if not _match(fn):
                    continue
                fp = Path(dirpath) / fn
                try:
                    size = fp.stat().st_size
                except OSError:
                    size = None
                entries.append(
                    {
                        "path": str(fp).replace("\\", "/"),
                        "name": fn,
                        "is_dir": False,
                        "size_bytes": size,
                    }
                )
                if len(entries) >= limit:
                    break
            if len(entries) >= limit:
                break
    else:
        for child in sorted(root.iterdir(), key=lambda x: x.name.lower()):
            if files_only and not child.is_file():
                continue
            if not _match(child.name):
                continue
            item: Dict[str, Any] = {
                "path": str(child).replace("\\", "/"),
                "name": child.name,
                "is_dir": child.is_dir(),
            }
            if child.is_file():
                try:
                    item["size_bytes"] = child.stat().st_size
                except OSError:
                    item["size_bytes"] = None
            entries.append(item)
            if len(entries) >= limit:
                break

    return {
        "directory": str(root).replace("\\", "/"),
        "count": len(entries),
        "entries": entries,
    }


def read_text(
    path: Union[str, Path],
    *,
    max_chars: int = DEFAULT_READ_MAX,
    encoding: str = "utf-8",
) -> Dict[str, Any]:
    p = resolve_path(str(path), must_exist=True)
    if not p.is_file():
        raise FsError(f"不是文件: {p}")
    max_chars = max(500, min(int(max_chars), HARD_READ_MAX))
    try:
        text = p.read_text(encoding=encoding, errors="replace")
    except OSError as e:
        raise FsError(f"读取失败: {e}") from e
    truncated = len(text) > max_chars
    return {
        "path": str(p).replace("\\", "/"),
        "size_chars": len(text),
        "truncated": truncated,
        "content": text[:max_chars],
        "encoding": encoding,
    }


def write_text(
    path: Union[str, Path],
    content: str,
    *,
    overwrite: bool = False,
    create_dirs: bool = True,
    encoding: str = "utf-8",
    require_whitelist: bool = True,
) -> Dict[str, Any]:
    p = resolve_path(str(path), must_exist=False)
    if require_whitelist:
        assert_writable(p)
    if p.exists() and p.is_dir():
        raise FsError(f"目标是目录，无法写入文件: {p}")
    if p.exists() and not overwrite:
        raise FsError(f"文件已存在，未覆盖: {p}（设 overwrite=true 可覆盖）")
    parent = p.parent
    if create_dirs and parent and not parent.is_dir():
        parent.mkdir(parents=True, exist_ok=True)
    data = content if isinstance(content, str) else str(content)
    p.write_text(data, encoding=encoding, newline="\n")
    raw = data.encode(encoding, errors="replace")
    return {
        "path": str(p).replace("\\", "/"),
        "bytes": len(raw),
        "overwritten": bool(p.exists()),
    }


def copy_path(
    src: Union[str, Path],
    dst: Union[str, Path],
    *,
    overwrite: bool = False,
) -> Dict[str, Any]:
    source = resolve_path(str(src), must_exist=True)
    dest = resolve_path(str(dst), must_exist=False)
    assert_writable(dest)
    if source.is_dir():
        raise FsError("暂不支持复制整个目录，请指定文件")
    if dest.exists() and dest.is_dir():
        dest = dest / source.name
        assert_writable(dest)
    if dest.exists() and not overwrite:
        raise FsError(f"目标已存在: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(source), str(dest))
    return {
        "src": str(source).replace("\\", "/"),
        "dst": str(dest).replace("\\", "/"),
        "size_bytes": dest.stat().st_size,
    }


def delete_path(path: Union[str, Path], *, allow_nonempty_dir: bool = False) -> Dict[str, Any]:
    p = resolve_path(str(path), must_exist=True)
    assert_writable(p)
    # Extra safety: never delete project roots themselves
    protected = {r.resolve() for r in allowed_write_roots()}
    if p.resolve() in protected:
        raise FsError(f"禁止删除白名单根目录本身: {p}")
    if p.is_file() or p.is_symlink():
        p.unlink()
        kind = "file"
    elif p.is_dir():
        if allow_nonempty_dir:
            shutil.rmtree(str(p))
            kind = "dir_tree"
        else:
            try:
                p.rmdir()
            except OSError as e:
                raise FsError(f"目录非空或无法删除: {e}") from e
            kind = "dir"
    else:
        raise FsError(f"无法删除: {p}")
    return {"path": str(p).replace("\\", "/"), "deleted": True, "kind": kind}


def _mime_to_ext(mime: str, name: str = "") -> str:
    name_ext = Path(name or "").suffix.lower()
    if name_ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"):
        return name_ext
    m = (mime or "").lower()
    if "jpeg" in m or m == "image/jpg":
        return ".jpg"
    if "webp" in m:
        return ".webp"
    if "gif" in m:
        return ".gif"
    return ".png"


def _chat_index_path() -> Path:
    return chat_images_dir() / _CHAT_INDEX_NAME


def _load_chat_index() -> List[Dict[str, Any]]:
    path = _chat_index_path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict) and x.get("path")]
    except Exception:
        pass
    return []


def _save_chat_index(items: List[Dict[str, Any]]) -> None:
    # Keep last 40 entries
    trimmed = items[-40:]
    try:
        _chat_index_path().write_text(
            json.dumps(trimmed, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        log.debug("save chat index failed: %s", e)


def stage_chat_images(attachments: Iterable[Any]) -> List[Dict[str, Any]]:
    """
    Persist chat ImageAttachment objects to disk under chat_images/.
    Returns list of {path, name, mime, size_bytes}.
    """
    global _RECENT_CHAT_IMAGES, _LAST_USER_ATTACHMENTS
    atts = [a for a in (attachments or []) if a is not None]
    if atts:
        _LAST_USER_ATTACHMENTS = list(atts)
    out: List[Dict[str, Any]] = []
    stamp = time.strftime("%Y%m%d_%H%M%S")
    for idx, img in enumerate(atts):
        data_b64 = getattr(img, "data_b64", None)
        mime = getattr(img, "mime", "") or "image/png"
        name = getattr(img, "name", "") or ""
        if isinstance(img, dict):
            data_b64 = img.get("data_b64") or data_b64
            mime = img.get("mime") or mime
            name = img.get("name") or name
        if not data_b64:
            continue
        try:
            raw = base64.b64decode(data_b64)
        except Exception:
            continue
        ext = _mime_to_ext(str(mime), str(name))
        safe_name = Path(name).stem if name else "chat"
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in safe_name)[:40]
        filename = f"{stamp}_{idx:02d}_{safe_name or 'img'}{ext}"
        dest = chat_images_dir() / filename
        try:
            dest.write_bytes(raw)
        except OSError as e:
            log.warning("stage chat image failed: %s", e)
            continue
        item = {
            "path": str(dest).replace("\\", "/"),
            "name": filename,
            "mime": mime,
            "size_bytes": len(raw),
            "original_name": name or "",
            "staged_at": time.time(),
        }
        out.append(item)
        _RECENT_CHAT_IMAGES.append(item)
    if out:
        disk = _load_chat_index()
        disk.extend(out)
        _save_chat_index(disk)
        _RECENT_CHAT_IMAGES = _RECENT_CHAT_IMAGES[-40:]
    return out


def restage_last_chat_images() -> List[Dict[str, Any]]:
    """Re-write the last remembered user attachments to disk."""
    if not _LAST_USER_ATTACHMENTS:
        return []
    return stage_chat_images(_LAST_USER_ATTACHMENTS)


def latest_chat_image_paths(limit: int = 4) -> List[str]:
    limit = max(1, min(int(limit), 20))
    items = list(_RECENT_CHAT_IMAGES)
    if len(items) < limit:
        # Merge from disk index (newest last)
        for it in _load_chat_index():
            p = it.get("path")
            if p and not any(x.get("path") == p for x in items):
                items.append(it)
    # Prefer newest
    items = sorted(items, key=lambda x: float(x.get("staged_at") or 0))
    paths: List[str] = []
    for it in reversed(items):
        p = str(it.get("path") or "")
        if p and Path(p).is_file() and p not in paths:
            paths.append(p)
        if len(paths) >= limit:
            break
    return paths


def list_staged_chat_images(limit: int = 20) -> List[Dict[str, Any]]:
    paths = latest_chat_image_paths(limit=limit)
    result: List[Dict[str, Any]] = []
    by_path = {str(x.get("path")): x for x in (_RECENT_CHAT_IMAGES + _load_chat_index())}
    for p in paths:
        meta = dict(by_path.get(p) or {})
        meta.update(file_info(p))
        result.append(meta)
    return result


def stage_images_from_memory_messages(messages: Sequence[Any]) -> List[Dict[str, Any]]:
    """Find the latest user message with images and stage them."""
    for msg in reversed(list(messages or [])):
        role = getattr(msg, "role", None) or (msg.get("role") if isinstance(msg, dict) else None)
        if role != "user":
            continue
        images = getattr(msg, "images", None)
        if images is None and isinstance(msg, dict):
            images = msg.get("images")
        if images:
            return stage_chat_images(images)
    return []
