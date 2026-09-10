"""Agent orchestration — LLM + tools loop."""

from __future__ import annotations

from typing import Any, Callable, Dict, Generator, List, Optional

from maya_agent.core.executor import ToolExecutor
from maya_agent.core.memory import ConversationMemory
from maya_agent.core.undo import UndoTurnManager
from maya_agent.llm.base import ChatMessage, ChatResponse, StreamChunk, ToolCall
from maya_agent.llm.registry import create_provider
from maya_agent.tools.registry import ensure_tools_loaded, tool_specs
from maya_agent.utils.config import get_config
from maya_agent.utils.logger import get_logger
from maya_agent.utils.maya_compat import in_maya, maya_version

log = get_logger("maya_agent.agent")


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
    ) -> Generator[Dict[str, Any], None, str]:
        """
        Yields event dicts:
          {"type":"text","content":"..."}
          {"type":"tool_start","name":"...","arguments":"..."}
          {"type":"tool_end","name":"...","result":"..."}
          {"type":"error","content":"..."}
          {"type":"done","content":"..."}
          {"type":"undo_ready","can_undo": bool}
        Returns final assistant text.
        """
        self.memory.add(ChatMessage(role="user", content=user_text))
        cfg = get_config()
        max_rounds = int(cfg.get("maya.max_tool_rounds", 12))
        use_stream = stream and cfg.get("agent.stream", True)
        auto_undo = bool(cfg.get("maya.auto_undo", True)) and in_maya()
        final_text = ""
        turn_opened = False
        had_tools = False

        try:
            provider = create_provider(self.provider_id, model=self.model)
        except Exception as e:
            yield {"type": "error", "content": str(e)}
            return str(e)

        tools = tool_specs() if provider.supports_tools else None

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
                    yield {"type": "error", "content": f"LLM 调用失败: {e}"}
                    return str(e)

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
                    for tc in resp.tool_calls:
                        yield from self._run_one_tool(tc)
                    continue

                final_text = resp.content or ""
                self.memory.add(ChatMessage(role="assistant", content=final_text))
                yield {"type": "done", "content": final_text}
                evt = _close_undo_turn()
                if evt:
                    yield evt
                return final_text

            msg = "已达到最大工具调用轮次，请缩小任务范围后重试。"
            evt = _close_undo_turn()
            if evt:
                yield evt
            yield {"type": "error", "content": msg}
            return msg
        except Exception:
            if turn_opened:
                self.undo.end_turn(had_edits=had_tools)
                turn_opened = False
            raise
        finally:
            # Safety: never leave an open Maya undo chunk behind
            if turn_opened:
                self.undo.end_turn(had_edits=had_tools)

    def _run_one_tool(self, tc: ToolCall) -> Generator[Dict[str, Any], None, None]:
        if self.on_tool_start:
            self.on_tool_start(tc.name, tc.arguments)
        yield {"type": "tool_start", "name": tc.name, "arguments": tc.arguments}
        result = self.executor.execute(tc.name, tc.arguments)
        text = result.to_str()
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

    def chat_sync(self, user_text: str) -> str:
        final = ""
        for event in self.chat(user_text, stream=False):
            if event["type"] in ("done", "error"):
                final = event.get("content", "")
        return final
