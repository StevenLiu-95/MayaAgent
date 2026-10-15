"""Local models + Local Runtime settings page (embedded as a tab)."""

from __future__ import annotations

from typing import Callable, Optional

from maya_agent.i18n import t
from maya_agent.local_models.availability import list_backend_status, local_cfg
from maya_agent.local_models.client import runtime_status, start_runtime, stop_runtime
from maya_agent.local_models.downloader import (
    delete_backend,
    get_download_job,
    start_download_async,
)
from maya_agent.local_models.installer_bridge import start_installer_async
from maya_agent.ui.palette import COLOR_MUTED, COLOR_TEST_FAIL, COLOR_TEST_OK
from maya_agent.ui.qt_bind import QtCore, QtWidgets
from maya_agent.ui.settings.form_helpers import SettingsFormMixin
from maya_agent.utils.config import get_config


class _InstallSignals(QtCore.QObject):
    line = QtCore.Signal(str)
    progress = QtCore.Signal(int, str)
    subprogress = QtCore.Signal(int, str)
    finished = QtCore.Signal(dict)


class LocalModelsPage(SettingsFormMixin, QtWidgets.QWidget):
    """Content for the「本地模型」tab inside SettingsPanel."""

    def __init__(
        self, parent=None, *, on_saved: Optional[Callable[..., None]] = None
    ):
        super().__init__(parent)
        self.cfg = get_config()
        self._on_saved = on_saved
        self._rows = {}  # backend_id -> widgets
        self._installing = False
        self._install_signals = _InstallSignals()
        self._install_signals.line.connect(self._on_install_line)
        self._install_signals.progress.connect(self._on_install_progress)
        self._install_signals.subprogress.connect(self._on_install_subprogress)
        self._install_signals.finished.connect(self._on_install_finished)
        self._build()
        self.refresh()
        self._poll = QtCore.QTimer(self)
        self._poll.setInterval(800)
        self._poll.timeout.connect(self._poll_jobs)
        self._poll.start()

    def _build(self) -> None:
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll, root = self._scroll_page()
        outer.addWidget(scroll)

        # Runtime section
        rt, rt_lay = self._section(
            t("settings.section.local_runtime"),
            t("settings.section.local_runtime_hint"),
        )
        self.local_enabled = QtWidgets.QCheckBox(t("settings.local_enabled"))
        rt_lay.addWidget(
            self._option_row(self.local_enabled, t("settings.local_enabled_hint"))
        )
        self.runtime_status = QtWidgets.QLabel("")
        self.runtime_status.setObjectName("testConnStatus")
        self.runtime_status.setWordWrap(True)
        rt_lay.addWidget(self.runtime_status)

        self.install_progress = QtWidgets.QProgressBar()
        self.install_progress.setRange(0, 100)
        self.install_progress.setValue(0)
        self.install_progress.setTextVisible(True)
        self.install_progress.setFormat(t("settings.local_install_overall_fmt"))
        self.install_progress.setVisible(False)
        self.install_progress.setMinimumHeight(18)
        rt_lay.addWidget(self.install_progress)

        self.install_phase = QtWidgets.QLabel("")
        self.install_phase.setObjectName("settingsSectionHint")
        self.install_phase.setWordWrap(True)
        self.install_phase.setVisible(False)
        rt_lay.addWidget(self.install_phase)

        self.install_sub_label = QtWidgets.QLabel(t("settings.local_install_sub_label"))
        self.install_sub_label.setObjectName("settingsSectionHint")
        self.install_sub_label.setVisible(False)
        rt_lay.addWidget(self.install_sub_label)

        self.install_sub_progress = QtWidgets.QProgressBar()
        self.install_sub_progress.setRange(0, 100)
        self.install_sub_progress.setValue(0)
        self.install_sub_progress.setTextVisible(True)
        self.install_sub_progress.setFormat("%p%")
        self.install_sub_progress.setVisible(False)
        self.install_sub_progress.setMinimumHeight(16)
        rt_lay.addWidget(self.install_sub_progress)

        self.install_sub_phase = QtWidgets.QLabel("")
        self.install_sub_phase.setObjectName("settingsSectionHint")
        self.install_sub_phase.setWordWrap(True)
        self.install_sub_phase.setVisible(False)
        rt_lay.addWidget(self.install_sub_phase)

        self.install_log = QtWidgets.QPlainTextEdit()
        self.install_log.setObjectName("settingsToolDesc")
        self.install_log.setReadOnly(True)
        self.install_log.setPlaceholderText(t("settings.local_install_log_ph"))
        self.install_log.setMinimumHeight(140)
        self.install_log.setMaximumHeight(220)
        self.install_log.setVisible(False)
        self.install_log.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        rt_lay.addWidget(self.install_log)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setSpacing(8)
        self.btn_install = QtWidgets.QPushButton(t("settings.local_install"))
        self.btn_repair = QtWidgets.QPushButton(t("settings.local_repair"))
        self.btn_start = QtWidgets.QPushButton(t("settings.local_start"))
        self.btn_stop = QtWidgets.QPushButton(t("settings.local_stop"))
        self.btn_refresh = QtWidgets.QPushButton(t("settings.local_refresh"))
        for b in (
            self.btn_install,
            self.btn_repair,
            self.btn_start,
            self.btn_stop,
            self.btn_refresh,
        ):
            b.setObjectName("secondaryBtn")
            b.setCursor(QtCore.Qt.PointingHandCursor)
            b.setMinimumHeight(30)
            btn_row.addWidget(b)
        btn_row.addStretch(1)
        rt_lay.addLayout(btn_row)
        root.addWidget(rt)

        self.btn_install.clicked.connect(lambda: self._run_installer(False))
        self.btn_repair.clicked.connect(lambda: self._run_installer(True))
        self.btn_start.clicked.connect(self._start_rt)
        self.btn_stop.clicked.connect(self._stop_rt)
        self.btn_refresh.clicked.connect(self.refresh)
        self.local_enabled.toggled.connect(self._save_enabled)

        # Models list
        md, md_lay = self._section(
            t("settings.section.local_models"),
            t("settings.section.local_models_hint"),
        )
        self.models_host = QtWidgets.QVBoxLayout()
        self.models_host.setSpacing(8)
        md_lay.addLayout(self.models_host)
        root.addWidget(md)
        self._stretch_end(root)

    def _save_enabled(self, *_a) -> None:
        self.cfg.set("local.enabled", bool(self.local_enabled.isChecked()))
        self.cfg.save_user()
        if self._on_saved:
            self._on_saved(language_changed=False)

    def _set_status(self, text: str, kind: str = "info") -> None:
        colors = {"ok": COLOR_TEST_OK, "fail": COLOR_TEST_FAIL, "info": COLOR_MUTED}
        self.runtime_status.setText(text or "")
        self.runtime_status.setStyleSheet(
            f"QLabel#testConnStatus {{ color: {colors.get(kind, COLOR_MUTED)}; "
            f"font-size: 12px; background: transparent; border: none; padding: 0; }}"
        )

    def refresh(self) -> None:
        if self._installing:
            return
        self.cfg.reload()
        conf = local_cfg()
        self.local_enabled.blockSignals(True)
        self.local_enabled.setChecked(bool(conf["enabled"]))
        self.local_enabled.blockSignals(False)

        try:
            st = runtime_status()
        except Exception as e:
            self._set_status(str(e), "fail")
            st = {}

        if st.get("online"):
            self._set_status(
                t("settings.local_runtime_on", url=st.get("base_url") or ""),
                "ok",
            )
        elif st.get("installed"):
            self._set_status(t("settings.local_runtime_installed_off"), "info")
        else:
            self._set_status(t("settings.local_runtime_missing"), "fail")

        # Rebuild model rows
        while self.models_host.count():
            item = self.models_host.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._rows.clear()

        for row in list_backend_status():
            if row.get("hidden"):
                continue
            self.models_host.addWidget(self._make_backend_card(row))

    def _make_backend_card(self, row: dict) -> QtWidgets.QWidget:
        bid = str(row.get("id") or "")
        frame = QtWidgets.QFrame()
        frame.setObjectName("settingsSection")
        lay = QtWidgets.QVBoxLayout(frame)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)

        title = QtWidgets.QLabel(
            f"{row.get('label') or bid}  ·  {row.get('domain') or ''}"
        )
        title.setObjectName("settingsSectionTitle")
        lay.addWidget(title)

        desc = QtWidgets.QLabel(str(row.get("description") or ""))
        desc.setObjectName("settingsSectionHint")
        desc.setWordWrap(True)
        lay.addWidget(desc)

        meta = QtWidgets.QLabel(
            t(
                "settings.local_model_meta",
                size=row.get("approx_size_gb") or "?",
                vram=row.get("vram_gb") or "?",
                license=row.get("license") or "",
            )
        )
        meta.setObjectName("settingsSectionHint")
        meta.setWordWrap(True)
        lay.addWidget(meta)

        status = QtWidgets.QLabel(
            t("settings.local_ready") if row.get("ready") else t("settings.local_not_ready")
        )
        status.setObjectName("testConnStatus")
        status.setStyleSheet(
            f"QLabel#testConnStatus {{ color: {COLOR_TEST_OK if row.get('ready') else COLOR_TEST_FAIL}; "
            f"font-size: 12px; background: transparent; border: none; padding: 0; }}"
        )
        lay.addWidget(status)

        progress = QtWidgets.QProgressBar()
        progress.setRange(0, 100)
        progress.setValue(0)
        progress.setVisible(False)
        progress.setFixedHeight(14)
        lay.addWidget(progress)

        msg = QtWidgets.QLabel("")
        msg.setObjectName("settingsSectionHint")
        msg.setWordWrap(True)
        lay.addWidget(msg)

        actions = QtWidgets.QHBoxLayout()
        btn_dl = QtWidgets.QPushButton(t("settings.local_download"))
        btn_del = QtWidgets.QPushButton(t("settings.local_delete"))
        for b in (btn_dl, btn_del):
            b.setObjectName("secondaryBtn")
            b.setCursor(QtCore.Qt.PointingHandCursor)
            b.setMinimumHeight(28)
            actions.addWidget(b)
        actions.addStretch(1)
        lay.addLayout(actions)

        btn_dl.clicked.connect(lambda _=False, i=bid: self._download(i))
        btn_del.clicked.connect(lambda _=False, i=bid: self._delete(i))

        self._rows[bid] = {
            "status": status,
            "progress": progress,
            "msg": msg,
            "btn_dl": btn_dl,
            "btn_del": btn_del,
        }
        return frame

    def _download(self, backend_id: str) -> None:
        widgets = self._rows.get(backend_id) or {}
        if widgets.get("btn_dl"):
            widgets["btn_dl"].setEnabled(False)
        if widgets.get("progress"):
            widgets["progress"].setVisible(True)
            widgets["progress"].setValue(0)
        if widgets.get("msg"):
            widgets["msg"].setText(t("settings.local_downloading"))

        def on_done(result: dict) -> None:
            def _ui() -> None:
                if widgets.get("btn_dl"):
                    widgets["btn_dl"].setEnabled(True)
                if result.get("ok"):
                    if widgets.get("msg"):
                        widgets["msg"].setText(t("settings.local_download_ok"))
                else:
                    if widgets.get("msg"):
                        widgets["msg"].setText(
                            t(
                                "settings.local_download_fail",
                                error=result.get("error") or "",
                            )
                        )
                self.refresh()

            QtCore.QTimer.singleShot(0, _ui)

        start_download_async(backend_id, on_done=on_done)

    def _delete(self, backend_id: str) -> None:
        reply = QtWidgets.QMessageBox.question(
            self,
            t("settings.local_delete_title"),
            t("settings.local_delete_body", id=backend_id),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        delete_backend(backend_id)
        self.refresh()

    def _poll_jobs(self) -> None:
        for bid, widgets in list(self._rows.items()):
            job = get_download_job(bid)
            st = job.get("status") or "idle"
            if st == "downloading":
                if widgets.get("progress"):
                    widgets["progress"].setVisible(True)
                    widgets["progress"].setValue(int(job.get("progress") or 0))
                if widgets.get("msg"):
                    widgets["msg"].setText(str(job.get("message") or ""))
            elif st == "error":
                if widgets.get("progress"):
                    widgets["progress"].setVisible(False)
                if widgets.get("btn_dl"):
                    widgets["btn_dl"].setEnabled(True)

    def _set_install_ui_active(self, active: bool) -> None:
        self._installing = active
        self.btn_install.setEnabled(not active)
        self.btn_repair.setEnabled(not active)
        self.install_progress.setVisible(True)
        self.install_phase.setVisible(True)
        self.install_log.setVisible(True)
        if active:
            self.install_progress.setValue(0)
            self.install_phase.setText(t("settings.local_installing"))
            self.install_log.clear()
            self._hide_subprogress()
        else:
            # Keep overall bar; hide sub-bar when idle
            if not active:
                pass

    def _hide_subprogress(self) -> None:
        self.install_sub_label.setVisible(False)
        self.install_sub_progress.setVisible(False)
        self.install_sub_phase.setVisible(False)
        self.install_sub_progress.setValue(0)
        self.install_sub_phase.setText("")

    def _show_subprogress(self, pct: int, message: str) -> None:
        self.install_sub_label.setVisible(True)
        self.install_sub_progress.setVisible(True)
        self.install_sub_phase.setVisible(True)
        self.install_sub_progress.setValue(max(0, min(100, int(pct))))
        if message:
            self.install_sub_phase.setText(message)
        if pct >= 100:
            # Brief completion, then can stay at 100 until next phase
            self.install_sub_phase.setText(
                message or t("settings.local_install_sub_done")
            )

    def _on_install_line(self, line: str) -> None:
        self.install_log.appendPlainText(line)
        # Keep scrolled to bottom
        bar = self.install_log.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _on_install_progress(self, pct: int, message: str) -> None:
        self.install_progress.setValue(max(0, min(100, int(pct))))
        if message:
            self.install_phase.setText(message)
            self._set_status(f"{t('settings.local_installing')} {pct}% — {message}", "info")
        # Leaving download band → hide sub-bar for next phases
        if pct >= 65 and self.install_sub_progress.isVisible():
            # Keep visible at 100 briefly if just finished torch; hide after torch band
            if pct >= 66:
                self._hide_subprogress()

    def _on_install_subprogress(self, pct: int, message: str) -> None:
        self._show_subprogress(pct, message)

    def _on_install_finished(self, result: dict) -> None:
        self._set_install_ui_active(False)
        self.btn_install.setEnabled(True)
        self.btn_repair.setEnabled(True)
        self.install_progress.setVisible(True)
        if result.get("ok"):
            self.install_progress.setValue(100)
            self.install_phase.setText(t("settings.local_install_ok"))
            self._set_status(t("settings.local_install_ok"), "ok")
            self._on_install_line("--- " + t("settings.local_install_ok") + " ---")
            self._hide_subprogress()
        else:
            err = result.get("error") or result.get("message") or "failed"
            self.install_phase.setText(
                t("settings.local_install_fail", error=str(err)[:200])
            )
            self._set_status(
                t("settings.local_install_fail", error=str(err)[:300]),
                "fail",
            )
            self._on_install_line("--- FAIL: " + str(err)[:500] + " ---")
        self._installing = False
        self.refresh()

    def _run_installer(self, repair: bool) -> None:
        if self._installing:
            return
        self._set_install_ui_active(True)
        self._set_status(t("settings.local_installing"), "info")
        sig = self._install_signals

        def on_line(line: str) -> None:
            sig.line.emit(line)

        def on_progress(pct: int, message: str) -> None:
            sig.progress.emit(int(pct), str(message or ""))

        def on_subprogress(pct: int, message: str) -> None:
            sig.subprogress.emit(int(pct), str(message or ""))

        def on_done(result: dict) -> None:
            sig.finished.emit(result or {})

        start_installer_async(
            repair=repair,
            on_done=on_done,
            on_line=on_line,
            on_progress=on_progress,
            on_subprogress=on_subprogress,
        )

    def _start_rt(self) -> None:
        self._set_status(t("settings.local_starting"), "info")
        result = start_runtime(wait_online=25.0)
        if result.get("ok"):
            self._set_status(
                t("settings.local_runtime_on", url=result.get("base_url") or ""),
                "ok",
            )
        else:
            self._set_status(result.get("error") or "start failed", "fail")

    def _stop_rt(self) -> None:
        stop_runtime()
        self._set_status(t("settings.local_stopped"), "info")
