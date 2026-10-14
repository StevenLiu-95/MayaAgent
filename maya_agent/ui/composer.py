"""Composer helpers (quick chips / send-stop styling) used by MayaAgentWindow."""

from __future__ import annotations

from maya_agent.i18n import t
from maya_agent.ui.qt_bind import QtWidgets


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
