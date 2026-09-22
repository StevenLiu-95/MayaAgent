"""UI package."""

__all__ = ["show_main_window"]


def show_main_window():
    from maya_agent.ui.main_window import show_main_window as _show

    return _show()
