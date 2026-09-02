"""Maya Agent — AI-powered assistant for Maya game development workflows."""

__version__ = "1.0.0"
__app_name__ = "Maya Agent"


def get_config():
    from maya_agent.utils.config import get_config as _get

    return _get()


def launch():
    from maya_agent.main import launch as _launch

    return _launch()


def bootstrap():
    from maya_agent.plugin.menu import bootstrap as _boot

    return _boot()


__all__ = ["__version__", "__app_name__", "get_config", "launch", "bootstrap"]
