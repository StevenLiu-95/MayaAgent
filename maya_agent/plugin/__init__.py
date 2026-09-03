"""Plugin package."""

from maya_agent.plugin.menu import (
    bootstrap,
    install_menu,
    install_shelf,
    reload_plugin,
    remove_shelf,
    uninstall_ui,
)

__all__ = [
    "bootstrap",
    "install_menu",
    "install_shelf",
    "reload_plugin",
    "remove_shelf",
    "uninstall_ui",
]
