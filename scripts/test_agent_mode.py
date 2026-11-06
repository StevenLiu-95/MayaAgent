"""Unit tests for Ask/Plan agent modes (no Maya required)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_normalize_and_ui_mode():
    from maya_agent.core.agent_mode import (
        MODE_AGENT,
        MODE_ASK,
        MODE_PLAN,
        MODE_PLAN_EXECUTING,
        MODE_PLAN_PLANNING,
        normalize_mode,
        ui_mode_from_internal,
    )

    assert normalize_mode("plan") == MODE_PLAN_PLANNING
    assert normalize_mode("ASK") == MODE_ASK
    assert normalize_mode(None) == MODE_AGENT
    assert normalize_mode("nope") == MODE_AGENT
    assert ui_mode_from_internal(MODE_PLAN_EXECUTING) == MODE_PLAN
    assert ui_mode_from_internal(MODE_PLAN_PLANNING) == MODE_PLAN
    assert ui_mode_from_internal(MODE_ASK) == MODE_ASK


def test_ask_allows_readonly_denies_destructive():
    from maya_agent.core.agent_mode import is_tool_allowed
    from maya_agent.tools.registry import RegisteredTool, ToolResult

    def _h(**kw):
        return ToolResult(ok=True)

    get_info = RegisteredTool(
        name="get_scene_info",
        description="x",
        parameters={},
        handler=_h,
        category="scene",
        destructive=False,
    )
    delete = RegisteredTool(
        name="delete_objects",
        description="x",
        parameters={},
        handler=_h,
        category="scene",
        destructive=True,
    )
    create = RegisteredTool(
        name="create_primitive",
        description="x",
        parameters={},
        handler=_h,
        category="modeling",
        destructive=False,
    )
    assert is_tool_allowed(get_info, "ask")
    assert not is_tool_allowed(delete, "ask")
    assert not is_tool_allowed(create, "ask")
    assert is_tool_allowed(create, "agent")
    assert not is_tool_allowed(
        RegisteredTool(
            name="create_plan",
            description="x",
            parameters={},
            handler=_h,
            category="plan",
        ),
        "agent",
    )
    assert is_tool_allowed(
        RegisteredTool(
            name="create_plan",
            description="x",
            parameters={},
            handler=_h,
            category="plan",
        ),
        "plan",
    )
    assert is_tool_allowed(
        RegisteredTool(
            name="update_plan_step",
            description="x",
            parameters={},
            handler=_h,
            category="plan",
        ),
        "plan_executing",
    )
    assert not is_tool_allowed(
        RegisteredTool(
            name="update_plan_step",
            description="x",
            parameters={},
            handler=_h,
            category="plan",
        ),
        "plan",
    )


def test_tool_specs_mode_and_executor_gate():
    from maya_agent.core.executor import ToolExecutor
    from maya_agent.tools.registry import ensure_tools_loaded, get_tool, tool_specs

    ensure_tools_loaded()
    ask_names = {s.name for s in tool_specs(vision=True, mode="ask")}
    agent_names = {s.name for s in tool_specs(vision=True, mode="agent")}
    plan_names = {s.name for s in tool_specs(vision=True, mode="plan")}
    exec_names = {s.name for s in tool_specs(vision=True, mode="plan_executing")}

    assert "get_scene_info" in ask_names
    assert "delete_objects" not in ask_names
    assert "create_primitive" not in ask_names
    assert "create_plan" not in ask_names
    assert "create_plan" not in agent_names
    assert "create_plan" in plan_names
    assert "get_scene_info" in plan_names
    assert "create_primitive" not in plan_names
    assert "update_plan_step" in exec_names
    assert "create_plan" not in exec_names
    assert "create_primitive" in exec_names
    assert "create_primitive" in agent_names

    mode_box = {"mode": "ask"}
    ex = ToolExecutor(mode_provider=lambda: mode_box["mode"])
    denied = ex.execute("delete_objects", "{}")
    assert not denied.ok
    assert "Ask" in (denied.error or "") or "只读" in (denied.error or "")

    # create_plan allowed only in planning
    mode_box["mode"] = "plan_planning"
    assert get_tool("create_plan") is not None
    ok = ex.execute(
        "create_plan",
        json.dumps(
            {
                "title": "T",
                "steps": ["a", "b"],
            },
            ensure_ascii=False,
        ),
    )
    # Plan store may be unbound outside agent — still should pass mode gate
    # (failure would be store bind, not mode deny)
    if not ok.ok:
        assert "不允许" not in (ok.error or "")
        assert "Ask" not in (ok.error or "")


def test_plan_store_roundtrip():
    from maya_agent.core.plan_store import PlanStore

    store = PlanStore()
    plan = store.create_from_args(
        title="绑骨",
        overview="UE5",
        steps=["对齐", {"id": "s2", "title": "蒙皮", "detail": "maxInf=4"}],
    )
    assert plan.id
    assert len(plan.steps) == 2
    data = store.export()
    store2 = PlanStore()
    store2.load(data)
    assert store2.plan is not None
    assert store2.plan.title == "绑骨"
    store2.mark_approved()
    step = store2.update_step("s2", status="done")
    assert step.status == "done"
    assert "已批准计划" in store2.plan.summary_for_prompt()


def main():
    test_normalize_and_ui_mode()
    test_ask_allows_readonly_denies_destructive()
    test_tool_specs_mode_and_executor_gate()
    test_plan_store_roundtrip()
    print("test_agent_mode: OK")


if __name__ == "__main__":
    main()
