"""Composer helpers (quick chips / send-stop styling / input) used by MayaAgentWindow."""

from __future__ import annotations

from typing import Any, Callable, Optional

from maya_agent.i18n import t
from maya_agent.ui.qt_bind import QtGui, QtWidgets


def apply_send_stop_style(btn: QtWidgets.QPushButton, busy: bool) -> None:
    """Toggle merged send/stop button label and QSS objectName."""
    if btn is None:
        return
    if busy:
        btn.setText(t("composer.stop"))
        btn.setObjectName("stopBtn")
        btn.setToolTip(t("composer.stop_tip"))
    else:
        btn.setText(t("composer.send"))
        btn.setObjectName("sendBtn")
        btn.setToolTip(t("composer.send_tip"))
    try:
        btn.style().unpolish(btn)
        btn.style().polish(btn)
        btn.update()
    except Exception:
        pass


def quick_command_specs():
    """Return (label, prompt) pairs for composer quick chips."""
    return (
        (t("quick.scene"), t("quick.scene_prompt")),
        (t("quick.mesh"), t("quick.mesh_prompt")),
        (t("quick.fbx"), t("quick.fbx_prompt")),
        (t("quick.light"), t("quick.light_prompt")),
        (t("quick.building"), t("quick.building_prompt")),
        (t("quick.new_scene"), t("quick.new_scene_prompt")),
        (t("quick.clear_scene"), t("quick.clear_scene_prompt")),
    )


class ComposerPlainTextEdit(QtWidgets.QPlainTextEdit):
    """Composer input that cooperates with MentionController for @-mentions."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._mention = None  # type: ignore[assignment]

    def set_mention_controller(self, controller: Any) -> None:
        self._mention = controller

    def mention_controller(self) -> Any:
        return self._mention

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        ctrl = self._mention
        if ctrl is not None:
            try:
                if ctrl.handle_key(event):
                    event.accept()
                    return
            except Exception:
                pass
        super().keyPressEvent(event)

    def insert_at_cursor(self, text: str) -> None:
        """Insert ``text`` at the cursor (used by tools panel / helpers)."""
        if not text:
            return
        cursor = self.textCursor()
        cursor.insertText(text)
        self.setTextCursor(cursor)


def attach_mention_controller(
    edit: ComposerPlainTextEdit,
    *,
    session_manager_provider: Optional[Callable[[], Any]] = None,
) -> Any:
    """Create and bind a MentionController to ``edit``."""
    from maya_agent.ui import mention as mention_mod

    _, controller_cls = mention_mod._ensure_ui_classes()
    controller = controller_cls(
        edit, session_manager_provider=session_manager_provider, parent=edit
    )
    edit.set_mention_controller(controller)
    return controller
