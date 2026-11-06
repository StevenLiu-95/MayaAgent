"""Agent orchestration — LLM + tools loop."""

from __future__ import annotations

import contextvars
import queue
import threading
from typing import Any, Callable, Dict, Generator, List, Optional

from maya_agent.core.agent_mode import (
    MODE_AGENT,
    MODE_ASK,
    MODE_PLAN_EXECUTING,
    MODE_PLAN_PLANNING,
    normalize_mode,
    ui_mode_from_internal,
)
from maya_agent.core.executor import ToolExecutor
from maya_agent.core.loop_guards import TurnLoopGuard
from maya_agent.core.memory import ConversationMemory
from maya_agent.core.plan_context import set_plan_store_fallback
from maya_agent.core.plan_store import PlanStore
from maya_agent.core.tool_progress import (
    push_cancel_checker,
    push_progress_emitter,
    reset_cancel_checker,
    reset_progress_emitter,
)
from maya_agent.core.undo import UndoTurnManager
from maya_agent.llm.base import (
    ChatMessage,
    ChatResponse,
    ImageAttachment,
    StreamChunk,
    ToolCall,
    describe_finish_reason,
    merge_usage,
    stop_notice_for_reason,
)
from maya_agent.llm.image_codec import MAX_IMAGES
from maya_agent.llm.registry import create_provider
from maya_agent.tools.registry import ToolResult, ensure_tools_loaded, tool_specs
from maya_agent.utils.config import get_config
from maya_agent.utils.logger import get_logger
from maya_agent.utils.maya_compat import in_maya

log = get_logger("maya_agent.agent")

_VISION_INJECT_PROMPT = (
    "[系统] 以下为工具刚截取的场景视口图像，请据此进行视觉分析，"
    "并继续完成用户任务（可再截图或调用其他工具）。"
)

