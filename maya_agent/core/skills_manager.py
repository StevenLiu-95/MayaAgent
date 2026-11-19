"""Agent Skills — discover / load SKILL.md packages (agentskills.io format)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from maya_agent.utils.logger import get_logger
from maya_agent.utils.paths import agent_skills_root, default_agent_skills_root

log = get_logger("maya_agent.skills")

_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_FRONTMATTER_RE = re.compile(
    r"\A---\s*\r?\n(.*?)\r?\n---\s*(?:\r?\n|$)(.*)\Z",
    re.DOTALL,
)

_MAX_RESOURCE_CHARS = 120_000
_skills_cache: Optional[List["SkillInfo"]] = None
_REQUIRE_KEYS = frozenset({"meshy", "tripo", "hunyuan", "adv"})

_DRAFT_EXAMPLE_MD = """---
name: example
description: Draft template — directories starting with _ are skipped by discovery.
---

# Skill 草稿说明

本目录名以 `_` 开头，**不会**被 MayaAgent 扫描。

要启用一个 Skill：

1. 在 Skills 根目录新建文件夹（名称用小写字母、数字与连字符）
2. 放入 `SKILL.md`，YAML frontmatter 至少包含 `name` 与 `description`
3. 在「扩展」页点击刷新

内置 Skill 位于插件 `resources/skills/`；用户目录同名包会覆盖内置。

