"""Unified tool exposure pipeline: availability → mode → router."""

from __future__ import annotations

import contextvars
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from maya_agent.core.agent_mode import is_tool_allowed, normalize_mode
from maya_agent.llm.base import ToolSpec
from maya_agent.utils.config import get_config

EXPOSURE_FULL = "full"
EXPOSURE_LAYERED = "layered"

# Core tools always visible in layered mode (after availability + mode).
ALWAYS_ON_TOOLS: frozenset = frozenset(
    {
        # Discovery / skills
        "list_tool_categories",
        "search_tools",
        "activate_tool_pack",
        "activate_tools",
        "list_skills",
        "read_skill",
        "read_skill_resource",
        # Plan (mode still gates create/update)
        "create_plan",
        "update_plan_step",
        # Scene / selection
        "get_scene_info",
        "list_selection",
        "list_materials",
        "list_skeleton_templates",
        "list_skinned_meshes",
        # Scripting fallback
        "execute_python",
        # Files (mostly read)
        "list_directory",
        "path_info",
        "read_text_file",
        "list_chat_images",
        "list_chat_files",
        # Web
        "web_search",
        "fetch_webpage",
        # Light vision (charts via data-visualization skill → analysis pack)
        "capture_viewport",
    }
)

_router_var: contextvars.ContextVar[Optional["ToolRouter"]] = contextvars.ContextVar(
    "maya_agent_tool_router", default=None
)
_fallback_router: Optional["ToolRouter"] = None


def set_exposure_router_fallback(router: Optional["ToolRouter"]) -> None:
    global _fallback_router
    _fallback_router = router


def push_exposure_router(router: Optional["ToolRouter"]):
    return _router_var.set(router)


def reset_exposure_router(token) -> None:
    _router_var.reset(token)


def get_exposure_router() -> Optional["ToolRouter"]:
    router = _router_var.get()
    if router is not None:
        return router
    return _fallback_router


def normalize_exposure(value: Optional[str], *, default: str = EXPOSURE_LAYERED) -> str:
    raw = (value or "").strip().lower()
    if raw in (EXPOSURE_FULL, EXPOSURE_LAYERED):
        return raw
    return default if default in (EXPOSURE_FULL, EXPOSURE_LAYERED) else EXPOSURE_LAYERED


def exposure_from_config() -> str:
    try:
        cfg = get_config()
        return normalize_exposure(cfg.get("agent.tool_exposure", EXPOSURE_LAYERED))
    except Exception:
        return EXPOSURE_LAYERED


def search_top_k_from_config(default: int = 15) -> int:
    try:
        return max(1, min(50, int(get_config().get("agent.tool_search_top_k", default))))
    except Exception:
        return default


