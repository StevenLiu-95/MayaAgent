"""Shared Maya cmds/mel accessors for tool modules."""

from __future__ import annotations

from maya_agent.utils.maya_compat import NOT_IN_MAYA, cmds, in_maya, mel

__all__ = ["NOT_IN_MAYA", "cmds", "in_maya", "mel", "require_maya"]


def require_maya():
    """Return cmds module or raise a ToolResult-friendly error string via RuntimeError."""
    if not in_maya():
        raise RuntimeError(NOT_IN_MAYA)
    return cmds()
