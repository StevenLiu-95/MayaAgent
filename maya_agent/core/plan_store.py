"""Lightweight execution plan store for Plan mode."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

STEP_PENDING = "pending"
STEP_IN_PROGRESS = "in_progress"
STEP_DONE = "done"
STEP_SKIPPED = "skipped"

_VALID_STATUS = frozenset(
    {STEP_PENDING, STEP_IN_PROGRESS, STEP_DONE, STEP_SKIPPED}
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(n: int = 8) -> str:
    return uuid.uuid4().hex[:n]


@dataclass
class PlanStep:
    id: str
    title: str
    status: str = STEP_PENDING
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlanStep":
        status = str(data.get("status") or STEP_PENDING)
        if status not in _VALID_STATUS:
            status = STEP_PENDING
        return cls(
            id=str(data.get("id") or _new_id()),
            title=str(data.get("title") or ""),
            status=status,
            detail=str(data.get("detail") or ""),
        )


@dataclass
class Plan:
    id: str
    title: str
    overview: str = ""
    steps: List[PlanStep] = field(default_factory=list)
    status: str = "pending"  # pending | approved | rejected | executing | completed
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "overview": self.overview,
            "steps": [s.to_dict() for s in self.steps],
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> Optional["Plan"]:
        if not data or not isinstance(data, dict):
            return None
        steps_raw = data.get("steps") or []
        steps = [
            PlanStep.from_dict(s) if isinstance(s, dict) else PlanStep(id=_new_id(), title=str(s))
            for s in steps_raw
        ]
        return cls(
            id=str(data.get("id") or _new_id()),
            title=str(data.get("title") or "Untitled Plan"),
            overview=str(data.get("overview") or ""),
            steps=steps,
            status=str(data.get("status") or "pending"),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
        )

    def summary_for_prompt(self) -> str:
        lines = [
            f"# 已批准计划：{self.title}",
            f"概述：{self.overview or '（无）'}",
            "步骤：",
        ]
        for i, s in enumerate(self.steps, 1):
            lines.append(f"{i}. [{s.status}] ({s.id}) {s.title}")
            if s.detail:
                lines.append(f"   - {s.detail}")
        lines.append(
            "请按顺序执行，并用 update_plan_step 更新每步状态。"
        )
        return "\n".join(lines)


class PlanStore:
    """Holds the pending / active plan for one MayaAgent instance."""

    def __init__(self) -> None:
        self.plan: Optional[Plan] = None

    def clear(self) -> None:
        self.plan = None

    def load(self, data: Optional[Dict[str, Any]]) -> None:
        self.plan = Plan.from_dict(data)

    def export(self) -> Optional[Dict[str, Any]]:
        return self.plan.to_dict() if self.plan else None

    def create_from_args(
        self,
        *,
        title: str,
        overview: str = "",
        steps: Optional[List[Any]] = None,
    ) -> Plan:
        now = _now_iso()
        parsed: List[PlanStep] = []
        for i, raw in enumerate(steps or []):
            if isinstance(raw, str):
                parsed.append(
                    PlanStep(id=f"s{i+1}", title=raw.strip() or f"步骤 {i+1}")
                )
            elif isinstance(raw, dict):
                sid = str(raw.get("id") or f"s{i+1}")
                title_s = str(raw.get("title") or raw.get("name") or f"步骤 {i+1}")
                detail = str(raw.get("detail") or raw.get("description") or "")
                parsed.append(PlanStep(id=sid, title=title_s, detail=detail))
            else:
                parsed.append(PlanStep(id=f"s{i+1}", title=str(raw)))
        if not parsed:
            parsed.append(PlanStep(id="s1", title="完成用户请求"))
        plan = Plan(
            id=_new_id(),
            title=(title or "").strip() or "执行计划",
            overview=(overview or "").strip(),
            steps=parsed,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        self.plan = plan
        return plan

    def update_step(
        self,
        step_id: str,
        *,
        status: Optional[str] = None,
        title: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> PlanStep:
        if not self.plan:
            raise ValueError("当前没有活动计划")
        step = None
        for s in self.plan.steps:
            if s.id == step_id:
                step = s
                break
        if step is None:
            # Allow 1-based index as string
            try:
                idx = int(step_id) - 1
                if 0 <= idx < len(self.plan.steps):
                    step = self.plan.steps[idx]
            except ValueError:
                pass
        if step is None:
            raise ValueError(f"未找到步骤: {step_id}")
        if status is not None:
            st = str(status).strip().lower()
            if st not in _VALID_STATUS:
                raise ValueError(
                    f"无效状态: {status}（允许: {', '.join(sorted(_VALID_STATUS))}）"
                )
            step.status = st
        if title is not None:
            step.title = str(title)
        if detail is not None:
            step.detail = str(detail)
        self.plan.updated_at = _now_iso()
        if self.plan.status == "approved":
            self.plan.status = "executing"
        if all(s.status in (STEP_DONE, STEP_SKIPPED) for s in self.plan.steps):
            self.plan.status = "completed"
        return step

    def mark_approved(self) -> Optional[Plan]:
        if not self.plan:
            return None
        self.plan.status = "approved"
        self.plan.updated_at = _now_iso()
        return self.plan

    def mark_rejected(self) -> None:
        if self.plan:
            self.plan.status = "rejected"
            self.plan.updated_at = _now_iso()
        self.plan = None
