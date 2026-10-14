"""Chat UI widgets (module-level Qt classes)."""

from __future__ import annotations

from maya_agent.ui.chat.panel import ChatPanel


def create_chat_panel(parent=None):
    """Build ChatPanel and return an instance."""
    return ChatPanel(parent)


__all__ = ["ChatPanel", "create_chat_panel"]
