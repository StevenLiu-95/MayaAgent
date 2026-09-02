"""Maya undo helpers — group one Agent turn into a single undo step."""

from __future__ import annotations

from typing import Any, Dict

from maya_agent.utils.logger import get_logger
from maya_agent.utils.maya_compat import in_maya, run_on_main_thread

log = get_logger("maya_agent.undo")

TURN_CHUNK = "MayaAgentTurn"


class UndoTurnManager:
    """
    Wraps all tool edits in one user message into a single Maya undo chunk.
    UI can then call undo_last() once to roll back the whole Agent turn.
    """

    def __init__(self) -> None:
        self._open = False
        self._can_undo = False
        self._turns_done = 0

    @property
    def can_undo(self) -> bool:
        return self._can_undo and in_maya()

    @property
    def is_open(self) -> bool:
        return self._open

    def begin_turn(self) -> None:
        if not in_maya():
            return

        def _do() -> None:
            import maya.cmds as cmds

            if self._open:
                return
            try:
                cmds.undoInfo(state=True)
            except Exception:
                pass
            try:
                cmds.undoInfo(openChunk=True, chunkName=TURN_CHUNK)
                self._open = True
                log.debug("undo turn chunk opened")
            except Exception as e:
                log.warning("openChunk failed: %s", e)
                self._open = False

        run_on_main_thread(_do)

    def end_turn(self, *, had_edits: bool = True) -> None:
        if not in_maya():
            self._open = False
            return

        def _do() -> None:
            import maya.cmds as cmds

            if not self._open:
                return
            try:
                cmds.undoInfo(closeChunk=True)
                if had_edits:
                    self._can_undo = True
                    self._turns_done += 1
                log.debug("undo turn chunk closed (can_undo=%s)", self._can_undo)
            except Exception as e:
                log.warning("closeChunk failed: %s", e)
            finally:
                self._open = False

        run_on_main_thread(_do)

    def cancel_open(self) -> None:
        """Close an open chunk without dropping undo availability."""
        if not self._open:
            return
        self.end_turn(had_edits=True)

    def undo_last(self) -> Dict[str, Any]:
        """Undo the last Agent turn (one Maya undo step for the turn chunk)."""
        if not in_maya():
            return {"ok": False, "error": "未在 Maya 中运行"}

        def _do() -> Dict[str, Any]:
            import maya.cmds as cmds

            try:
                if not cmds.undoInfo(query=True, state=True):
                    return {"ok": False, "error": "Maya Undo 已关闭，请在首选项中开启"}
            except Exception as e:
                return {"ok": False, "error": str(e)}

            undone = 0
            try:
                for _ in range(24):
                    try:
                        next_name = cmds.undoInfo(query=True, undoName=True) or ""
                    except Exception:
                        next_name = ""
                    if not next_name:
                        break
                    cmds.undo()
                    undone += 1
                    if (
                        next_name == TURN_CHUNK
                        or next_name.startswith("MayaAgent_")
                        or next_name.startswith("MayaAgent")
                    ):
                        break
                    if "MayaAgent" not in next_name:
                        break
            except RuntimeError as e:
                if undone == 0:
                    self._can_undo = False
                    return {"ok": False, "error": f"没有可撤销的操作: {e}"}
            except Exception as e:
                if undone == 0:
                    return {"ok": False, "error": str(e)}

            if undone == 0:
                self._can_undo = False
                return {"ok": False, "error": "没有可撤销的 Agent 操作"}

            self._can_undo = False
            return {
                "ok": True,
                "message": f"已回退 Agent 修改（{undone} 步 Undo）",
                "steps": undone,
            }

        return run_on_main_thread(_do) or {"ok": False, "error": "撤销失败"}