参考规范：https://agentskills.io/specification
"""


def bundled_skills_root() -> Path:
    """Shipped skills under ``<project>/resources/skills``."""
    return Path(__file__).resolve().parent.parent.parent / "resources" / "skills"


@dataclass
class SkillInfo:
    """One discovered Agent Skill package."""

    name: str
    description: str
    path: Path
    skill_md_path: Path
    license: str = ""
    compatibility: str = ""
    metadata: Dict[str, str] = field(default_factory=dict)
    allowed_tools: str = ""
    disable_model_invocation: bool = False
    name_mismatch: bool = False
    raw_frontmatter_name: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "path": str(self.path).replace("\\", "/"),
            "license": self.license,
            "compatibility": self.compatibility,
            "metadata": dict(self.metadata),
            "allowed_tools": self.allowed_tools,
            "disable_model_invocation": self.disable_model_invocation,
            "name_mismatch": self.name_mismatch,
        }


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in ("1", "true", "yes", "on")


def validate_skill_name(name: str) -> Tuple[bool, str]:
    """Return (ok, error). Spec: 1–64 chars, [a-z0-9-]+, no leading/trailing/consecutive hyphens."""
    n = (name or "").strip()
    if not n:
        return False, "name is empty"
    if len(n) > 64:
        return False, "name exceeds 64 characters"
    if n.startswith("-") or n.endswith("-"):
        return False, "name must not start or end with a hyphen"
    if "--" in n:
        return False, "name must not contain consecutive hyphens"
    if not _NAME_RE.match(n):
        return False, "name must be lowercase letters, numbers, and single hyphens"
    return True, ""


def _parse_frontmatter_simple(raw: str) -> Dict[str, Any]:
    """Minimal key: value parser when PyYAML is unavailable (flat keys only)."""
    data: Dict[str, Any] = {}
    key: Optional[str] = None
    buf: List[str] = []

    def flush() -> None:
        nonlocal key, buf
        if key is None:
            return
        text = "\n".join(buf).strip()
        if text.startswith((">", "|")):
            text = text.lstrip(">|-").strip()
        if key == "disable-model-invocation":
            data[key] = _truthy(text)
        elif key == "metadata":
            # Ignore nested block without YAML.
            pass
        else:
            data[key] = text
        key = None
        buf = []

    for line in raw.splitlines():
        if not line.strip() and key is None:
            continue
        if key and (line.startswith("  ") or line.startswith("\t")):
            buf.append(line.strip())
            continue
        m = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", line)
        if m:
            flush()
            key = m.group(1).strip()
            rest = m.group(2).strip()
            if rest in (">", "|", ">-", "|-"):
                buf = []
            elif rest:
                buf = [rest]
            else:
                buf = []
        elif key:
            buf.append(line.strip())
    flush()
    return data


def parse_skill_md(text: str) -> Tuple[Dict[str, Any], str]:
    """
    Split SKILL.md into frontmatter dict and markdown body.

    Raises ValueError when frontmatter is missing or invalid.
    """
    match = _FRONTMATTER_RE.match(text or "")
    if not match:
        raise ValueError("SKILL.md must start with YAML frontmatter (--- ... ---)")
    raw_fm, body = match.group(1), match.group(2)
    data: Dict[str, Any]
    try:
        import yaml  # type: ignore

        loaded = yaml.safe_load(raw_fm) or {}
        if not isinstance(loaded, dict):
            raise ValueError("frontmatter must be a mapping")
        data = loaded
    except ImportError:
        data = _parse_frontmatter_simple(raw_fm)
    except Exception as e:
        # Fall back to simple parser if YAML content is still flat-friendly.
        try:
            data = _parse_frontmatter_simple(raw_fm)
        except Exception:
            raise ValueError(f"invalid YAML frontmatter: {e}") from e
    return data, (body or "").lstrip("\n")


def _coerce_metadata(raw: Any) -> Dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, str] = {}
    for k, v in raw.items():
        if v is None:
            continue
        if isinstance(v, (list, tuple)):
            out[str(k)] = ",".join(str(x).strip() for x in v if str(x).strip())
        else:
            out[str(k)] = str(v)
    return out


def skill_requirement_met(skill: "SkillInfo") -> bool:
    """Return False when metadata.requires names an unavailable tool family."""
    req = (skill.metadata.get("requires") or "").strip().lower()
    if not req:
        return True
    # Allow comma-separated requires (all must be met).
    parts = [p.strip() for p in re.split(r"[\s,]+", req) if p.strip()]
    for part in parts:
        if part not in _REQUIRE_KEYS:
            continue
        if part == "meshy":
            try:
                from maya_agent.tools.meshy_client import meshy_tools_available

                if not meshy_tools_available():
                    return False
            except Exception:
                return False
        elif part == "tripo":
            try:
                from maya_agent.tools.tripo_client import tripo_tools_available

                if not tripo_tools_available():
                    return False
            except Exception:
                return False
        elif part == "hunyuan":
            try:
                from maya_agent.tools.hunyuan_client import hunyuan_tools_available

                if not hunyuan_tools_available():
                    return False
            except Exception:
                return False
        elif part == "adv":
            try:
                from maya_agent.tools.adv_rig import adv_tools_available

                if not adv_tools_available():
                    return False
            except Exception:
                return False
    return True


def skill_info_from_dir(skill_dir: Path) -> Optional[SkillInfo]:
    """Parse one skill directory; return None if invalid."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        # Also accept skill.md on case-sensitive FS only when exact SKILL.md missing.
        alt = skill_dir / "skill.md"
        if alt.is_file():
            skill_md = alt
        else:
            return None
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError as e:
        log.warning("cannot read %s: %s", skill_md, e)
        return None
    try:
        fm, _body = parse_skill_md(text)
    except ValueError as e:
        log.warning("skip skill %s: %s", skill_dir.name, e)
        return None

    dir_name = skill_dir.name
    raw_name = str(fm.get("name") or "").strip()
    description = str(fm.get("description") or "").strip()
    if not description:
        log.warning("skip skill %s: empty description", dir_name)
        return None
    if len(description) > 1024:
        description = description[:1024]

    ok_dir, _ = validate_skill_name(dir_name)
    if not ok_dir:
        log.warning("skip skill dir %s: invalid directory name", dir_name)
        return None

    name = dir_name
    name_mismatch = False
    if raw_name and raw_name != dir_name:
        name_mismatch = True
        log.warning(
            "skill name mismatch: frontmatter=%r dir=%r — using directory name",
            raw_name,
            dir_name,
        )
    elif raw_name:
        ok_name, err = validate_skill_name(raw_name)
        if not ok_name:
            log.warning("skill %s has invalid frontmatter name (%s); using dir name", dir_name, err)

    disable = _truthy(fm.get("disable-model-invocation") or fm.get("disable_model_invocation"))
    allowed = fm.get("allowed-tools") or fm.get("allowed_tools") or ""
    return SkillInfo(
        name=name,
        description=description,
        path=skill_dir.resolve(),
        skill_md_path=skill_md.resolve(),
        license=str(fm.get("license") or "").strip(),
        compatibility=str(fm.get("compatibility") or "").strip()[:500],
        metadata=_coerce_metadata(fm.get("metadata")),
        allowed_tools=str(allowed).strip(),
        disable_model_invocation=disable,
        name_mismatch=name_mismatch,
        raw_frontmatter_name=raw_name,
    )


