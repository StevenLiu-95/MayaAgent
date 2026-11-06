"""
Maya version ↔ CPython ABI tag mapping (for multi-tag .vendor / vendor_cache).

Tags match PEP 425 style used as directory names: cp37, cp39, cp311.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

# Maya year → CPython ABI directory name
MAYA_ABI_TAGS: Dict[str, str] = {
    "2020": "cp37",
    "2022": "cp39",
    "2023": "cp39",
    "2024": "cp311",
    "2025": "cp311",
    "2026": "cp311",
}

KNOWN_ABI_TAGS: tuple[str, ...] = ("cp37", "cp39", "cp311")


def abi_tag_from_version_info(
    major: Optional[int] = None,
    minor: Optional[int] = None,
) -> str:
    """Return ``cpXY`` for the given (or current) interpreter."""
    if major is None or minor is None:
        major = sys.version_info.major
        minor = sys.version_info.minor
    return f"cp{major}{minor}"


def abi_tag_for_maya(version: str) -> str:
    """
    Map a Maya year string to an ABI tag.

    Unknown versions default to cp311 (Maya 2024+).
    """
    ver = str(version).strip()
    if ver in MAYA_ABI_TAGS:
        return MAYA_ABI_TAGS[ver]
    # Heuristic: numeric year
    try:
        year = int(float(ver))
    except (TypeError, ValueError):
        return "cp311"
    if year <= 2020:
        return "cp37"
    if year <= 2023:
        return "cp39"
    return "cp311"


def abi_tags_for_maya_versions(versions: Sequence[str]) -> List[str]:
    """Unique ABI tags needed for the given Maya versions (stable order)."""
    seen = set()
    out: List[str] = []
    for ver in versions:
        tag = abi_tag_for_maya(ver)
        if tag not in seen:
            seen.add(tag)
            out.append(tag)
    return out


def vendor_tag_dir(vendor_root: Path, tag: str) -> Path:
    """``.vendor/cp311`` style path."""
    return Path(vendor_root) / tag


def resolve_vendor_dir(
    vendor_root: Path,
    *,
    tag: Optional[str] = None,
    maya_version: Optional[str] = None,
) -> Optional[Path]:
    """
    Pick the best vendor directory for imports.

    Preference:
      1. ``.vendor/<tag>/`` when tag is known and exists
      2. Flat ``.vendor/`` (legacy single-tree layout) if it looks populated
      3. None
    """
    root = Path(vendor_root)
    if not root.is_dir():
        return None

    use_tag = tag
    if use_tag is None and maya_version:
        use_tag = abi_tag_for_maya(maya_version)
    if use_tag is None:
        use_tag = abi_tag_from_version_info()

    tagged = root / use_tag
    if tagged.is_dir() and any(tagged.iterdir()):
        return tagged

    # Legacy flat layout: packages directly under .vendor (no cp* children only)
    if _looks_like_flat_vendor(root):
        return root

    # Last resort: any known tag present for this interpreter family
    if tagged.is_dir():
        return tagged
    return None


def _looks_like_flat_vendor(root: Path) -> bool:
    """True if root contains package dirs that are not only ABI tag folders."""
    try:
        children = list(root.iterdir())
    except OSError:
        return False
    if not children:
        return False
    non_tag = [c for c in children if c.is_dir() and c.name not in KNOWN_ABI_TAGS]
    # httpx / matplotlib etc. live as top-level dirs in a flat vendor
    return any(non_tag)


def copy_vendor_cache_to_project(
    vendor_cache: Path,
    project_vendor: Path,
    tags: Iterable[str],
    *,
    force: bool = False,
) -> List[str]:
    """
    Copy ``vendor_cache/<tag>/`` → ``project/.vendor/<tag>/``.

    Returns list of tags successfully copied.
    """
    import shutil

    copied: List[str] = []
    cache = Path(vendor_cache)
    dest_root = Path(project_vendor)
    dest_root.mkdir(parents=True, exist_ok=True)

    for tag in tags:
        src = cache / tag
        if not src.is_dir():
            print(f"  [vendor-cache] missing {src}")
            continue
        dest = dest_root / tag
        if dest.exists():
            if not force and any(dest.iterdir()):
                print(f"  [vendor-cache] keep existing {dest}")
                copied.append(tag)
                continue
            try:
                shutil.rmtree(dest)
            except OSError as e:
                print(f"  [vendor-cache] cannot clear {dest}: {e}")
                continue
        try:
            shutil.copytree(src, dest)
            print(f"  [vendor-cache] copied {tag} → {dest}")
            copied.append(tag)
        except OSError as e:
            print(f"  [vendor-cache] copy failed {tag}: {e}")
    return copied


def parse_tags_arg(raw: str) -> List[str]:
    """Parse comma/space-separated tag list; empty → all known tags."""
    text = (raw or "").strip()
    if not text or text.lower() == "all":
        return list(KNOWN_ABI_TAGS)
    parts = []
    for chunk in text.replace(",", " ").split():
        t = chunk.strip().lower()
        if not t:
            continue
        if not t.startswith("cp"):
            t = f"cp{t}" if t.isdigit() else t
        parts.append(t)
    return parts or list(KNOWN_ABI_TAGS)
