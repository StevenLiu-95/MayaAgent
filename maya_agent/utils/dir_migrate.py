"""Migrate directory contents when user changes temp / models roots."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def resolve_configured_dir(raw: str, default: Path) -> Path:
    """Empty raw → default; always expand env/user and resolve."""
    text = (raw or "").strip()
    if text:
        path = Path(os.path.expandvars(os.path.expanduser(text)))
    else:
        path = Path(default)
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def dir_has_content(path: Path) -> bool:
    try:
        if not path.is_dir():
            return False
        return any(path.iterdir())
    except OSError:
        return False


def _is_nested(a: Path, b: Path) -> bool:
    """True if a is inside b or b is inside a."""
    try:
        a.relative_to(b)
        return True
    except ValueError:
        pass
    try:
        b.relative_to(a)
        return True
    except ValueError:
        return False


def migrate_directory_contents(
    src: Path,
    dst: Path,
    *,
    remove_empty_src: bool = True,
) -> Dict[str, Any]:
    """
    Move top-level entries from src into dst (merge on name collision for dirs).

    Returns ok/moved/skipped/errors. Does not delete leftover conflicting files.
    """
    src = resolve_configured_dir(str(src), src)
    dst = resolve_configured_dir(str(dst), dst)
    if src == dst:
        return {
            "ok": True,
            "moved": [],
            "skipped": [],
            "errors": [],
            "message": "same path",
        }
    if not src.is_dir():
        return {
            "ok": True,
            "moved": [],
            "skipped": [],
            "errors": [],
            "message": "source missing",
        }
    if _is_nested(src, dst):
        return {
            "ok": False,
            "moved": [],
            "skipped": [],
            "errors": ["source and destination nest; refuse migrate"],
            "message": "nested paths",
        }

    try:
        dst.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return {
            "ok": False,
            "moved": [],
            "skipped": [],
            "errors": [str(e)],
            "message": "cannot create destination",
        }

    moved: List[str] = []
    skipped: List[str] = []
    errors: List[str] = []

    try:
        children = list(src.iterdir())
    except OSError as e:
        return {
            "ok": False,
            "moved": [],
            "skipped": [],
            "errors": [str(e)],
            "message": "cannot list source",
        }

    for child in children:
        target = dst / child.name
        try:
            if not target.exists():
                shutil.move(str(child), str(target))
                moved.append(child.name)
                continue
            if child.is_dir() and target.is_dir():
                # Merge recursively then remove emptied source tree
                sub = migrate_directory_contents(
                    child, target, remove_empty_src=True
                )
                moved.extend(f"{child.name}/{x}" for x in sub.get("moved") or [])
                skipped.extend(f"{child.name}/{x}" for x in sub.get("skipped") or [])
                errors.extend(sub.get("errors") or [])
                if child.exists():
                    try:
                        if not any(child.iterdir()):
                            child.rmdir()
                        else:
                            skipped.append(child.name)
                    except OSError:
                        skipped.append(child.name)
                continue
            # File/dir conflict — leave source
            skipped.append(child.name)
        except OSError as e:
            errors.append(f"{child.name}: {e}")

    if remove_empty_src:
        try:
            if src.exists() and not any(src.iterdir()):
                src.rmdir()
        except OSError:
            pass

    ok = not errors
    return {
        "ok": ok,
        "moved": moved,
        "skipped": skipped,
        "errors": errors,
        "message": "migrated" if moved and not errors else ("partial" if moved else "nothing"),
        "src": str(src),
        "dst": str(dst),
    }


def plan_path_change(
    *,
    old_raw: str,
    new_raw: str,
    default: Path,
) -> Optional[Tuple[Path, Path]]:
    """
    If effective path changes and old has content, return (old_path, new_path).
    Otherwise None (no migration needed).
    """
    old_path = resolve_configured_dir(old_raw, default)
    new_path = resolve_configured_dir(new_raw, default)
    if old_path == new_path:
        return None
    if not dir_has_content(old_path):
        return None
    if _is_nested(old_path, new_path):
        return None
    return old_path, new_path
