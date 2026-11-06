"""Bind PlanStore to the current agent turn (contextvar + fallback)."""

from __future__ import annotations

import contextvars
from typing import Optional

from maya_agent.core.plan_store import PlanStore

_store_var: contextvars.ContextVar[Optional[PlanStore]] = contextvars.ContextVar(
    "maya_agent_plan_store", default=None
)
# Fallback when tools run off the context that set the var (side threads).
_fallback_store: Optional[PlanStore] = None


def set_plan_store_fallback(store: Optional[PlanStore]) -> None:
    global _fallback_store
    _fallback_store = store


def push_plan_store(store: Optional[PlanStore]):
    return _store_var.set(store)


def reset_plan_store(token) -> None:
    _store_var.reset(token)


def get_plan_store() -> Optional[PlanStore]:
    store = _store_var.get()
    if store is not None:
        return store
    return _fallback_store
