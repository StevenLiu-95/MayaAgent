"""Tool discovery / pack activation meta-tools for layered exposure."""

from __future__ import annotations

from typing import List, Optional

from maya_agent.core.tool_exposure import (
    get_exposure_router,
    list_categories_payload,
    search_tools_payload,
    search_top_k_from_config,
)
from maya_agent.tools.registry import ToolResult, obj_schema, tool


def _router_mode_vision():
    router = get_exposure_router()
    mode = getattr(router, "mode", None) if router else None
    vision = bool(getattr(router, "vision", True)) if router else True
    return router, mode or "agent", vision


@tool(
    name="list_tool_categories",
    description=(
        "List tool categories available under the current mode/availability gates, "
        "with tool counts and whether each pack is already activated. "
        "Use before activate_tool_pack when exploring capabilities."
    ),
    parameters=obj_schema({}),
    category="discovery",
    main_thread=False,
)
def list_tool_categories() -> ToolResult:
    router, mode, vision = _router_mode_vision()
    payload = list_categories_payload(mode=mode, vision=vision, router=router)
    return ToolResult(
        ok=True,
        message=f"共 {payload.get('count', 0)} 个工具类别",
        data=payload,
    )


@tool(
    name="search_tools",
    description=(
        "Search registered tools by keyword against name, description, and category. "
        "Returns Top-K matches; does not activate them. "
        "Then call activate_tool_pack or activate_tools before using domain tools "
        "when tool exposure is layered."
    ),
    parameters=obj_schema(
        {
            "query": {
                "type": "string",
                "description": "Search text, e.g. uv, skin, meshy, export",
            },
            "top_k": {
                "type": "integer",
                "description": "Max results (default from config, typically 15)",
            },
        },
        required=["query"],
    ),
    category="discovery",
    main_thread=False,
)
def search_tools(query: str, top_k: Optional[int] = None) -> ToolResult:
    router, mode, vision = _router_mode_vision()
    limit = int(top_k) if top_k is not None else search_top_k_from_config()
    payload = search_tools_payload(
        query,
        mode=mode,
        vision=vision,
        top_k=limit,
        router=router,
    )
    return ToolResult(
        ok=True,
        message=f"找到 {payload.get('count', 0)} 个相关工具",
        data=payload,
    )


@tool(
    name="activate_tool_pack",
    description=(
        "Activate all tools in a category pack for the rest of this agent turn "
        "(layered exposure). Use list_tool_categories or search_tools to find "
        "category names (e.g. uv, rigging, modeling, meshy)."
    ),
    parameters=obj_schema(
        {
            "category": {
                "type": "string",
                "description": "Tool category / pack name",
            },
        },
        required=["category"],
    ),
    category="discovery",
    main_thread=False,
)
def activate_tool_pack(category: str) -> ToolResult:
    router = get_exposure_router()
    if router is None:
        return ToolResult(
            ok=False,
            error=(
                "当前没有活动的 ToolRouter（可能未启用 layered，或非 Agent 对话回合）。"
                "设置 agent.tool_exposure=layered 并在对话中调用。"
            ),
        )
    detail = router.activate_category(category)
    if not detail.get("ok"):
        return ToolResult(ok=False, error=detail.get("error") or "activate failed", data=detail)
    return ToolResult(
        ok=True,
        message=f"已激活类别 {detail.get('category')}（{detail.get('tool_count', 0)} 个工具）",
        data={**detail, "router": router.snapshot()},
    )


@tool(
    name="activate_tools",
    description=(
        "Activate specific tool names for the rest of this agent turn "
        "(layered exposure). Prefer activate_tool_pack for whole categories."
    ),
    parameters=obj_schema(
        {
            "names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Exact tool names to activate",
            },
        },
        required=["names"],
    ),
    category="discovery",
    main_thread=False,
)
def activate_tools(names: List[str]) -> ToolResult:
    router = get_exposure_router()
    if router is None:
        return ToolResult(
            ok=False,
            error=(
                "当前没有活动的 ToolRouter（可能未启用 layered，或非 Agent 对话回合）。"
            ),
        )
    detail = router.activate_names(names or [])
    return ToolResult(
        ok=True,
        message=f"已激活 {len(detail.get('added') or [])} 个工具",
        data={**detail, "router": router.snapshot()},
    )