@dataclass
class ToolRouter:
    """Per-chat-turn active tool set for layered exposure."""

    always_on: Set[str] = field(default_factory=lambda: set(ALWAYS_ON_TOOLS))
    active_categories: Set[str] = field(default_factory=set)
    active_names: Set[str] = field(default_factory=set)
    activated_skills: Set[str] = field(default_factory=set)
    exposure: str = EXPOSURE_LAYERED
    # Set by MayaAgent.chat for discovery tools / executor hints.
    mode: Optional[str] = None
    vision: bool = True

    @classmethod
    def from_config(cls) -> "ToolRouter":
        return cls(exposure=exposure_from_config())

    def reset(self) -> None:
        self.active_categories.clear()
        self.active_names.clear()
        self.activated_skills.clear()

    def activate_category(self, category: str) -> Dict[str, Any]:
        cat = (category or "").strip()
        if not cat:
            return {"ok": False, "error": "category is empty", "added": 0}
        self.active_categories.add(cat)
        from maya_agent.tools.registry import tools_by_category

        tools = tools_by_category().get(cat) or []
        return {
            "ok": True,
            "category": cat,
            "tool_count": len(tools),
            "tool_names": [t.name for t in tools],
            "active_categories": sorted(self.active_categories),
        }

    def activate_names(self, names: Sequence[str]) -> Dict[str, Any]:
        from maya_agent.tools.registry import get_tool

        added: List[str] = []
        missing: List[str] = []
        for raw in names or []:
            name = (raw or "").strip()
            if not name:
                continue
            if get_tool(name) is None:
                missing.append(name)
                continue
            self.active_names.add(name)
            added.append(name)
        return {
            "ok": True,
            "added": added,
            "missing": missing,
            "active_names": sorted(self.active_names),
            "active_categories": sorted(self.active_categories),
        }

    def activate_from_skill(self, skill: Any) -> Dict[str, Any]:
        """Activate tools declared by a SkillInfo / load_skill payload."""
        name = ""
        allowed = ""
        metadata: Dict[str, str] = {}
        if isinstance(skill, dict):
            name = str(skill.get("name") or "").strip()
            allowed = str(skill.get("allowed_tools") or skill.get("allowed-tools") or "").strip()
            meta = skill.get("metadata") or {}
            if isinstance(meta, dict):
                metadata = {str(k): str(v) for k, v in meta.items() if v is not None}
        else:
            name = str(getattr(skill, "name", "") or "").strip()
            allowed = str(getattr(skill, "allowed_tools", "") or "").strip()
            meta = getattr(skill, "metadata", None) or {}
            if isinstance(meta, dict):
                metadata = {str(k): str(v) for k, v in meta.items() if v is not None}

        if name:
            self.activated_skills.add(name)

        result: Dict[str, Any] = {
            "ok": True,
            "skill": name,
            "activated_via": None,
            "detail": {},
        }
        if allowed:
            names = [p for p in re.split(r"[\s,]+", allowed) if p]
            detail = self.activate_names(names)
            result["activated_via"] = "allowed-tools"
            result["detail"] = detail
            return result

        cats_raw = (
            metadata.get("categories")
            or metadata.get("category")
            or metadata.get("tool_category")
            or metadata.get("tool-category")
            or ""
        ).strip()
        cats = [p for p in re.split(r"[\s,]+", cats_raw) if p]
        # Dedupe preserving order
        seen: Set[str] = set()
        ordered: List[str] = []
        for c in cats:
            if c not in seen:
                seen.add(c)
                ordered.append(c)
        if ordered:
            details = []
            for cat in ordered:
                details.append(self.activate_category(cat))
            result["activated_via"] = (
                "metadata.categories" if len(ordered) > 1 else "metadata.category"
            )
            result["detail"] = {
                "categories": ordered,
                "activations": details,
                "active_categories": sorted(self.active_categories),
            }
            return result

        result["activated_via"] = None
        result["detail"] = {
            "message": "no allowed-tools or metadata.category/categories; instructions only"
        }
        return result

    def is_active(self, tool_name: str, *, category: str = "") -> bool:
        if self.exposure == EXPOSURE_FULL:
            return True
        name = (tool_name or "").strip()
        if name in self.always_on or name in self.active_names:
            return True
        cat = (category or "").strip()
        if cat and cat in self.active_categories:
            return True
        return False

    def expand_active_names(self) -> Set[str]:
        from maya_agent.tools.registry import tools_by_category

        names = set(self.always_on) | set(self.active_names)
        by_cat = tools_by_category()
        for cat in self.active_categories:
            for t in by_cat.get(cat) or []:
                names.add(t.name)
        return names

    def snapshot(self) -> Dict[str, Any]:
        return {
            "exposure": self.exposure,
            "mode": self.mode,
            "vision": self.vision,
            "always_on_count": len(self.always_on),
            "active_categories": sorted(self.active_categories),
            "active_names": sorted(self.active_names),
            "activated_skills": sorted(self.activated_skills),
            "expanded_count": len(self.expand_active_names()),
        }


@dataclass
class ExposureContext:
    mode: Optional[str] = None
    vision: bool = True
    exposure: str = EXPOSURE_FULL
    router: Optional[ToolRouter] = None

    @classmethod
    def for_agent_turn(
        cls,
        *,
        mode: Optional[str],
        vision: bool,
        router: ToolRouter,
    ) -> "ExposureContext":
        return cls(
            mode=mode,
            vision=vision,
            exposure=normalize_exposure(router.exposure),
            router=router,
        )

    @classmethod
    def for_catalog(
        cls,
        *,
        mode: Optional[str] = None,
        vision: bool = True,
    ) -> "ExposureContext":
        """MCP / tests / prompts: availability + mode only (no router narrowing)."""
        return cls(
            mode=mode,
            vision=vision,
            exposure=EXPOSURE_FULL,
            router=None,
        )


def _availability_flags() -> Dict[str, bool]:
    meshy_ok = True
    try:
        from maya_agent.tools.meshy_client import meshy_tools_available

        meshy_ok = meshy_tools_available()
    except Exception:
        meshy_ok = False

    tripo_ok = True
    try:
        from maya_agent.tools.tripo_client import tripo_tools_available

        tripo_ok = tripo_tools_available()
    except Exception:
        tripo_ok = False

    hunyuan_ok = True
    try:
        from maya_agent.tools.hunyuan_client import hunyuan_tools_available

        hunyuan_ok = hunyuan_tools_available()
    except Exception:
        hunyuan_ok = False

    adv_ok = True
    try:
        from maya_agent.tools.adv_rig import adv_tools_available

        adv_ok = adv_tools_available()
    except Exception:
        adv_ok = False

    return {
        "meshy": meshy_ok,
        "tripo": tripo_ok,
        "hunyuan": hunyuan_ok,
        "adv": adv_ok,
    }


def filter_availability(tools: Iterable[Any], vision: bool = True) -> List[Any]:
    flags = _availability_flags()
    out: List[Any] = []
    for t in tools:
        if getattr(t, "requires_vision", False) and not vision:
            continue
        cat = getattr(t, "category", "") or ""
        if cat == "meshy" and not flags["meshy"]:
            continue
        if cat == "tripo" and not flags["tripo"]:
            continue
        if cat == "hunyuan" and not flags["hunyuan"]:
            continue
        if cat == "adv" and not flags["adv"]:
            continue
        out.append(t)
    return out


def filter_mode(tools: Iterable[Any], mode: Optional[str]) -> List[Any]:
    filter_mode_name = normalize_mode(mode)
    return [t for t in tools if is_tool_allowed(t, filter_mode_name)]


