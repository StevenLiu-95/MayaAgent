"""Thread-safe tool progress reporting during long-running handlers."""

from __future__ import annotations

import contextvars
from typing import Any, Callable, Dict, Optional

ProgressEmitter = Callable[[Dict[str, Any]], None]
CancelChecker = Callable[[], bool]

_emitter: contextvars.ContextVar[Optional[ProgressEmitter]] = contextvars.ContextVar(
    "maya_agent_tool_progress_emitter", default=None
)
_cancel_checker: contextvars.ContextVar[Optional[CancelChecker]] = contextvars.ContextVar(
    "maya_agent_tool_cancel_checker", default=None
)


def push_progress_emitter(cb: Optional[ProgressEmitter]):
    """Install a progress emitter; returns a token for ``reset_progress_emitter``."""
    return _emitter.set(cb)


def reset_progress_emitter(token) -> None:
    _emitter.reset(token)


def push_cancel_checker(cb: Optional[CancelChecker]):
    """Install a cooperative-cancel checker; returns a token for reset."""
    return _cancel_checker.set(cb)


def reset_cancel_checker(token) -> None:
    _cancel_checker.reset(token)


def is_cancel_requested() -> bool:
    """
    True when the current Agent turn has been asked to stop.

    Long-running tools (cloud 3D polling, big downloads) call this between
    steps so a user "Stop" frees the worker thread quickly instead of waiting
    for the full 600 s provider timeout. No-op when called outside an Agent
    turn (e.g. a direct MCP /v1/tools/call).
    """
    cb = _cancel_checker.get()
    if cb is None:
        return False
    try:
        return bool(cb())
    except Exception:
        return False


def report_tool_progress(
    *,
    name: str = "",
    progress: Optional[Any] = None,
    status: str = "",
    message: str = "",
    task_id: str = "",
    kind: str = "",
) -> None:
    """Emit a ``tool_progress`` event if a listener is installed (no-op otherwise)."""
    cb = _emitter.get()
    if cb is None:
        return
    event: Dict[str, Any] = {"type": "tool_progress"}
    if name:
        event["name"] = name
    if progress is not None:
        try:
            event["progress"] = int(progress)
        except (TypeError, ValueError):
            event["progress"] = progress
    if status:
        event["status"] = str(status)
    if message:
        event["message"] = message
    if task_id:
        event["task_id"] = task_id
    if kind:
        event["kind"] = kind
    try:
        cb(event)
    except Exception:
        pass