def _retire_legacy_seeded_uv(root: Path) -> None:
    """
    Older installs auto-seeded ``game-asset-uv`` without metadata.category.

    That user copy would override the richer bundled skill — move it aside once.
    """
    legacy = root / "game-asset-uv"
    if not legacy.is_dir():
        return
    info = skill_info_from_dir(legacy)
    if info is None:
        return
    if info.metadata.get("category") or info.metadata.get("categories"):
        return
    dest = root / "_legacy-game-asset-uv"
    if dest.exists():
        return
    try:
        legacy.rename(dest)
        log.info("retired legacy user skill game-asset-uv → %s", dest.name)
    except OSError as e:
        log.warning("failed to retire legacy game-asset-uv: %s", e)


def ensure_skills_dir() -> Path:
    """Create user skills root and seed draft ``_example`` if missing."""
    root = agent_skills_root()
    root.mkdir(parents=True, exist_ok=True)

    try:
        _retire_legacy_seeded_uv(root)
    except Exception:
        log.exception("retire legacy uv skill failed")

    draft = root / "_example"
    if not (draft / "SKILL.md").is_file():
        try:
            draft.mkdir(parents=True, exist_ok=True)
            (draft / "SKILL.md").write_text(_DRAFT_EXAMPLE_MD, encoding="utf-8")
        except OSError as e:
            log.warning("failed to write draft skill: %s", e)

    return root


