"""Plan mode tools: create_plan / update_plan_step."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from maya_agent.core.plan_context import get_plan_store
from maya_agent.tools.registry import ToolResult, tool


@tool(
    name="create_plan",
    description=(
        "提交结构化执行计划供用户批准。仅在 Plan 规划阶段可用。"
        "调用后应停止修改场景，等待用户在界面点击「批准执行」。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "计划标题",
            },
            "overview": {
                "type": "string",
                "description": "简要概述目标与前提",
            },
            "steps": {
                "type": "array",
                "description": "有序步骤列表；元素为字符串或 {id,title,detail} 对象",
                "items": {
                    "oneOf": [
                        {"type": "string"},
                        {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "title": {"type": "string"},
                                "detail": {"type": "string"},
                            },
                        },
                    ]
                },
            },
        },
        "required": ["title", "steps"],
    },
    category="plan",
    destructive=False,
    main_thread=False,
)
def create_plan(
    title: str = "",
    overview: str = "",
    steps: Optional[List[Any]] = None,
) -> ToolResult:
    store = get_plan_store()
    if store is None:
        return ToolResult(ok=False, error="Plan 存储未绑定（内部错误）")
    try:
        plan = store.create_from_args(
            title=title or "",
            overview=overview or "",
            steps=list(steps or []),
        )
    except Exception as e:
        return ToolResult(ok=False, error=str(e))
    return ToolResult(
        ok=True,
        message=f"计划已提交，等待用户批准：{plan.title}（{len(plan.steps)} 步）",
        data=plan.to_dict(),
    )


@tool(
    name="update_plan_step",
    description=(
        "更新已批准计划中某一步的状态。仅在 Plan 执行阶段可用。"
        "status: pending | in_progress | done | skipped"
    ),
    parameters={
        "type": "object",
        "properties": {
            "step_id": {
                "type": "string",
                "description": "步骤 id，或 1-based 序号字符串",
            },
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "done", "skipped"],
                "description": "新状态",
            },
            "title": {"type": "string", "description": "可选：改写步骤标题"},
            "detail": {"type": "string", "description": "可选：补充说明"},
        },
        "required": ["step_id", "status"],
    },
    category="plan",
    destructive=False,
    main_thread=False,
)
def update_plan_step(
    step_id: str = "",
    status: str = "in_progress",
    title: Optional[str] = None,
    detail: Optional[str] = None,
) -> ToolResult:
    store = get_plan_store()
    if store is None:
        return ToolResult(ok=False, error="Plan 存储未绑定（内部错误）")
    try:
        step = store.update_step(
            str(step_id),
            status=status,
            title=title,
            detail=detail,
        )
    except Exception as e:
        return ToolResult(ok=False, error=str(e))
    plan = store.plan
    return ToolResult(
        ok=True,
        message=f"步骤 {step.id} → {step.status}",
        data={
            "step": step.to_dict(),
            "plan_status": plan.status if plan else "",
            "plan": plan.to_dict() if plan else None,
        },
    )
