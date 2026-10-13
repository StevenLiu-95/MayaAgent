"""Shared MayaAgent instance for panel + remote MCP service."""

from __future__ import annotations

import json
import threading
from typing import Any, Callable, Dict, List, Optional

from maya_agent.utils.config import get_config
from maya_agent.utils.logger import get_logger
from maya_agent.utils.maya_compat import in_maya, run_on_main_thread

log = get_logger("maya_agent.bridge.agent")

_agent_lock = threading.RLock()
_panel_agent = None  # MayaAgent | None
_fallback_agent = None  # MayaAgent | None
_skip_confirm_bridge_turn = False


def agent_lock() -> threading.RLock:
    return _agent_lock


def force_reset_agent_lock() -> None:
    """
    Replace the shared lock after a hard-killed panel Worker.

    QThread.terminate() skips finally blocks, so a held RLock would deadlock
    the MCP service; recreate the lock so subsequent calls can proceed.
    """
    global _agent_lock
    _agent_lock = threading.RLock()
    log.warning("agent lock force-reset (panel worker likely terminated)")


def register_panel_agent(agent) -> None:
    global _panel_agent
    with _agent_lock:
        _panel_agent = agent
        log.debug("panel agent registered")


def unregister_panel_agent(agent=None) -> None:
    global _panel_agent
    with _agent_lock:
        if agent is None or _panel_agent is agent:
            _panel_agent = None
            log.debug("panel agent unregistered")


def get_active_agent():
    """Prefer panel agent when share_panel_agent; else lazy fallback."""
    cfg = get_config()
    share = bool(cfg.get("bridge.share_panel_agent", True))
    with _agent_lock:
        if share and _panel_agent is not None:
            return _panel_agent
        return _ensure_fallback_agent()


def _ensure_fallback_agent():
    global _fallback_agent
    if _fallback_agent is not None:
        return _fallback_agent
    from maya_agent.core.agent import MayaAgent

    _fallback_agent = MayaAgent(confirm_callback=_bridge_confirm_destructive)
    return _fallback_agent


def reset_bridge_confirm_turn() -> None:
    global _skip_confirm_bridge_turn
    _skip_confirm_bridge_turn = False


def _bridge_confirm_destructive(name: str, args: Dict[str, Any]) -> bool:
    """Confirm destructive tools for bridge / fallback agent path."""
    global _skip_confirm_bridge_turn
    cfg = get_config()
    mode = str(cfg.get("bridge.confirm_mode", "maya_dialog") or "maya_dialog").lower()
    if mode in ("allow", "auto", "skip"):
        return True
    if _skip_confirm_bridge_turn:
        return True
    if not in_maya():
        return False

    def _ask() -> bool:
        global _skip_confirm_bridge_turn
        # Prefer Qt dialog when available (richer); fall back to cmds.confirmDialog
        try:
            return _qt_confirm(name, args)
        except Exception:
            pass
        try:
            import maya.cmds as cmds

            args_text = json.dumps(args, ensure_ascii=False)
            if len(args_text) > 400:
                args_text = args_text[:400] + "…"
            result = cmds.confirmDialog(
                title="Maya Agent — MCP",
                message=f"MCP 请求执行危险工具：{name}\n\n{args_text}",
                button=["允许一次", "允许本轮", "取消"],
                defaultButton="允许一次",
                cancelButton="取消",
                dismissString="取消",
            )
            if result == "允许本轮":
                _skip_confirm_bridge_turn = True
                return True
            return result == "允许一次"
        except Exception as e:
            log.warning("bridge confirm failed: %s", e)
            return False

    return bool(run_on_main_thread(_ask))


def _qt_confirm(name: str, args: Dict[str, Any]) -> bool:
    global _skip_confirm_bridge_turn
    from maya_agent.i18n import t
    from maya_agent.utils.maya_compat import get_maya_main_window, import_qt

    QtCore, QtGui, QtWidgets, _ = import_qt()
    parent = get_maya_main_window()
    args_text = json.dumps(args, ensure_ascii=False, indent=2)
    if len(args_text) > 600:
        args_text = args_text[:600] + "\n…"

    box = QtWidgets.QMessageBox(parent)
    box.setWindowTitle(t("confirm.title"))
    box.setIcon(QtWidgets.QMessageBox.Question)
    box.setText(t("confirm.body", name=name))
    box.setInformativeText(t("confirm.args", args=args_text))
    btn_once = box.addButton(
        t("confirm.allow_once"), QtWidgets.QMessageBox.AcceptRole
    )
    btn_turn = box.addButton(
        t("confirm.allow_turn"), QtWidgets.QMessageBox.ActionRole
    )
    btn_no = box.addButton(t("confirm.cancel"), QtWidgets.QMessageBox.RejectRole)
    box.setDefaultButton(btn_once)
    box.exec_()
    clicked = box.clickedButton()
    if clicked is btn_turn:
        _skip_confirm_bridge_turn = True
        return True
    if clicked is btn_once:
        return True
    return False


def make_tool_confirm_callback() -> Callable[[str, Dict[str, Any]], bool]:
    """Confirm callback for ToolExecutor used by direct tool calls."""
    return _bridge_confirm_destructive


def run_agent_chat(
    text: str,
    *,
    images: Optional[List[Any]] = None,
    stream: bool = False,
) -> Dict[str, Any]:
    """
    Run full MayaAgent.chat loop under the shared lock.
    Returns {ok, events, final, error}.
    """
    cfg = get_config()
    timeout = float(cfg.get("bridge.agent_timeout", 0) or 0)
    if timeout <= 0:
        llm_t = float(cfg.get("llm.timeout", 120) or 120)
        rounds = int(cfg.get("maya.max_tool_rounds", 30) or 30)
        timeout = max(120.0, llm_t * min(rounds, 10))

    reset_bridge_confirm_turn()
    acquired = _agent_lock.acquire(timeout=timeout)
    if not acquired:
        return {
            "ok": False,
            "error": "agent busy (panel or another IDE chat in progress)",
            "events": [],
            "final": "",
        }
    try:
        agent = get_active_agent()
        # Ensure bridge confirm is used when this is the fallback agent;
        # panel agent keeps its own confirm callback.
        events: List[Dict[str, Any]] = []
        final = ""
        for event in agent.chat(text or "", stream=bool(stream), images=images):
            if isinstance(event, dict):
                events.append(event)
                et = event.get("type")
                if et in ("done", "error", "stopped"):
                    final = str(event.get("content") or event.get("stop_notice") or "")
        ok = not any(e.get("type") == "error" for e in events)
        return {"ok": ok, "events": events, "final": final, "error": "" if ok else final}
    except Exception as e:
        log.exception("remote agent chat failed")
        return {"ok": False, "error": str(e), "events": [], "final": ""}
    finally:
        reset_bridge_confirm_turn()
        _agent_lock.release()


def run_agent_undo() -> Dict[str, Any]:
    acquired = _agent_lock.acquire(timeout=30)
    if not acquired:
        return {"ok": False, "error": "agent busy"}
    try:
        agent = get_active_agent()
        return agent.undo_last_turn()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        _agent_lock.release()
