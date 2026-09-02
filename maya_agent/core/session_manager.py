"""Multi-session chat manager bound to Maya scene projects."""

from __future__ import annotations

from typing import List, Optional

from maya_agent.core.chat_session import ChatSession, ProjectChatData
from maya_agent.core.message_codec import messages_from_dicts, messages_to_dicts
from maya_agent.core.session_store import (
    get_maya_scene_path,
    load_project,
    save_project,
)
from maya_agent.llm.base import ChatMessage
from maya_agent.utils.config import get_config
from maya_agent.utils.logger import get_logger

log = get_logger("maya_agent.session_manager")


class SessionManager:
    """Manages multiple chat sessions for the current Maya scene."""

    def __init__(self) -> None:
        self.project: ProjectChatData = ProjectChatData(scene_path="")
        self.reload_from_disk()

    def reload_from_disk(self) -> None:
        scene = get_maya_scene_path()
        self.project = load_project(scene)
        self.project.scene_path = scene or self.project.scene_path
        if not self.project.sessions:
            self.create_session("新对话", set_active=True, save_now=False)
            self.save()
        elif not self.project.active_session_id:
            self.project.active_session_id = self.project.sessions[0].id

    def active(self) -> ChatSession:
        s = self.project.active_session()
        if s is None:
            return self.create_session("新对话", set_active=True)
        return s

    def list_sessions(self) -> List[ChatSession]:
        return sorted(
            self.project.sessions,
            key=lambda s: s.updated_at,
            reverse=True,
        )

    def create_session(
        self,
        title: str = "新对话",
        set_active: bool = True,
        save_now: bool = True,
    ) -> ChatSession:
        max_n = int(get_config().get("agent.max_sessions_per_project", 50))
        while len(self.project.sessions) >= max_n:
            oldest = min(self.project.sessions, key=lambda s: s.updated_at)
            if oldest.id == self.project.active_session_id and len(self.project.sessions) > 1:
                # drop second-oldest instead
                rest = [s for s in self.project.sessions if s.id != oldest.id]
                oldest = min(rest, key=lambda s: s.updated_at)
            self.project.sessions = [s for s in self.project.sessions if s.id != oldest.id]
            log.info("dropped oldest session %s (limit %s)", oldest.id, max_n)

        session = ChatSession.create(title)
        self.project.sessions.insert(0, session)
        if set_active:
            self.project.active_session_id = session.id
        if save_now:
            self.save()
        return session

    def switch(self, session_id: str) -> ChatSession:
        s = self.project.get_session(session_id)
        if not s:
            raise KeyError(session_id)
        self.project.active_session_id = session_id
        self.save()
        return s

    def rename(self, session_id: str, title: str) -> None:
        s = self.project.get_session(session_id)
        if not s:
            return
        s.title = (title or "对话").strip()[:60] or "对话"
        s.touch()
        self.save()

    def delete(self, session_id: str) -> Optional[ChatSession]:
        """Delete a session. Returns the new active session, or None if empty."""
        if len(self.project.sessions) <= 1:
            return None
        self.project.sessions = [s for s in self.project.sessions if s.id != session_id]
        if self.project.active_session_id == session_id:
            self.project.active_session_id = self.project.sessions[0].id
        self.save()
        return self.active()

    def reset_active(self) -> ChatSession:
        """Clear current session content but keep the session entry."""
        s = self.active()
        s.memory = []
        s.ui_blocks = []
        s.touch()
        self.save()
        return s

    def sync_session(
        self,
        session_id: str,
        memory_messages: List[ChatMessage],
        ui_blocks: List[dict],
        auto_title: bool = True,
    ) -> None:
        """Persist one session by id without changing the active session."""
        if not get_config().get("agent.auto_save_sessions", True):
            return
        s = self.project.get_session(session_id)
        if not s:
            return
        s.memory = messages_to_dicts(memory_messages)
        s.ui_blocks = [dict(b) for b in ui_blocks]
        s.touch()
        if auto_title:
            self._maybe_auto_title(s, ui_blocks)
        self.save()

    def sync_active(
        self,
        memory_messages: List[ChatMessage],
        ui_blocks: List[dict],
        auto_title: bool = True,
    ) -> None:
        if not get_config().get("agent.auto_save_sessions", True):
            return
        self.sync_session(
            self.active().id,
            memory_messages,
            ui_blocks,
            auto_title=auto_title,
        )

    @staticmethod
    def _maybe_auto_title(session: ChatSession, ui_blocks: List[dict]) -> None:
        if session.title not in ("", "新对话", "对话"):
            return
        for block in ui_blocks:
            if block.get("type") == "user":
                text = (block.get("text") or "").strip()
                if text:
                    session.title = text[:30] + ("…" if len(text) > 30 else "")
                    return

    def memory_for_active(self) -> List[ChatMessage]:
        return messages_from_dicts(self.active().memory)

    def blocks_for_active(self) -> List[dict]:
        return list(self.active().ui_blocks)

    def save(self) -> None:
        if not get_config().get("agent.auto_save_sessions", True):
            return
        save_project(self.project)

    def scene_label(self) -> str:
        path = get_maya_scene_path() or self.project.scene_path
        if not path:
            return "未保存场景 · 会话暂存于用户目录"
        name = path.replace("\\", "/").rsplit("/", 1)[-1]
        return f"工程: {name}"

    def storage_hint(self) -> str:
        from maya_agent.core.session_store import storage_path

        return str(storage_path())