def filter_router(tools: Iterable[Any], router: Optional[ToolRouter], exposure: str) -> List[Any]:
    if normalize_exposure(exposure) == EXPOSURE_FULL or router is None:
        return list(tools)
    if getattr(router, "exposure", EXPOSURE_LAYERED) == EXPOSURE_FULL:
        return list(tools)
    active = router.expand_active_names()
    return [t for t in tools if getattr(t, "name", "") in active]


def resolve_registered_tools(ctx: ExposureContext) -> List[Any]:
    from maya_agent.tools.registry import all_tools, ensure_tools_loaded

    ensure_tools_loaded()
    tools = filter_availability(all_tools(), vision=bool(ctx.vision))
    tools = filter_mode(tools, ctx.mode)
    tools = filter_router(tools, ctx.router, ctx.exposure)
    return tools


def resolve_tool_specs(ctx: ExposureContext) -> List[ToolSpec]:
    tools = resolve_registered_tools(ctx)
    return [
        ToolSpec(name=t.name, description=t.description, parameters=t.parameters)
        for t in tools
    ]


def not_activated_message(tool_name: str) -> str:
    return (
        f"工具 `{tool_name}` 已注册，但当前为分层暴露（layered），尚未激活。"
        f"请先调用 `search_tools` / `activate_tool_pack` / `activate_tools`，"
        f"或 `read_skill`（若 Skill 声明了 allowed-tools / metadata.category）。"
    )


def list_categories_payload(
    *,
    mode: Optional[str],
    vision: bool = True,
    router: Optional[ToolRouter] = None,
) -> Dict[str, Any]:
    """Category summary after availability + mode (before router narrowing)."""
    from maya_agent.tools.registry import all_tools, ensure_tools_loaded

    ensure_tools_loaded()
    base = filter_mode(filter_availability(all_tools(), vision=vision), mode)
    cats: Dict[str, List[str]] = {}
    for t in base:
        cats.setdefault(t.category or "general", []).append(t.name)
    active_cats = set(router.active_categories) if router else set()
    items = []
    for cat in sorted(cats.keys()):
        names = sorted(cats[cat])
        items.append(
            {
                "category": cat,
                "tool_count": len(names),
                "activated": cat in active_cats,
                "tools": names,
            }
        )
    return {
        "count": len(items),
        "categories": items,
        "router": router.snapshot() if router else None,
    }


def search_tools_payload(
    query: str,
    *,
    mode: Optional[str],
    vision: bool = True,
    top_k: Optional[int] = None,
    router: Optional[ToolRouter] = None,
) -> Dict[str, Any]:
    from maya_agent.tools.registry import all_tools, ensure_tools_loaded

    ensure_tools_loaded()
    base = filter_mode(filter_availability(all_tools(), vision=vision), mode)
    q = (query or "").strip().lower()
    tokens = [t for t in re.split(r"[\s/_-]+", q) if t]
    scored: List[tuple] = []
    for t in base:
        name = (t.name or "").lower()
        desc = (t.description or "").lower()
        cat = (t.category or "").lower()
        score = 0
        if q and q in name:
            score += 50
        if q and q in cat:
            score += 30
        if q and q in desc:
            score += 10
        for tok in tokens:
            if tok in name:
                score += 20
            elif tok in cat:
                score += 12
            elif tok in desc:
                score += 5
        if score <= 0 and not tokens:
            continue
        if score <= 0:
            continue
        scored.append(
            (
                score,
                {
                    "name": t.name,
                    "category": t.category,
                    "description": t.description,
                    "activated": bool(
                        router and router.is_active(t.name, category=t.category)
                    ),
                    "score": score,
                },
            )
        )
    scored.sort(key=lambda x: (-x[0], x[1]["name"]))
    limit = top_k if top_k is not None else search_top_k_from_config()
    hits = [item for _, item in scored[:limit]]
    return {
        "query": query,
        "count": len(hits),
        "tools": hits,
        "router": router.snapshot() if router else None,
    }


def exposure_status_for_prompt(*, mode: Optional[str] = None, vision: bool = True) -> str:
    """Short env blurb for system prompt."""
    exposure = exposure_from_config()
    full_n = len(resolve_tool_specs(ExposureContext.for_catalog(mode=mode, vision=vision)))
    if exposure == EXPOSURE_FULL:
        return f"- 工具暴露: full（可见 {full_n}）\n"
    router = ToolRouter.from_config()
    core_n = len(
        resolve_tool_specs(
            ExposureContext.for_agent_turn(mode=mode, vision=vision, router=router)
        )
    )
    from maya_agent.tools.registry import all_tools, ensure_tools_loaded

    ensure_tools_loaded()
    base = filter_mode(filter_availability(all_tools(), vision=vision), mode)
    cats = sorted({(t.category or "general") for t in base})
    return (
        f"- 工具暴露: layered（本轮核心约 {core_n}；全量可用约 {full_n}；"
        f"可用类别 {len(cats)}，先 search_tools / activate_tool_pack / read_skill）\n"
    )