class MayaAgent:
    def __init__(
        self,
        provider_id: Optional[str] = None,
        model: Optional[str] = None,
        confirm_callback: Optional[Callable[[str, Dict[str, Any]], bool]] = None,
        on_tool_start: Optional[Callable[[str, str], None]] = None,
        on_tool_end: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        ensure_tools_loaded()
        cfg = get_config()
        self.provider_id = provider_id or cfg.get("llm.active_provider")
        self.model = model
        self.memory = ConversationMemory(limit=int(cfg.get("agent.history_limit", 40)))
        self.undo = UndoTurnManager()
        self.plans = PlanStore()
        default_mode = normalize_mode(cfg.get("agent.default_mode", MODE_AGENT))
        self.mode = default_mode
        self._active_mode = default_mode
        self.executor = ToolExecutor(
            confirm_callback=confirm_callback,
            turn_undo_active=lambda: self.undo.is_open,
            mode_provider=lambda: self._active_mode,
        )
        self.on_tool_start = on_tool_start
        self.on_tool_end = on_tool_end
        self._cancel_event = threading.Event()
        set_plan_store_fallback(self.plans)
        self._ensure_system_prompt()

    def request_cancel(self) -> None:
        """Ask the running chat loop to stop at the next safe checkpoint."""
        self._cancel_event.set()

    def clear_cancel(self) -> None:
        self._cancel_event.clear()

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def set_mode(self, mode: Optional[str]) -> str:
        """Set persistent agent mode (agent/ask/plan). Returns normalized internal mode."""
        self.mode = normalize_mode(mode)
        self._active_mode = self.mode
        self._ensure_system_prompt()
        return self.mode

    def get_ui_mode(self) -> str:
        return ui_mode_from_internal(self.mode)

    def _ensure_system_prompt(self, mode: Optional[str] = None) -> None:
        from maya_agent.core.system_prompt import build_system_prompt

        use_mode = normalize_mode(mode if mode is not None else self._active_mode)
        full = build_system_prompt(mode=use_mode)
        for i, m in enumerate(self.memory.messages):
            if m.role == "system":
                # Refresh when Meshy availability / tool count / mode changes
                if m.content != full:
                    self.memory.messages[i] = ChatMessage(role="system", content=full)
                return
        self.memory.add(ChatMessage(role="system", content=full))

    def reset(self) -> None:
        self.memory.clear()
        self.plans.clear()
        self._ensure_system_prompt()

    def load_session_memory(self, serialized: List[Dict[str, Any]]) -> None:
        """Restore conversation from persisted session data."""
        self.memory.load_from_serializable(serialized)
        conv = [m for m in self.memory.messages if m.role != "system"]
        self.memory.clear()
        self._ensure_system_prompt()
        if conv:
            self.memory.extend(conv)

    def export_session_memory(self) -> List[Dict[str, Any]]:
        return self.memory.to_serializable()

    def load_pending_plan(self, data: Optional[Dict[str, Any]]) -> None:
        self.plans.load(data)

    def export_pending_plan(self) -> Optional[Dict[str, Any]]:
        return self.plans.export()

    def set_provider(self, provider_id: str, model: Optional[str] = None) -> None:
        self.provider_id = provider_id
        if model:
            self.model = model
        cfg = get_config()
        cfg.set("llm.active_provider", provider_id)
        if model:
            cfg.set(f"providers.{provider_id}.default_model", model)

    def undo_last_turn(self) -> Dict[str, Any]:
        return self.undo.undo_last()

    def approve_pending_plan(self) -> Optional[Dict[str, Any]]:
        plan = self.plans.mark_approved()
        return plan.to_dict() if plan else None

    def reject_pending_plan(self) -> None:
        self.plans.mark_rejected()

    def chat(
        self,
        user_text: str,
        stream: bool = False,
        images: Optional[List[Any]] = None,
        mode: Optional[str] = None,
    ) -> Generator[Dict[str, Any], None, str]:
        """
        Yields event dicts:
          {"type":"text","content":"..."}
          {"type":"thinking","content":"..."}
          {"type":"tool_start","name":"...","arguments":"..."}
          {"type":"tool_progress","name":"...","progress":0-100,"status":"...","message":"..."}
          {"type":"tool_end","name":"...","result":"...","images":[...optional...]}
          {"type":"plan_proposed","plan":{...}}
          {"type":"plan_updated","plan":{...}}
          {"type":"vision_context","count":N}
          {"type":"chat_images_staged","count":N,"paths":[...]}
          {"type":"error","content":"...","stop_notice":"..."}
          {"type":"done","content":"...","model":"...","usage":{...},"stop_notice":"..."}
          {"type":"stopped","reason":"...","stop_notice":"..."}
          {"type":"undo_ready","can_undo": bool}
        Returns final assistant text.
        """
        self.clear_cancel()
        turn_mode = normalize_mode(mode if mode is not None else self.mode)
        self._active_mode = turn_mode
        # Persist UI-facing mode (plan_executing still shows as Plan).
        if turn_mode == MODE_PLAN_EXECUTING:
            self.mode = MODE_PLAN_PLANNING  # stay on Plan in UI after execute
        else:
            self.mode = turn_mode
        set_plan_store_fallback(self.plans)

        attached = [img for img in (images or []) if getattr(img, "data_b64", "")]
        text = (user_text or "").strip()
        if attached and not text:
            text = "请查看附图。"
        if turn_mode == MODE_PLAN_EXECUTING and self.plans.plan:
            # Ensure approved + inject plan summary once if user text is the approve cue.
            if self.plans.plan.status in ("pending", "approved"):
                self.plans.mark_approved()
            summary = self.plans.plan.summary_for_prompt()
            if summary and summary not in text:
                text = f"{text}\n\n{summary}" if text else summary
        self._ensure_system_prompt(turn_mode)
        self.memory.add(
            ChatMessage(role="user", content=text, images=attached or None)
        )
        staged_chat_images: List[Dict[str, Any]] = []
        if attached:
            try:
                from maya_agent.tools.fsutil import stage_chat_images

                staged_chat_images = stage_chat_images(attached)
            except Exception:
                log.exception("stage chat images failed")
        if staged_chat_images:
            yield {
                "type": "chat_images_staged",
                "count": len(staged_chat_images),
                "paths": [x.get("path") for x in staged_chat_images if x.get("path")],
            }
        cfg = get_config()
        max_rounds = int(cfg.get("maya.max_tool_rounds", 30))
        use_stream = stream and cfg.get("agent.stream", True)
        auto_undo = bool(cfg.get("maya.auto_undo", True)) and in_maya()
        # Ask / Plan planning should not open undo chunks (read-only tools).
        if turn_mode in (MODE_ASK, MODE_PLAN_PLANNING):
            auto_undo = False
        final_text = ""
        turn_opened = False
        had_tools = False
        turn_usage: Dict[str, int] = {}
        llm_calls = 0
        loop_guard = TurnLoopGuard.from_config(cfg)

        try:
            provider = create_provider(self.provider_id, model=self.model)
        except Exception as e:
            yield {"type": "error", "content": str(e)}
            return str(e)

        model_name = getattr(provider, "model", "") or self.model or ""
        vision_ok = bool(getattr(provider, "supports_vision", False))
        tools = (
            tool_specs(vision=vision_ok, mode=turn_mode)
            if provider.supports_tools
            else None
        )

        def _close_undo_turn():
            nonlocal turn_opened
            if not turn_opened:
                return None
            self.undo.end_turn(had_edits=had_tools)
            turn_opened = False
            return {
                "type": "undo_ready",
                "can_undo": bool(self.undo.can_undo),
            }

        def _emit_cancelled(partial: str = "") -> Dict[str, Any]:
            nonlocal turn_opened
            try:
                self.undo.cancel_open()
            except Exception:
                pass
            turn_opened = False
            try:
                self.memory.drop_incomplete_tool_round()
            except Exception:
                pass
            notice = stop_notice_for_reason("user_cancel")
            return {
                "type": "stopped",
                "reason": "user_cancel",
                "content": partial or "",
                "stop_notice": notice,
                "model": model_name,
                "usage": dict(turn_usage),
                "llm_calls": llm_calls,
            }

        try:
            for _ in range(max_rounds):
                if self.is_cancelled():
                    stopped = _emit_cancelled(final_text)
                    yield stopped
                    return stopped.get("stop_notice") or ""
                try:
                    if use_stream:
                        gen = provider.chat(self.memory.as_list(), tools=tools, stream=True)
                        text_parts: List[str] = []
                        thinking_parts: List[str] = []
                        resp: Optional[ChatResponse] = None
                        try:
                            while True:
                                if self.is_cancelled():
                                    try:
                                        gen.close()
                                    except Exception:
                                        pass
                                    partial = "".join(text_parts)
                                    stopped = _emit_cancelled(partial)
                                    yield stopped
                                    return stopped.get("stop_notice") or ""
                                piece = next(gen)
                                if isinstance(piece, str):
                                    piece = StreamChunk(text=piece)
                                if not isinstance(piece, StreamChunk):
                                    continue
                                if piece.thinking:
                                    thinking_parts.append(piece.thinking)
                                    yield {
                                        "type": "thinking",
                                        "content": piece.thinking,
                                    }
                                if piece.text:
                                    text_parts.append(piece.text)
                                    yield {"type": "text", "content": piece.text}
                        except StopIteration as stop:
                            resp = stop.value
                        if resp is None:
                            resp = ChatResponse(
                                content="".join(text_parts),
                                thinking="".join(thinking_parts),
                            )
                        if not resp.content and text_parts:
                            resp.content = "".join(text_parts)
                        if not resp.thinking and thinking_parts:
                            resp.thinking = "".join(thinking_parts)
                    else:
                        resp = provider.chat(
                            self.memory.as_list(), tools=tools, stream=False
                        )
                        assert isinstance(resp, ChatResponse)
                        if resp.thinking:
                            yield {
                                "type": "thinking",
                                "content": resp.thinking,
                            }
                        if resp.content:
                            yield {"type": "text", "content": resp.content}
                except Exception as e:
                    log.exception("LLM error")
                    evt = _close_undo_turn()
                    if evt:
                        yield evt
                    err_text = str(e).strip() or repr(e)
                    # Friendly formatter already returns full Chinese guidance
                    if err_text.startswith(("LLM ", "Anthropic ", "Gemini ", "Cursor ")):
                        content = err_text
                    else:
                        content = f"LLM 调用失败：{err_text}"
                    notice = stop_notice_for_reason("llm_error")
                    if "Max Tokens" in err_text or "max_tokens" in err_text.lower():
                        notice = "已停止：Max Tokens 等请求参数不符合当前模型限制，请按下方说明调整设置。"
                    yield {
                        "type": "error",
                        "content": content,
                        "stop_notice": notice,
                    }
                    return str(e)

                if resp.usage:
                    merge_usage(turn_usage, resp.usage)
                llm_calls += 1

                if resp.tool_calls:
                    if self.is_cancelled():
                        stopped = _emit_cancelled(resp.content or "")
                        yield stopped
                        return stopped.get("stop_notice") or ""
                    if auto_undo and not turn_opened:
                        self.undo.begin_turn()
                        turn_opened = True
                    had_tools = True
                    tc_payload = []
                    for idx, tc in enumerate(resp.tool_calls):
                        call_id = tc.id or f"call_{idx}"
                        tc.id = call_id
                        tc_payload.append(
                            {
                                "id": call_id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": tc.arguments or "{}",
                                },
                            }
                        )
                    self.memory.add(
                        ChatMessage(
                            role="assistant",
                            content=resp.content or "",
                            tool_calls=tc_payload,
                        )
                    )
                    vision_batch: List[ImageAttachment] = []
                    for tc in resp.tool_calls:
                        if self.is_cancelled():
                            stopped = _emit_cancelled(resp.content or "")
                            yield stopped
                            return stopped.get("stop_notice") or ""
                        decision = loop_guard.evaluate(
                            tc.name or "", tc.arguments or "{}"
                        )
                        if decision.skip_execute and decision.result is not None:
                            yield from self._emit_synthetic_tool(
                                tc, decision.result
                            )
                            continue
                        yield from self._run_one_tool(
                            tc,
                            vision_ok=vision_ok,
                            vision_batch=vision_batch,
                            loop_guard=loop_guard,
                        )
                    if self.is_cancelled():
                        stopped = _emit_cancelled(resp.content or "")
                        yield stopped
                        return stopped.get("stop_notice") or ""
                    if vision_batch and vision_ok:
                        clipped = vision_batch[:MAX_IMAGES]
                        self.memory.add(
                            ChatMessage(
                                role="user",
                                content=_VISION_INJECT_PROMPT,
                                images=clipped,
                            )
                        )
                        yield {
                            "type": "vision_context",
                            "count": len(clipped),
                        }
                    continue

                final_text = resp.content or ""
                self.memory.add(ChatMessage(role="assistant", content=final_text))
                stop_notice = describe_finish_reason(resp.finish_reason) or ""
                yield {
                    "type": "done",
                    "content": final_text,
                    "model": model_name,
                    "usage": dict(turn_usage),
                    "llm_calls": llm_calls,
                    "finish_reason": resp.finish_reason or "",
                    "stop_notice": stop_notice,
                }
                evt = _close_undo_turn()
                if evt:
                    yield evt
                return final_text

            msg = stop_notice_for_reason("max_tool_rounds")
            evt = _close_undo_turn()
            if evt:
                yield evt
            yield {
                "type": "stopped",
                "reason": "max_tool_rounds",
                "content": "",
                "stop_notice": msg,
                "model": model_name,
                "usage": dict(turn_usage),
                "llm_calls": llm_calls,
            }
            return msg
        except Exception as e:
            if turn_opened:
                self.undo.end_turn(had_edits=had_tools)
                turn_opened = False
            # Re-raise after closing undo; outer UI maps unexpected errors.
            # Also surface a stopped tip when this is an LLM-path failure already handled above.
            raise
        finally:
            # Safety: never leave an open Maya undo chunk behind
            if turn_opened:
                self.undo.end_turn(had_edits=had_tools)

    def _emit_synthetic_tool(
        self, tc: ToolCall, result: ToolResult
    ) -> Generator[Dict[str, Any], None, None]:
        """Emit tool_start/tool_end for guard short-circuits (dedup / fuse)."""
        if self.on_tool_start:
            self.on_tool_start(tc.name, tc.arguments)
        yield {"type": "tool_start", "name": tc.name, "arguments": tc.arguments}
        text = result.to_str()
        # Prefer full cached payload for dedup so the model still sees data.
        if (
            result.ok
            and isinstance(result.data, dict)
            and result.data.get("deduplicated")
            and result.data.get("cached_result")
        ):
            text = str(result.data.get("cached_result") or text)
        if self.on_tool_end:
            self.on_tool_end(tc.name, text)
        yield {"type": "tool_end", "name": tc.name, "result": text}
        self.memory.add(
            ChatMessage(
                role="tool",
                content=text,
                name=tc.name,
                tool_call_id=tc.id,
            )
        )

    def _run_one_tool(
        self,
        tc: ToolCall,
        *,
        vision_ok: bool = False,
        vision_batch: Optional[List[ImageAttachment]] = None,
        loop_guard: Optional[TurnLoopGuard] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        if self.on_tool_start:
            self.on_tool_start(tc.name, tc.arguments)
        yield {"type": "tool_start", "name": tc.name, "arguments": tc.arguments}

        # Run the handler on a side thread so progress events can be yielded
        # while long polls (e.g. Meshy wait) are in flight.
        progress_q: queue.Queue = queue.Queue()
        box: Dict[str, Any] = {"result": None, "error": None}

        def _emit_progress(event: Dict[str, Any]) -> None:
            if not isinstance(event, dict):
                return
            payload = dict(event)
            payload.setdefault("type", "tool_progress")
            payload.setdefault("name", tc.name)
            progress_q.put(payload)

        token = push_progress_emitter(_emit_progress)
        # Lets long cloud-3D polls / downloads abort promptly on Stop.
        cancel_token = push_cancel_checker(self.is_cancelled)

        def _execute() -> None:
            try:
                box["result"] = self.executor.execute(tc.name, tc.arguments)
            except BaseException as exc:
                box["error"] = exc
            finally:
                progress_q.put(None)

        ctx = contextvars.copy_context()
        thread = threading.Thread(
            target=ctx.run,
            args=(_execute,),
            name=f"maya_agent_tool:{tc.name}",
            daemon=True,
        )
        thread.start()
        try:
            while True:
                if self.is_cancelled() and not thread.is_alive():
                    break
                try:
                    item = progress_q.get(timeout=0.2)
                except queue.Empty:
                    if self.is_cancelled() and not thread.is_alive():
                        break
                    continue
                if item is None:
                    break
                yield item
        finally:
            thread.join(timeout=30.0)
            reset_progress_emitter(token)
            reset_cancel_checker(cancel_token)
        if self.is_cancelled():
            return

        if box["error"] is not None:
            raise box["error"]
        result = box["result"]
        result = self._apply_vision_gate(result, vision_ok=vision_ok)
        text = result.to_str()
        image_dicts = []
        for img in result.images or []:
            if getattr(img, "data_b64", ""):
                image_dicts.append(img.to_dict())
                if vision_batch is not None and vision_ok:
                    vision_batch.append(img)
        if self.on_tool_end:
            self.on_tool_end(tc.name, text)
        evt: Dict[str, Any] = {
            "type": "tool_end",
            "name": tc.name,
            "result": text,
        }
        if image_dicts:
            evt["images"] = image_dicts
        yield evt
        if result.ok and tc.name == "create_plan":
            plan_data = result.data if isinstance(result.data, dict) else self.plans.export()
            if plan_data:
                yield {"type": "plan_proposed", "plan": plan_data}
        elif result.ok and tc.name == "update_plan_step":
            plan_data = None
            if isinstance(result.data, dict):
                plan_data = result.data.get("plan")
            if not plan_data:
                plan_data = self.plans.export()
            if plan_data:
                yield {"type": "plan_updated", "plan": plan_data}
        if loop_guard is not None and result.ok:
            try:
                loop_guard.remember_success(
                    tc.name or "", tc.arguments or "{}", text
                )
            except Exception:
                pass
        self.memory.add(
            ChatMessage(
                role="tool",
                content=text,
                name=tc.name,
                tool_call_id=tc.id,
            )
        )

    @staticmethod
    def _apply_vision_gate(result: ToolResult, *, vision_ok: bool) -> ToolResult:
        """Drop or reject image-bearing results when the model cannot see them."""
        imgs = [img for img in (result.images or []) if getattr(img, "data_b64", "")]
        if not imgs:
            return result
        if vision_ok:
            result.images = imgs
            return result
        return ToolResult(
            ok=False,
            error=(
                "当前模型不支持视觉分析，无法使用视口截图。"
                "请在设置中切换到支持看图的模型（如 gpt-4o、Claude、Gemini，"
                "或名称含 vision / vl 的模型），或将「图片输入」设为开启。"
            ),
            data=result.data,
        )

    def chat_sync(
        self,
        user_text: str,
        images: Optional[List[Any]] = None,
        mode: Optional[str] = None,
    ) -> str:
        final = ""
        for event in self.chat(user_text, stream=False, images=images, mode=mode):
            if event["type"] in ("done", "error"):
                final = event.get("content", "")
        return final
