"""Plan proposal card shown in the chat transcript."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from maya_agent.i18n import t
from maya_agent.ui.qt_bind import QtCore, QtWidgets


class PlanCard(QtWidgets.QFrame):
    """Structured plan with Approve / Reject actions."""

    def __init__(
        self,
        plan: Dict[str, Any],
        *,
        on_approve: Optional[Callable[[], None]] = None,
        on_reject: Optional[Callable[[], None]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("planCard")
        self._plan = dict(plan or {})
        self._on_approve = on_approve
        self._on_reject = on_reject
        self._interactive = True

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)

        header = QtWidgets.QHBoxLayout()
        badge = QtWidgets.QLabel(t("plan.badge"))
        badge.setObjectName("planBadge")
        self._title = QtWidgets.QLabel(self._plan.get("title") or t("plan.untitled"))
        self._title.setObjectName("planTitle")
        self._title.setWordWrap(True)
        header.addWidget(badge, 0)
        header.addWidget(self._title, 1)
        lay.addLayout(header)

        self._overview = QtWidgets.QLabel(self._plan.get("overview") or "")
        self._overview.setObjectName("planOverview")
        self._overview.setWordWrap(True)
        if not (self._plan.get("overview") or "").strip():
            self._overview.hide()
        lay.addWidget(self._overview)

        self._steps_host = QtWidgets.QWidget()
        self._steps_lay = QtWidgets.QVBoxLayout(self._steps_host)
        self._steps_lay.setContentsMargins(0, 0, 0, 0)
        self._steps_lay.setSpacing(3)
        lay.addWidget(self._steps_host)
        self._rebuild_steps()

        self._btn_row = QtWidgets.QHBoxLayout()
        self._btn_row.addStretch(1)
        self._approve_btn = QtWidgets.QPushButton(t("plan.approve"))
        self._approve_btn.setObjectName("planApproveBtn")
        self._approve_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._approve_btn.clicked.connect(self._handle_approve)
        self._reject_btn = QtWidgets.QPushButton(t("plan.reject"))
        self._reject_btn.setObjectName("planRejectBtn")
        self._reject_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._reject_btn.clicked.connect(self._handle_reject)
        self._btn_row.addWidget(self._reject_btn)
        self._btn_row.addWidget(self._approve_btn)
        lay.addLayout(self._btn_row)

        status = str(self._plan.get("status") or "pending")
        if status not in ("pending",):
            self.set_interactive(False)

    def plan_data(self) -> Dict[str, Any]:
        return dict(self._plan)

    def update_plan(self, plan: Dict[str, Any]) -> None:
        self._plan = dict(plan or {})
        self._title.setText(self._plan.get("title") or t("plan.untitled"))
        overview = self._plan.get("overview") or ""
        self._overview.setText(overview)
        self._overview.setVisible(bool(str(overview).strip()))
        self._rebuild_steps()
        status = str(self._plan.get("status") or "pending")
        if status != "pending":
            self.set_interactive(False)

    def set_interactive(self, enabled: bool) -> None:
        self._interactive = bool(enabled)
        self._approve_btn.setVisible(self._interactive)
        self._reject_btn.setVisible(self._interactive)
        self._approve_btn.setEnabled(self._interactive)
        self._reject_btn.setEnabled(self._interactive)

    def _rebuild_steps(self) -> None:
        while self._steps_lay.count():
            item = self._steps_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        steps: List[Dict[str, Any]] = list(self._plan.get("steps") or [])
        for i, step in enumerate(steps, 1):
            if not isinstance(step, dict):
                step = {"title": str(step), "status": "pending"}
            status = str(step.get("status") or "pending")
            title = str(step.get("title") or f"#{i}")
            label = QtWidgets.QLabel(f"{i}. [{status}] {title}")
            label.setObjectName("planStep")
            label.setWordWrap(True)
            self._steps_lay.addWidget(label)

    def _handle_approve(self) -> None:
        if not self._interactive:
            return
        self.set_interactive(False)
        self._plan["status"] = "approved"
        if self._on_approve:
            self._on_approve()

    def _handle_reject(self) -> None:
        if not self._interactive:
            return
        self.set_interactive(False)
        self._plan["status"] = "rejected"
        if self._on_reject:
            self._on_reject()
