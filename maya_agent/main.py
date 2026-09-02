"""Package entry helpers."""

from maya_agent.ui.main_window import show_main_window
from maya_agent.plugin.menu import bootstrap


def launch():
    """Open the Maya Agent UI."""
    return show_main_window()


__all__ = ["launch", "bootstrap", "show_main_window"]