def _scan_skills(root: Path) -> List[SkillInfo]:
    if not root.is_dir():
        return []
    found: List[SkillInfo] = []
    try:
        children = sorted(root.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return []
    for child in children:
        if not child.is_dir():
            continue
        if child.name.startswith("_"):
            continue
        if child.name.startswith("."):
            continue
        info = skill_info_from_dir(child)
        if info:
            found.append(info)
    return found


def reload_skills() -> None:
    global _skills_cache
    _skills_cache = None


def discover_skills(force_reload: bool = False) -> List[SkillInfo]:
    """
    Return cached skills: bundled ``resources/skills`` then user root.

    Same-name packages in the user skills directory override bundled ones.
    """
    global _skills_cache
    if force_reload or _skills_cache is None:
        try:
            ensure_skills_dir()
        except Exception:
            log.exception("ensure_skills_dir failed")
        by_name: Dict[str, SkillInfo] = {}
        for root in (bundled_skills_root(), agent_skills_root()):
            for info in _scan_skills(root):
                by_name[info.name] = info
        _skills_cache = sorted(by_name.values(), key=lambda s: s.name.lower())
    return list(_skills_cache or [])


def get_skill(name: str) -> Optional[SkillInfo]:
    key = (name or "").strip()
    if not key:
        return None
    for s in discover_skills():
        if s.name == key:
            return s
    return None


def load_skill(name: str) -> Dict[str, Any]:
    """Load full skill instructions (body) for progressive disclosure level 2."""
    info = get_skill(name)
    if not info:
        raise FileNotFoundError(f"unknown skill: {name}")
    text = info.skill_md_path.read_text(encoding="utf-8")
    fm, body = parse_skill_md(text)
    return {
        "name": info.name,
        "description": info.description,
        "path": str(info.path).replace("\\", "/"),
        "license": info.license,
        "compatibility": info.compatibility,
        "metadata": dict(info.metadata),
        "allowed_tools": info.allowed_tools,
        "disable_model_invocation": info.disable_model_invocation,
        "instructions": body.strip(),
        "frontmatter": {
            k: v
            for k, v in fm.items()
            if k
            in (
                "name",
                "description",
                "license",
                "compatibility",
                "metadata",
                "allowed-tools",
                "disable-model-invocation",
            )
        },
    }


def _resolve_under_skill(skill: SkillInfo, relative_path: str) -> Path:
    rel = (relative_path or "").strip().replace("\\", "/")
    if not rel or rel.startswith("/") or rel.startswith("~"):
        raise ValueError("relative_path must be a relative path inside the skill package")
    # Reject absolute Windows paths
    if len(rel) >= 2 and rel[1] == ":":
        raise ValueError("relative_path must not be absolute")
    parts = Path(rel).parts
    if ".." in parts:
        raise ValueError("path traversal is not allowed")
    target = (skill.path / rel).resolve()
    root = skill.path.resolve()
    try:
        target.relative_to(root)
    except ValueError as e:
        raise ValueError("path escapes skill directory") from e
    return target


def read_skill_resource(name: str, relative_path: str, max_chars: int = _MAX_RESOURCE_CHARS) -> Dict[str, Any]:
    """Read a text file inside a skill package (progressive disclosure level 3)."""
    info = get_skill(name)
    if not info:
        raise FileNotFoundError(f"unknown skill: {name}")
    target = _resolve_under_skill(info, relative_path)
    if not target.is_file():
        raise FileNotFoundError(f"resource not found: {relative_path}")
    # Skip obviously binary extensions
    if target.suffix.lower() in (
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".fbx",
        ".obj",
        ".abc",
        ".usd",
        ".usda",
        ".usdc",
        ".bin",
        ".exe",
        ".dll",
        ".so",
        ".zip",
        ".7z",
    ):
        raise ValueError(f"binary resource not supported via read_skill_resource: {relative_path}")
    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(f"resource is not valid UTF-8 text: {relative_path}") from e
    truncated = False
    limit = max(500, int(max_chars or _MAX_RESOURCE_CHARS))
    if len(text) > limit:
        text = text[: limit - 40].rstrip() + "\n…[truncated]"
        truncated = True
    return {
        "name": info.name,
        "path": relative_path.replace("\\", "/"),
        "content": text,
        "truncated": truncated,
        "chars": len(text),
    }


def get_skills_catalog_for_prompt(max_chars: Optional[int] = None) -> str:
    """
    Build ``<available_skills>`` block for the system prompt (metadata only).

    Skills with ``disable-model-invocation`` are omitted from the auto catalog.
    """
    from maya_agent.utils.config import get_config

    cfg = get_config()
    if not bool(cfg.get("agent.skills_enabled", True)):
        return ""
    if max_chars is None:
        max_chars = int(cfg.get("agent.skills_max_catalog_chars", 4000) or 4000)
    max_chars = max(200, int(max_chars))

    skills = [
        s
        for s in discover_skills()
        if not s.disable_model_invocation and skill_requirement_met(s)
    ]
    if not skills:
        return ""

    lines: List[str] = []
    for s in skills:
        lines.append(f"- {s.name}: {s.description}")
    body = "\n".join(lines)
    header = (
        "<available_skills>\n"
        "The following Agent Skills are installed. When a task matches a skill "
        "description, call `read_skill` with that skill name to load full instructions "
        "(and activate the skill's tool category pack under layered exposure). "
        "Use `read_skill_resource` for files referenced from the skill "
        "(scripts/, references/, assets/). Use `list_skills` to refresh the list. "
        "If no skill matches, use `search_tools` / `activate_tool_pack`.\n\n"
    )
    footer = "\n</available_skills>"
    overhead = len(header) + len(footer)
    budget = max(100, max_chars - overhead)
    if len(body) > budget:
        body = body[: budget - 40].rstrip() + "\n…[skills catalog truncated]"
    return header + body + footer


def skills_root_display() -> str:
    """Absolute skills root for UI placeholder / status."""
    try:
        return str(agent_skills_root()).replace("\\", "/")
    except Exception:
        return str(default_agent_skills_root()).replace("\\", "/")
