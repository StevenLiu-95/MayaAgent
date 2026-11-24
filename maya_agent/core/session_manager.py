"""Multi-session chat manager bound to Maya scene projects."""

from __future__ import annotations

import copy
from typing import List, Optional

from maya_agent.core import checkpoint as cpmod
from maya_agent.core.chat_session import ChatSession, ProjectChatData
from maya_agent.core.message_codec import messages_from_dicts, messages_to_dicts
from maya_agent.core.session_store import (
    get_maya_scene_path,
    load_project,
    save_project,
)
from maya_agent.i18n import t
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
        scene = (get_maya_scene_path() or "").replace("\\", "/")
        self.project = load_project(scene)
        self.project.scene_path = scene
        if not self.project.sessions:
            self.create_session(t("session.default_title"), set_active=True, save_now=False)
            self.save()
        elif not self.project.active_session_id:
            self.project.active_session_id = self.project.sessions[0].id

    def rebind_scene_path(self, scene_path: str) -> None:
        """Update bound scene path in place (e.g. scene saved mid-turn)."""
        self.project.scene_path = (scene_path or "").replace("\\", "/")

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
        title: str = "",
        set_active: bool = True,
        save_now: bool = True,
    ) -> ChatSession:
        if not (title or "").strip():
            title = t("session.default_title")
        max_n = int(get_config().get("agent.max_sessions_per_project", 50))
        while len(self.project.sessions) >= max_n:
            oldest = min(self.project.sessions, key=lambda s: s.updated_at)
            if oldest.id == self.project.active_session_id and len(self.project.sessions) > 1:
                # drop second-oldest instead
                rest = [s for s in self.project.sessions if s.id != oldest.id]
                oldest = min(rest, key=lambda s: s.updated_at)
            self.project.sessions = [s for s in self.project.sessions if s.id != oldest.id]
            self._release_checkpoints(oldest.checkpoints)
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
        removed = self.project.get_session(session_id)
        self.project.sessions = [s for s in self.project.sessions if s.id != session_id]
        if removed is not None:
            self._release_checkpoints(removed.checkpoints)
        if self.project.active_session_id == session_id:
            self.project.active_session_id = self.project.sessions[0].id
        self.save()
        return self.active()

    def reset_active(self) -> ChatSession:
        """Clear current session content but keep the session entry."""
        s = self.active()
        old_cps = s.checkpoints
        s.memory = []
        s.ui_blocks = []
        s.pending_plan = None
        s.checkpoints = []
        self._release_checkpoints(old_cps)
        # Keep mode preference across clear.
        s.touch()
        self.save()
        return s

    def sync_session(
        self,
        session_id: str,
        memory_messages: List[ChatMessage],
        ui_blocks: List[dict],
        auto_title: bool = True,
        force: bool = False,
    ) -> None:
        """Persist one session by id without changing the active session.

        ``force`` updates the in-memory session even when auto-save is off
        (checkpoint rollback/branch need the live UI state).
        """
        if not force and not get_config().get("agent.auto_save_sessions", True):
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
        defaults = {
            "",
            "新对话",
            "对话",
            "New chat",
            t("session.default_title"),
        }
        if session.title not in defaults:
            return
        for block in ui_blocks:
            if block.get("type") == "user":
                text = (block.get("text") or "").strip()
                if text:
                    session.title = text[:30] + ("…" if len(text) > 30 else "")
                    return

    # ------------------------------------------------------------------
    # Checkpoints
    # ------------------------------------------------------------------

    def _snapshot_refs(self) -> set:
        refs = set()
        for s in self.project.sessions:
            for c in s.checkpoints:
                p = c.get("snapshot_path")
                if p:
                    refs.add(p)
        return refs

    def _release_checkpoints(self, checkpoints: List[dict]) -> None:
        """Delete snapshot files of ``checkpoints`` no other checkpoint uses."""
        if not checkpoints:
            return
        refs = self._snapshot_refs()
        for c in checkpoints:
            p = c.get("snapshot_path")
            if p and p not in refs:
                cpmod.delete_snapshot(p)

    def get_checkpoint(self, session_id: str, cp_id: str) -> Optional[cpmod.Checkpoint]:
        s = self.project.get_session(session_id)
        if not s:
            return None
        raw = s.get_checkpoint(cp_id)
        return cpmod.Checkpoint.from_dict(raw) if raw else None

    def add_checkpoint(self, session_id: str, cp: cpmod.Checkpoint) -> None:
        """Register a checkpoint and enforce ``agent.checkpoint_max``."""
        s = self.project.get_session(session_id)
        if not s:
            return
        s.checkpoints.append(cp.to_dict())
        try:
            limit = int(get_config().get("agent.checkpoint_max", 30))
        except (TypeError, ValueError):
            limit = 30
        limit = max(1, limit)
        # Oldest snapshots are dropped (the checkpoint stays: branch still works).
        with_snap = [c for c in s.checkpoints if c.get("snapshot_path")]
        overflow = with_snap[: max(0, len(with_snap) - limit)]
        if overflow:
            dropped_paths = [dict(c) for c in overflow]
            for c in overflow:
                c["snapshot_path"] = ""
            self._release_checkpoints(dropped_paths)
        s.touch()
        self.save()

    def rename_checkpoint(self, session_id: str, cp_id: str, name: str) -> bool:
        s = self.project.get_session(session_id)
        if not s:
            return False
        raw = s.get_checkpoint(cp_id)
        if raw is None:
            return False
        name = (name or "").strip()[:60]
        raw["name"] = name
        for b in s.ui_blocks:
            if b.get("type") == cpmod.BLOCK_TYPE and b.get("id") == cp_id:
                b["name"] = name
        s.touch()
        self.save()
        return True

    def rollback_to(self, session_id: str, cp_id: str) -> Optional[ChatSession]:
        """
        Cut the session's dialogue + memory back to the checkpoint.

        Scene restoration is the caller's job (do it first). Checkpoints after
        the target are discarded together with their snapshots; the target's
        own snapshot is kept so the user can roll back to it again.
        """
        s = self.project.get_session(session_id)
        if not s:
            return None
        raw = s.get_checkpoint(cp_id)
        if raw is None:
            return None
        cp = cpmod.Checkpoint.from_dict(raw)
        blocks = cpmod.truncate_blocks(s.ui_blocks, cp_id)
        if blocks is None:
            return None
        idx = next(i for i, c in enumerate(s.checkpoints) if c.get("id") == cp_id)
        dropped = s.checkpoints[idx + 1 :]
        s.checkpoints = s.checkpoints[: idx + 1]
        s.memory = cpmod.truncate_memory_dicts(s.memory, cp.memory_seq)
        s.ui_blocks = blocks
        s.pending_plan = copy.deepcopy(cp.plan) if cp.plan else None
        self._release_checkpoints(dropped)
        s.touch()
        self.save()
        return s

    def branch_from(self, session_id: str, cp_id: str) -> Optional[ChatSession]:
        """
        New active session holding the dialogue/memory up to the checkpoint.
        The scene is untouched. Snapshots are shared with the source session.
        """
        src = self.project.get_session(session_id)
        if not src:
            return None
        raw = src.get_checkpoint(cp_id)
        if raw is None:
            return None
        cp = cpmod.Checkpoint.from_dict(raw)
        blocks = cpmod.truncate_blocks(src.ui_blocks, cp_id)
        if blocks is None:
            return None
        idx = next(i for i, c in enumerate(src.checkpoints) if c.get("id") == cp_id)
        label = cp.name or ""
        title = t("checkpoint.branch_title", title=src.title, name=label)
        title = title.strip().rstrip("·").strip() or src.title
        new = self.create_session(title[:60], set_active=True, save_now=False)
        new.mode = src.mode
        new.memory = cpmod.truncate_memory_dicts(src.memory, cp.memory_seq)
        new.ui_blocks = blocks
        new.checkpoints = [copy.deepcopy(c) for c in src.checkpoints[: idx + 1]]
        new.pending_plan = copy.deepcopy(cp.plan) if cp.plan else None
        new.touch()
        self.save()
        return new

    def memory_for_active(self) -> List[ChatMessage]:
        return messages_from_dicts(self.active().memory)

    def blocks_for_active(self) -> List[dict]:
        return list(self.active().ui_blocks)

    def save(self) -> None:
        if not get_config().get("agent.auto_save_sessions", True):
            return
        # Always write to the scene this ProjectChatData is bound to (including
        # "" for untitled scenes). Critical when Maya has already switched
        # sceneName (AfterOpen / AfterNew) while we still hold the previous
        # project's sessions in memory — passing None for "" would fall back to
        # the newly opened scene path and overwrite its sidecar.
        bound = (self.project.scene_path or "").strip()
        save_project(self.project, bound)

    def scene_label(self) -> str:
        path = get_maya_scene_path() or self.project.scene_path
        if not path:
            return t("session.scene_untitled")
        name = path.replace("\\", "/").rsplit("/", 1)[-1]
        return t("session.scene_project", name=name)

    def storage_hint(self) -> str:
        from maya_agent.core.session_store import storage_path

        return str(storage_path())
