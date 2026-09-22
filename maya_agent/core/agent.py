"""Agent orchestration — LLM + tools loop."""

from __future__ import annotations

from typing import Any, Callable, Dict, Generator, List, Optional

from maya_agent.core.executor import ToolExecutor
from maya_agent.core.memory import ConversationMemory
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
from maya_agent.utils.maya_compat import in_maya, maya_version

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
        self.executor = ToolExecutor(
            confirm_callback=confirm_callback,
            turn_undo_active=lambda: self.undo.is_open,
        )
        self.on_tool_start = on_tool_start
        self.on_tool_end = on_tool_end
        self._ensure_system_prompt()

    def _ensure_system_prompt(self) -> None:
        if any(m.role == "system" for m in self.memory.messages):
            return
        prompt = get_config().system_prompt()
        env = (
            f"\n\n## 运行环境\n- Maya: {maya_version() if in_maya() else '未在 Maya 内'}\n"
            f"- 工具数量: {len(tool_specs())}\n"
        )
        self.memory.add(ChatMessage(role="system", content=prompt + env))

    def reset(self) -> None:
        self.memory.clear()
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

    def chat(
        self,
        user_text: str,
        stream: bool = False,
        images: Optional[List[Any]] = None,
    ) -> Generator[Dict[str, Any], None, str]:
        """
        Yields event dicts:
          {"type":"text","content":"..."}
          {"type":"thinking","content":"..."}
          {"type":"tool_start","name":"...","arguments":"..."}
          {"type":"tool_end","name":"...","result":"...","images":[...optional...]}
          {"type":"vision_context","count":N}
          {"type":"error","content":"...","stop_notice":"..."}
          {"type":"done","content":"...","model":"...","usage":{...},"stop_notice":"..."}
          {"type":"stopped","reason":"...","stop_notice":"..."}
          {"type":"undo_ready","can_undo": bool}
        Returns final assistant text.
        """
        attached = [img for img in (images or []) if getattr(img, "data_b64", "")]
        text = (user_text or "").strip()
        if attached and not text:
            text = "请查看附图。"
        self.memory.add(
            ChatMessage(role="user", content=text, images=attached or None)
        )
        cfg = get_config()
        max_rounds = int(cfg.get("maya.max_tool_rounds", 12))
        use_stream = stream and cfg.get("agent.stream", True)
        auto_undo = bool(cfg.get("maya.auto_undo", True)) and in_maya()
        final_text = ""
        turn_opened = False
        had_tools = False
        turn_usage: Dict[str, int] = {}
        llm_calls = 0

        try:
            provider = create_provider(self.provider_id, model=self.model)
        except Exception as e:
            yield {"type": "error", "content": str(e)}
            return str(e)

        model_name = getattr(provider, "model", "") or self.model or ""
        vision_ok = bool(getattr(provider, "supports_vision", False))
        tools = (
            tool_specs(vision=vision_ok) if provider.supports_tools else None
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

        try:
            for _ in range(max_rounds):
                try:
                    if use_stream:
                        gen = provider.chat(self.memory.as_list(), tools=tools, stream=True)
                        text_parts: List[str] = []
                        thinking_parts: List[str] = []
                        resp: Optional[ChatResponse] = None
                        try:
                            while True:
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
                        yield from self._run_one_tool(
                            tc,
                            vision_ok=vision_ok,
                            vision_batch=vision_batch,
                        )
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

    def _run_one_tool(
        self,
        tc: ToolCall,
        *,
        vision_ok: bool = False,
        vision_batch: Optional[List[ImageAttachment]] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        if self.on_tool_start:
            self.on_tool_start(tc.name, tc.arguments)
        yield {"type": "tool_start", "name": tc.name, "arguments": tc.arguments}
        result = self.executor.execute(tc.name, tc.arguments)
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

    def chat_sync(self, user_text: str, images: Optional[List[Any]] = None) -> str:
        final = ""
        for event in self.chat(user_text, stream=False, images=images):
            if event["type"] in ("done", "error"):
                final = event.get("content", "")
        return final
