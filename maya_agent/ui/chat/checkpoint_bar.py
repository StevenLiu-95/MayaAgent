"""Checkpoint widgets shown between conversation turns.

``CheckpointBar``   --  ── ● name  [Rollback] [Branch] ──      (a saved checkpoint)
``CheckpointOffer`` --  ──────── [+ Add checkpoint] ────────    (manual mode)
"""

from __future__ import annotations

from typing import Callable, Optional

from maya_agent.i18n import t
from maya_agent.ui.qt_bind import QtCore, QtWidgets


def _hline() -> "QtWidgets.QFrame":
    line = QtWidgets.QFrame()
    line.setObjectName("checkpointLine")
    line.setFrameShape(QtWidgets.QFrame.HLine)
    line.setFixedHeight(1)
    line.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
    return line


class _NameLabel(QtWidgets.QLabel):
    """Click-to-rename label."""

    clicked = QtCore.Signal()

    def mouseReleaseEvent(self, event):  # noqa: N802 (Qt API)
        if event.button() == QtCore.Qt.LeftButton and self.rect().contains(
            event.pos()
        ):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class CheckpointBar(QtWidgets.QWidget):
    def __init__(
        self,
        cp_id: str,
        name: str = "",
        *,
        can_rollback: bool = True,
        actions_enabled: bool = True,
        on_rollback: Optional[Callable[[str], None]] = None,
        on_branch: Optional[Callable[[str], None]] = None,
        on_rename: Optional[Callable[[str, str], None]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("checkpointBar")
        self.cp_id = cp_id
        self._name = name or ""
        self._can_rollback = bool(can_rollback)
        self._actions_enabled = bool(actions_enabled)
        self._on_rollback = on_rollback
        self._on_branch = on_branch
        self._on_rename = on_rename
        self._editing = False

        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(12, 4, 12, 4)
        lay.setSpacing(8)
        lay.addWidget(_hline(), 1)

        dot = QtWidgets.QLabel()
        dot.setObjectName("checkpointDot")
        dot.setFixedSize(8, 8)
        lay.addWidget(dot, 0, QtCore.Qt.AlignVCenter)

        self._name_lbl = _NameLabel()
        self._name_lbl.setObjectName("checkpointName")
        self._name_lbl.setCursor(QtCore.Qt.PointingHandCursor)
        self._name_lbl.setToolTip(t("checkpoint.rename_tip"))
        self._name_lbl.clicked.connect(self._begin_rename)
        lay.addWidget(self._name_lbl, 0)

        self._name_edit = QtWidgets.QLineEdit()
        self._name_edit.setObjectName("checkpointNameEdit")
        self._name_edit.setMaxLength(60)
        self._name_edit.setMinimumWidth(120)
        self._name_edit.setPlaceholderText(t("checkpoint.name_placeholder"))
        self._name_edit.returnPressed.connect(self._commit_rename)
        self._name_edit.editingFinished.connect(self._commit_rename)
        self._name_edit.hide()
        lay.addWidget(self._name_edit, 0)

        self._rollback_btn = QtWidgets.QPushButton(t("checkpoint.rollback"))
        self._rollback_btn.setObjectName("checkpointBtn")
        self._rollback_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._rollback_btn.clicked.connect(self._emit_rollback)
        lay.addWidget(self._rollback_btn, 0)

        self._branch_btn = QtWidgets.QPushButton(t("checkpoint.branch"))
        self._branch_btn.setObjectName("checkpointBtn")
        self._branch_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._branch_btn.setToolTip(t("checkpoint.branch_tip"))
        self._branch_btn.clicked.connect(self._emit_branch)
        lay.addWidget(self._branch_btn, 0)

        lay.addWidget(_hline(), 1)

        self._refresh_name()
        self._refresh_buttons()

    # -- state ------------------------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    def set_name(self, name: str) -> None:
        self._name = name or ""
        self._refresh_name()

    def set_can_rollback(self, value: bool) -> None:
        self._can_rollback = bool(value)
        self._refresh_buttons()

    def set_actions_enabled(self, value: bool) -> None:
        self._actions_enabled = bool(value)
        self._refresh_buttons()

    def _refresh_name(self) -> None:
        self._name_lbl.setText(self._name or t("checkpoint.unnamed"))

    def _refresh_buttons(self) -> None:
        self._rollback_btn.setEnabled(self._actions_enabled and self._can_rollback)
        self._branch_btn.setEnabled(self._actions_enabled)
        if self._can_rollback:
            self._rollback_btn.setToolTip(t("checkpoint.rollback_tip"))
        else:
            self._rollback_btn.setToolTip(t("checkpoint.no_snapshot_tip"))

    # -- actions ----------------------------------------------------------

    def _emit_rollback(self) -> None:
        if self._on_rollback:
            self._on_rollback(self.cp_id)

    def _emit_branch(self) -> None:
        if self._on_branch:
            self._on_branch(self.cp_id)

    def _begin_rename(self) -> None:
        if self._editing:
            return
        self._editing = True
        self._name_edit.setText(self._name)
        self._name_lbl.hide()
        self._name_edit.show()
        self._name_edit.setFocus()
        self._name_edit.selectAll()

    def _commit_rename(self) -> None:
        # returnPressed and editingFinished both fire; handle once.
        if not self._editing:
            return
        self._editing = False
        new_name = self._name_edit.text().strip()
        self._name_edit.hide()
        self._name_lbl.show()
        if new_name != self._name:
            self._name = new_name
            self._refresh_name()
            if self._on_rename:
                self._on_rename(self.cp_id, new_name)

    def keyPressEvent(self, event):  # noqa: N802 (Qt API)
        if self._editing and event.key() == QtCore.Qt.Key_Escape:
            self._editing = False
            self._name_edit.hide()
            self._name_lbl.show()
            return
        super().keyPressEvent(event)


class CheckpointOffer(QtWidgets.QWidget):
    """Manual mode: subtle row offering to add a checkpoint after an answer."""

    def __init__(self, on_add: Optional[Callable[[], None]] = None, parent=None):
        super().__init__(parent)
        self.setObjectName("checkpointOffer")
        self._on_add = on_add
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(12, 4, 12, 4)
        lay.setSpacing(8)
        lay.addWidget(_hline(), 1)
        self._btn = QtWidgets.QPushButton(t("checkpoint.add"))
        self._btn.setObjectName("checkpointAddBtn")
        self._btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn.setToolTip(t("checkpoint.add_tip"))
        self._btn.clicked.connect(self._emit_add)
        lay.addWidget(self._btn, 0)
        lay.addWidget(_hline(), 1)

    def set_enabled_actions(self, value: bool) -> None:
        self._btn.setEnabled(bool(value))

    def _emit_add(self) -> None:
        self._btn.setEnabled(False)
        if self._on_add:
            self._on_add()
