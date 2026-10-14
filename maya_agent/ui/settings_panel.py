"""Compatibility re-export — panels live in ``maya_agent.ui.settings``."""

from __future__ import annotations

from maya_agent.ui.settings import (
    create_help_panel,
    create_settings_panel,
    create_tools_panel,
    create_ui_panel,
)
from maya_agent.ui.settings.config_defaults import ConfigDefaults

__all__ = [
    "ConfigDefaults",
    "create_help_panel",
    "create_settings_panel",
    "create_tools_panel",
    "create_ui_panel",
]
