"""Chat session and project bundle data models."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_session_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class ChatSession:
    id: str
    title: str
    created_at: str
    updated_at: str
    memory: List[Dict[str, Any]] = field(default_factory=list)
    ui_blocks: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def create(cls, title: str = "新对话") -> "ChatSession":
        now = _now_iso()
        return cls(
            id=new_session_id(),
            title=title,
            created_at=now,
            updated_at=now,
        )

    def touch(self) -> None:
        self.updated_at = _now_iso()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "memory": self.memory,
            "ui_blocks": self.ui_blocks,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatSession":
        return cls(
            id=str(data.get("id") or new_session_id()),
            title=str(data.get("title") or "对话"),
            created_at=str(data.get("created_at") or _now_iso()),
            updated_at=str(data.get("updated_at") or _now_iso()),
            memory=list(data.get("memory") or []),
            ui_blocks=list(data.get("ui_blocks") or []),
        )


@dataclass
class ProjectChatData:
    """All chat sessions bound to one Maya scene file."""

    scene_path: str
    active_session_id: str = ""
    sessions: List[ChatSession] = field(default_factory=list)
    version: int = 1
    saved_at: str = ""

    def get_session(self, session_id: str) -> Optional[ChatSession]:
        for s in self.sessions:
            if s.id == session_id:
                return s
        return None

    def active_session(self) -> Optional[ChatSession]:
        if not self.sessions:
            return None
        if self.active_session_id:
            s = self.get_session(self.active_session_id)
            if s:
                return s
        return self.sessions[0]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "scene_path": self.scene_path,
            "active_session_id": self.active_session_id,
            "saved_at": self.saved_at or _now_iso(),
            "sessions": [s.to_dict() for s in self.sessions],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProjectChatData":
        sessions = [ChatSession.from_dict(s) for s in (data.get("sessions") or [])]
        active = str(data.get("active_session_id") or "")
        if not active and sessions:
            active = sessions[0].id
        return cls(
            version=int(data.get("version") or 1),
            scene_path=str(data.get("scene_path") or ""),
            active_session_id=active,
            sessions=sessions,
            saved_at=str(data.get("saved_at") or ""),
        )
