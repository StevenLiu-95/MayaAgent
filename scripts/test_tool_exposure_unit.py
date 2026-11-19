"""Unit tests for unified tool exposure + router (no Maya required)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    from maya_agent.core.agent_mode import is_tool_allowed
    from maya_agent.core.tool_exposure import (
        ALWAYS_ON_TOOLS,
        EXPOSURE_FULL,
        EXPOSURE_LAYERED,
        ExposureContext,
        ToolRouter,
        filter_availability,
        filter_mode,
        resolve_tool_specs,
    )
    from maya_agent.tools.registry import (
        all_tools,
        ensure_tools_loaded,
        get_tool,
        tool_specs,
        tools_by_category,
    )

    ensure_tools_loaded()

    # --- catalog API stays full-after-gates ---
    catalog = {s.name for s in tool_specs(vision=True, mode="agent")}
    assert "get_scene_info" in catalog
    assert "search_tools" in catalog
    assert "activate_tool_pack" in catalog
    assert len(catalog) > 50, f"catalog too small: {len(catalog)}"

    full_ctx = ExposureContext(
        mode="agent", vision=True, exposure=EXPOSURE_FULL, router=None
    )
    full_names = {s.name for s in resolve_tool_specs(full_ctx)}
    assert full_names == catalog

    # --- layered: initial only always_on (that pass gates) ---
    router = ToolRouter(exposure=EXPOSURE_LAYERED)
    router.mode = "agent"
    router.vision = True
    layered0 = {
        s.name
        for s in resolve_tool_specs(
            ExposureContext.for_agent_turn(mode="agent", vision=True, router=router)
        )
    }
    assert layered0, "layered core empty"
    for name in layered0:
        assert name in ALWAYS_ON_TOOLS, f"non-core leaked: {name}"
    assert "get_scene_info" in layered0
    assert "search_tools" in layered0

    uv_tools = [t.name for t in tools_by_category().get("uv") or []]
    domain = [n for n in uv_tools if n not in ALWAYS_ON_TOOLS and n in catalog]
    assert domain, "expected uv domain tools"
    assert domain[0] not in layered0

    # --- activate pack expands ---
    detail = router.activate_category("uv")
    assert detail.get("ok")
    layered1 = {
        s.name
        for s in resolve_tool_specs(
            ExposureContext.for_agent_turn(mode="agent", vision=True, router=router)
        )
    }
    for n in domain:
        assert n in layered1, f"uv tool not exposed after activate: {n}"

    # --- Ask ∩ layered: write tools stay out even if pack activated ---
    router2 = ToolRouter(exposure=EXPOSURE_LAYERED)
    router2.mode = "ask"
    router2.vision = True
    router2.activate_category("modeling")
    ask_layered = {
        s.name
        for s in resolve_tool_specs(
            ExposureContext.for_agent_turn(mode="ask", vision=True, router=router2)
        )
    }
    create = get_tool("create_primitive")
    assert create is not None
    assert not is_tool_allowed(create, "ask")
    assert "create_primitive" not in ask_layered
    ask_mode_names = {
        t.name for t in filter_mode(filter_availability(all_tools(), True), "ask")
    }
    assert "create_primitive" not in ask_mode_names

    # --- activate_from_skill: allowed-tools ---
    router3 = ToolRouter(exposure=EXPOSURE_LAYERED)
    sample = next(iter(catalog - ALWAYS_ON_TOOLS), None)
    assert sample
    r = router3.activate_from_skill(
        {"name": "demo-skill", "allowed_tools": sample, "metadata": {}}
    )
    assert r.get("activated_via") == "allowed-tools"
    assert sample in router3.active_names

    # --- activate_from_skill: metadata.category ---
    router4 = ToolRouter(exposure=EXPOSURE_LAYERED)
    r4 = router4.activate_from_skill(
        {
            "name": "uv-skill",
            "allowed_tools": "",
            "metadata": {"category": "uv"},
        }
    )
    assert r4.get("activated_via") == "metadata.category"
    assert "uv" in router4.active_categories

    # --- activate_from_skill: metadata.categories ---
    router4b = ToolRouter(exposure=EXPOSURE_LAYERED)
    r4b = router4b.activate_from_skill(
        {
            "name": "rig-skill",
            "allowed_tools": "",
            "metadata": {"categories": "rigging,animation"},
        }
    )
    assert r4b.get("activated_via") == "metadata.categories"
    assert "rigging" in router4b.active_categories
    assert "animation" in router4b.active_categories

    # --- no declaration ---
    router5 = ToolRouter(exposure=EXPOSURE_LAYERED)
    r5 = router5.activate_from_skill(
        {"name": "docs-only", "allowed_tools": "", "metadata": {}}
    )
    assert r5.get("activated_via") is None

    assert "generate_chart" not in ALWAYS_ON_TOOLS

    print("OK test_tool_exposure_unit")


if __name__ == "__main__":
    main()
