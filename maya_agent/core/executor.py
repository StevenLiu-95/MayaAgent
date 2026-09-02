"""Tool executor with undo chunks and safety checks."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional

from maya_agent.tools.registry import ToolResult, get_tool, run_tool
from maya_agent.utils.config import get_config
from maya_agent.utils.logger import get_logger
from maya_agent.utils.maya_compat import in_maya, run_on_main_thread

log = get_logger("maya_agent.executor")


class ToolExecutor:
    def __init__(
        self,
        confirm_callback: Optional[Callable[[str, Dict[str, Any]], bool]] = None,
        turn_undo_active: Optional[Callable[[], bool]] = None,
    ) -> None:
        self.confirm_callback = confirm_callback
        # When a turn-level undo chunk is already open, skip per-tool chunks
        # so the whole Agent reply collapses into one Ctrl+Z / 撤销.
        self.turn_undo_active = turn_undo_active

    def execute(self, name: str, arguments_json: str) -> ToolResult:
        try:
            args = json.loads(arguments_json) if arguments_json else {}
            if not isinstance(args, dict):
                return ToolResult(ok=False, error="工具参数必须是 JSON 对象")
        except json.JSONDecodeError as e:
            return ToolResult(ok=False, error=f"JSON 解析失败: {e}")

        reg = get_tool(name)
        if not reg:
            return ToolResult(ok=False, error=f"未知工具: {name}")

        cfg = get_config()

        def _do() -> ToolResult:
            if reg.destructive and cfg.get("maya.confirm_destructive", True):
                if self.confirm_callback and not self.confirm_callback(name, args):
                    return ToolResult(ok=False, error="用户取消了危险操作")
            use_undo = in_maya() and cfg.get("maya.auto_undo", True)
            turn_open = bool(self.turn_undo_active and self.turn_undo_active())
            if use_undo and not turn_open:
                return self._with_undo(name, args)
            return run_tool(name, args)

        return run_on_main_thread(_do)

    def _with_undo(self, name: str, args: Dict[str, Any]) -> ToolResult:
        import maya.cmds as cmds

        chunk = f"MayaAgent_{name}"
        try:
            cmds.undoInfo(state=True)
            cmds.undoInfo(openChunk=True, chunkName=chunk)
            return run_tool(name, args)
        finally:
            try:
                cmds.undoInfo(closeChunk=True)
            except Exception:
                pass
