"""LLM / Meshy settings panel."""

from __future__ import annotations

from typing import Callable, Optional

from maya_agent.i18n import init_from_config, t
from maya_agent.llm.registry import create_provider, list_providers
from maya_agent.ui.combo_widgets import create_toolbar_combo
from maya_agent.ui.spin_widgets import create_toolbar_spin
from maya_agent.ui.qt_bind import QtCore, QtGui, QtWidgets
from maya_agent.ui.palette import COLOR_MUTED, COLOR_TEST_FAIL, COLOR_TEST_OK
from maya_agent.ui.settings.form_helpers import SettingsFormMixin
from maya_agent.utils.config import get_config

class SettingsPanel(SettingsFormMixin, QtWidgets.QWidget):
    def __init__(self, parent=None, *, on_saved: Optional[Callable[..., None]] = None):
        super().__init__(parent)
        self.setObjectName("settingsPanel")
        self.cfg = get_config()
        self._on_saved = on_saved
        self._build()
        self._load()

    # ---- layout helpers -------------------------------------------------

    def _build(self) -> None:
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 6, 0, 0)
        outer.setSpacing(10)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setObjectName("settingsTabs")
        self.tabs.setDocumentMode(True)
        outer.addWidget(self.tabs, 1)

        self._build_llm_tab()
        self._build_meshy_tab()
        self._build_local_tab()
        self._apply_no_wheel()

        footer = QtWidgets.QFrame()
        footer.setObjectName("settingsFooter")
        foot = QtWidgets.QHBoxLayout(footer)
        foot.setContentsMargins(0, 2, 0, 0)
        foot.setSpacing(10)
        self.save_hint = QtWidgets.QLabel(t("settings.autosave_hint"))
        self.save_hint.setObjectName("settingsSectionHint")
        foot.addWidget(self.save_hint, 1)
        self.reset_btn = QtWidgets.QPushButton(t("settings.reset"))
        self.reset_btn.setObjectName("secondaryBtn")
        self.reset_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.reset_btn.setMinimumWidth(108)
        self.reset_btn.setMinimumHeight(32)
        self.reset_btn.setToolTip(t("settings.reset_tip"))
        self.reset_btn.clicked.connect(self._restore_defaults)
        foot.addWidget(self.reset_btn, 0, QtCore.Qt.AlignRight)
        outer.addWidget(footer)

        self._baseline = None
        self._suppress_dirty = False
        self._autosave_timer = QtCore.QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(400)
        self._autosave_timer.timeout.connect(self._autosave_now)
        self._wire_dirty_tracking()

    def _build_llm_tab(self) -> None:
        scroll, root = self._scroll_page()

        conn, conn_lay = self._section(
            t("settings.section.connection"),
            t("settings.section.connection_hint"),
        )
        form = self._form(conn_lay)

        self.provider_combo = create_toolbar_combo()
        self.provider_combo.setMinimumHeight(30)
        self.model_combo = create_toolbar_combo(editable=True)
        self.model_combo.setMinimumHeight(30)
        self.vision_policy = create_toolbar_combo()
        self.vision_policy.setMinimumHeight(30)
        self.vision_policy.addItem(t("settings.vision_auto"), "auto")
        self.vision_policy.addItem(t("settings.vision_on"), "on")
        self.vision_policy.addItem(t("settings.vision_off"), "off")
        self.vision_policy.setToolTip(t("settings.vision_tip"))
        self.api_key_edit = QtWidgets.QLineEdit()
        self.api_key_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self.api_key_edit.setPlaceholderText(t("settings.api_key_ph"))
        self.api_key_edit.setMinimumHeight(30)
        self.base_url_edit = QtWidgets.QLineEdit()
        self.base_url_edit.setMinimumHeight(30)
        self.base_url_edit.setPlaceholderText("https://api.example.com/v1")

        for p in list_providers():
            self.provider_combo.addItem(p["label"], p["id"])
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)

        form.addRow(self._field_label(t("settings.provider")), self.provider_combo)
        form.addRow(self._field_label(t("settings.model")), self.model_combo)
        form.addRow(self._field_label(t("settings.vision")), self.vision_policy)
        form.addRow(self._field_label(t("settings.api_key")), self.api_key_edit)
        form.addRow(self._field_label(t("settings.base_url")), self.base_url_edit)

        actions = QtWidgets.QHBoxLayout()
        actions.setContentsMargins(0, 4, 0, 0)
        actions.setSpacing(10)
        self.test_status = QtWidgets.QLabel("")
        self.test_status.setObjectName("testConnStatus")
        self.test_status.setWordWrap(True)
        self.test_status.setMinimumWidth(0)
        self.test_status.setAlignment(
            QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter
        )
        self.test_status.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred
        )
        actions.addWidget(self.test_status, 1)
        self.test_btn = QtWidgets.QPushButton(t("settings.test"))
        self.test_btn.setObjectName("secondaryBtn")
        self.test_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.test_btn.setMinimumWidth(96)
        self.test_btn.setMinimumHeight(30)
        self.test_btn.clicked.connect(self._test_connection)
        actions.addWidget(self.test_btn, 0)
        conn_lay.addLayout(actions)
        root.addWidget(conn)

        gen, gen_lay = self._section(
            t("settings.section.gen"),
            t("settings.section.gen_hint"),
        )
        gform = self._form(gen_lay)
        self.temp_spin = create_toolbar_spin(decimal=True)
        self.temp_spin.setRange(0, 2)
        self.temp_spin.setSingleStep(0.1)
        self.temp_spin.setDecimals(2)
        self.temp_spin.setFixedHeight(30)
        self.temp_spin.setFixedWidth(112)
        self.max_tokens_spin = create_toolbar_spin()
        self.max_tokens_spin.setRange(256, 128000)
        self.max_tokens_spin.setSingleStep(256)
        self.max_tokens_spin.setFixedHeight(30)
        self.max_tokens_spin.setFixedWidth(132)
        self.max_tokens_spin.setToolTip(t("settings.max_tokens_tip"))
        gform.addRow(self._field_label("Temperature"), self.temp_spin)
        gform.addRow(self._field_label("Max Tokens"), self.max_tokens_spin)
        root.addWidget(gen)

        beh, beh_lay = self._section(
            t("settings.section.behavior"),
            t("settings.section.behavior_hint"),
        )
        self.auto_undo = QtWidgets.QCheckBox(t("settings.auto_undo"))
        self.confirm_destructive = QtWidgets.QCheckBox(
            t("settings.confirm_destructive")
        )
        self.stream_check = QtWidgets.QCheckBox(t("settings.stream"))
        self.show_thinking = QtWidgets.QCheckBox(t("settings.show_thinking"))
        self.show_tools = QtWidgets.QCheckBox(t("settings.show_tools"))

        beh_lay.addWidget(
            self._option_row(self.auto_undo, t("settings.auto_undo_hint"))
        )
        beh_lay.addWidget(
            self._option_row(
                self.confirm_destructive, t("settings.confirm_destructive_hint")
            )
        )
        beh_lay.addWidget(
            self._option_row(self.stream_check, t("settings.stream_hint"))
        )
        beh_lay.addWidget(
            self._option_row(
                self.show_thinking, t("settings.show_thinking_hint")
            )
        )
        beh_lay.addWidget(
            self._option_row(self.show_tools, t("settings.show_tools_hint"))
        )
        root.addWidget(beh)

        lim, lim_lay = self._section(
            t("settings.section.limits"),
            t("settings.section.limits_hint"),
        )
        lform = self._form(lim_lay)
        self.max_rounds = create_toolbar_spin()
        self.max_rounds.setRange(1, 100)
        self.max_rounds.setFixedHeight(30)
        self.max_rounds.setFixedWidth(100)
        lform.addRow(self._field_label(t("settings.max_rounds")), self.max_rounds)
        root.addWidget(lim)

        self._stretch_end(root)
        self.tabs.addTab(scroll, t("settings.tab.llm"))

    def _build_meshy_tab(self) -> None:
        scroll, root = self._scroll_page()

        meshy, meshy_lay = self._section(
            t("settings.section.meshy"),
            t("settings.section.meshy_hint"),
        )
        self.meshy_enabled = QtWidgets.QCheckBox(t("settings.meshy_enabled"))
        meshy_lay.addWidget(
            self._option_row(
                self.meshy_enabled, t("settings.meshy_enabled_hint")
            )
        )
        mform = self._form(meshy_lay)
        self.meshy_api_key_edit = QtWidgets.QLineEdit()
        self.meshy_api_key_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self.meshy_api_key_edit.setPlaceholderText(t("settings.meshy_api_key_ph"))
        self.meshy_api_key_edit.setMinimumHeight(30)
        mform.addRow(
            self._field_label(t("settings.meshy_api_key")),
            self.meshy_api_key_edit,
        )
        meshy_actions = QtWidgets.QHBoxLayout()
        meshy_actions.setContentsMargins(0, 4, 0, 0)
        meshy_actions.setSpacing(10)
        self.meshy_test_status = QtWidgets.QLabel("")
        self.meshy_test_status.setObjectName("testConnStatus")
        self.meshy_test_status.setWordWrap(True)
        self.meshy_test_status.setAlignment(
            QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter
        )
        self.meshy_test_status.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred
        )
        meshy_actions.addWidget(self.meshy_test_status, 1)
        self.meshy_test_btn = QtWidgets.QPushButton(t("settings.meshy_test"))
        self.meshy_test_btn.setObjectName("secondaryBtn")
        self.meshy_test_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.meshy_test_btn.setMinimumWidth(96)
        self.meshy_test_btn.setMinimumHeight(30)
        self.meshy_test_btn.clicked.connect(self._test_meshy)
        meshy_actions.addWidget(self.meshy_test_btn, 0)
        meshy_lay.addLayout(meshy_actions)
        root.addWidget(meshy)

        self._stretch_end(root)
        self.tabs.addTab(scroll, t("settings.tab.meshy"))

    def _build_local_tab(self) -> None:
        from maya_agent.ui.settings.local_panel import LocalModelsPage

        self.local_page = LocalModelsPage(self, on_saved=self._on_saved)
        self.tabs.addTab(self.local_page, t("settings.tab.local"))

    # ---- data -----------------------------------------------------------

    def _snapshot(self) -> tuple:
        """Serializable form state used for dirty comparison."""
        return (
            self.provider_combo.currentData(),
            self.model_combo.currentText().strip(),
            self.vision_policy.currentData(),
            self.api_key_edit.text(),
            self.base_url_edit.text().strip(),
            bool(self.meshy_enabled.isChecked()),
            self.meshy_api_key_edit.text(),
            round(float(self.temp_spin.value()), 4),
            int(self.max_tokens_spin.value()),
            bool(self.auto_undo.isChecked()),
            bool(self.confirm_destructive.isChecked()),
            bool(self.stream_check.isChecked()),
            bool(self.show_thinking.isChecked()),
            bool(self.show_tools.isChecked()),
            int(self.max_rounds.value()),
        )

    def _mark_clean(self) -> None:
        self._baseline = self._snapshot()
        self.save_hint.setText(t("settings.autosave_hint"))

    def _schedule_autosave(self, *_args) -> None:
        if self._suppress_dirty or self._baseline is None:
            return
        if self._snapshot() == self._baseline:
            self.save_hint.setText(t("settings.autosave_hint"))
            return
        self.save_hint.setText(t("settings.saving"))
        self._autosave_timer.start()

    def _autosave_now(self) -> None:
        if self._suppress_dirty or self._baseline is None:
            return
        if self._snapshot() == self._baseline:
            self.save_hint.setText(t("settings.autosave_hint"))
            return
        self._save(silent=True)

    def _wire_dirty_tracking(self) -> None:
        # Combos / spins / checks: debounce via same timer (short delay is fine)
        for sig in (
            self.provider_combo.currentIndexChanged,
            self.model_combo.currentIndexChanged,
            self.model_combo.editTextChanged,
            self.vision_policy.currentIndexChanged,
            self.api_key_edit.textChanged,
            self.base_url_edit.textChanged,
            self.meshy_enabled.toggled,
            self.meshy_api_key_edit.textChanged,
            self.temp_spin.valueChanged,
            self.max_tokens_spin.valueChanged,
            self.auto_undo.toggled,
            self.confirm_destructive.toggled,
            self.stream_check.toggled,
            self.show_thinking.toggled,
            self.show_tools.toggled,
            self.max_rounds.valueChanged,
        ):
            sig.connect(self._schedule_autosave)
        # Connection fields change → clear stale test result
        for sig in (
            self.provider_combo.currentIndexChanged,
            self.model_combo.currentIndexChanged,
            self.model_combo.editTextChanged,
            self.api_key_edit.textChanged,
            self.base_url_edit.textChanged,
        ):
            sig.connect(self._clear_test_status)
        self.meshy_api_key_edit.textChanged.connect(self._clear_meshy_test_status)
        self.meshy_enabled.toggled.connect(self._clear_meshy_test_status)

    def _clear_test_status(self, *_args) -> None:
        self._set_test_status("", "")

    def _clear_meshy_test_status(self, *_args) -> None:
        self._set_meshy_test_status("", "")

    def _on_provider_changed(self) -> None:
        pid = self.provider_combo.currentData()
        pconf = self.cfg.get(f"providers.{pid}", {}) or {}
        self.model_combo.clear()
        for m in pconf.get("models") or []:
            self.model_combo.addItem(m)
        self.model_combo.setCurrentText(pconf.get("default_model", ""))
        policy = str(pconf.get("vision_policy") or "auto")
        pidx = self.vision_policy.findData(policy)
        self.vision_policy.setCurrentIndex(pidx if pidx >= 0 else 0)
        self.base_url_edit.setText(pconf.get("base_url", ""))
        self.api_key_edit.setText(self.cfg.get_api_key(pid))
        self._schedule_autosave()

    def _load(self) -> None:
        self._suppress_dirty = True
        try:
            if self._autosave_timer.isActive():
                self._autosave_timer.stop()
            active = self.cfg.get("llm.active_provider", "deepseek")
            idx = self.provider_combo.findData(active)
            if idx >= 0:
                self.provider_combo.setCurrentIndex(idx)
            self._on_provider_changed()
            self.temp_spin.setValue(float(self.cfg.get("llm.temperature", 0.3)))
            self.max_tokens_spin.setValue(int(self.cfg.get("llm.max_tokens", 8192)))
            self.auto_undo.setChecked(bool(self.cfg.get("maya.auto_undo", True)))
            self.confirm_destructive.setChecked(
                bool(self.cfg.get("maya.confirm_destructive", True))
            )
            self.stream_check.setChecked(bool(self.cfg.get("agent.stream", True)))
            self.show_thinking.setChecked(
                bool(self.cfg.get("agent.show_thinking", True))
            )
            self.show_tools.setChecked(
                bool(self.cfg.get("agent.show_tool_calls", True))
            )
            self.max_rounds.setValue(int(self.cfg.get("maya.max_tool_rounds", 30)))
            self.meshy_enabled.setChecked(bool(self.cfg.get("meshy.enabled", True)))
            self.meshy_api_key_edit.setText(self.cfg.get_api_key("meshy"))
        finally:
            self._suppress_dirty = False
        self._mark_clean()

    def reload_from_config(self) -> None:
        self.cfg.reload()
        self._load()

    def _save(self, *, silent: bool = False) -> None:
        pid = self.provider_combo.currentData()
        model = self.model_combo.currentText().strip()
        self.cfg.set("llm.active_provider", pid)
        self.cfg.set("llm.temperature", self.temp_spin.value())
        self.cfg.set("llm.max_tokens", self.max_tokens_spin.value())
        self.cfg.set(f"providers.{pid}.default_model", model)
        self.cfg.set(
            f"providers.{pid}.vision_policy",
            self.vision_policy.currentData() or "auto",
        )
        self.cfg.set(
            f"providers.{pid}.base_url", self.base_url_edit.text().strip()
        )
        self.cfg.set_api_key(pid, self.api_key_edit.text().strip())
        old_meshy_key = self.cfg.get_api_key("meshy")
        new_meshy_key = self.meshy_api_key_edit.text().strip()
        self.cfg.set("meshy.enabled", self.meshy_enabled.isChecked())
        self.cfg.set_api_key("meshy", new_meshy_key)
        if new_meshy_key != old_meshy_key:
            try:
                from maya_agent.tools.meshy_client import clear_meshy_key_validity

                clear_meshy_key_validity()
            except Exception:
                pass
        self.cfg.set("maya.auto_undo", self.auto_undo.isChecked())
        self.cfg.set(
            "maya.confirm_destructive", self.confirm_destructive.isChecked()
        )
        self.cfg.set("agent.stream", self.stream_check.isChecked())
        self.cfg.set("agent.show_thinking", self.show_thinking.isChecked())
        self.cfg.set("agent.show_tool_calls", self.show_tools.isChecked())
        self.cfg.set("maya.max_tool_rounds", self.max_rounds.value())
        self.cfg.save_user()
        self._mark_clean()
        if self._on_saved:
            self._on_saved(language_changed=False)
        if silent:
            self.save_hint.setText(t("settings.saved"))
        else:
            QtWidgets.QMessageBox.information(
                self,
                t("settings.saved_dialog_title"),
                t("settings.saved_dialog_body"),
            )

    def _restore_defaults(self) -> None:
        reply = QtWidgets.QMessageBox.question(
            self,
            t("settings.reset_title"),
            t("settings.reset_body"),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        if self._autosave_timer.isActive():
            self._autosave_timer.stop()
        old_lang = str(self.cfg.get("app.language", "zh-CN") or "zh-CN")
        self.cfg.reset_user_settings()
        init_from_config()
        self._load()
        new_lang = str(self.cfg.get("app.language", "zh-CN") or "zh-CN")
        if self._on_saved:
            self._on_saved(language_changed=(old_lang != new_lang))
        self.save_hint.setText(t("settings.reset_done"))

    def _set_test_status(self, text: str, kind: str = "") -> None:
        """Inline connection test feedback. kind: ok | fail | info | ''."""
        label = getattr(self, "test_status", None)
        if label is None:
            return
        label.setText(text or "")
        colors = {
            "ok": COLOR_TEST_OK,
            "fail": COLOR_TEST_FAIL,
            "info": COLOR_MUTED,
        }
        color = colors.get(kind, COLOR_MUTED)
        label.setStyleSheet(
            f"QLabel#testConnStatus {{ color: {color}; font-size: 12px; "
            f"background: transparent; border: none; padding: 0; }}"
        )

    def _set_meshy_test_status(self, text: str, kind: str = "") -> None:
        label = getattr(self, "meshy_test_status", None)
        if label is None:
            return
        label.setText(text or "")
        colors = {
            "ok": COLOR_TEST_OK,
            "fail": COLOR_TEST_FAIL,
            "info": COLOR_MUTED,
        }
        color = colors.get(kind, COLOR_MUTED)
        label.setStyleSheet(
            f"QLabel#testConnStatus {{ color: {color}; font-size: 12px; "
            f"background: transparent; border: none; padding: 0; }}"
        )

    def _test_connection(self) -> None:
        pid = self.provider_combo.currentData()
        model = self.model_combo.currentText().strip()
        key = self.api_key_edit.text().strip()
        base = self.base_url_edit.text().strip()
        self._set_test_status(t("settings.test_running"), "info")
        btn = getattr(self, "test_btn", None)
        if btn is not None:
            btn.setEnabled(False)
        try:
            # Let the label paint before a blocking network call
            QtWidgets.QApplication.processEvents()
            provider = create_provider(
                pid, model=model, api_key=key or None, base_url=base or None
            )
            result = provider.test_connection()
            if result.get("ok"):
                preview = (result.get("preview") or "").strip()
                msg = "连接成功"
                if preview:
                    one_line = " ".join(preview.split())
                    if len(one_line) > 48:
                        one_line = one_line[:48] + "…"
                    msg = f"连接成功 · {one_line}"
                self._set_test_status(msg, "ok")
            else:
                err = (result.get("error") or "未知错误").strip()
                one_line = " ".join(err.split())
                if len(one_line) > 72:
                    one_line = one_line[:72] + "…"
                self._set_test_status(f"连接失败 · {one_line}", "fail")
        except Exception as e:
            err = " ".join(str(e).split())
            if len(err) > 72:
                err = err[:72] + "…"
            self._set_test_status(f"连接失败 · {err}", "fail")
        finally:
            if btn is not None:
                btn.setEnabled(True)

    def _test_meshy(self) -> None:
        key = self.meshy_api_key_edit.text().strip()
        enabled = self.meshy_enabled.isChecked()
        self._set_meshy_test_status(t("settings.meshy_test_running"), "info")
        btn = getattr(self, "meshy_test_btn", None)
        if btn is not None:
            btn.setEnabled(False)
        try:
            QtWidgets.QApplication.processEvents()
            if not enabled:
                self._set_meshy_test_status("Meshy 已关闭", "fail")
                return
            # Persist key first so MeshyClient can read it
            if key:
                self.cfg.set_api_key("meshy", key)
            self.cfg.set("meshy.enabled", True)
            from maya_agent.tools.meshy_client import MeshyClient, MeshyError

            try:
                data = MeshyClient(api_key=key or None).balance()
            except MeshyError as e:
                from maya_agent.tools.meshy_client import mark_meshy_key_invalid

                if getattr(e, "status_code", 0) == 401 or "401" in str(e):
                    mark_meshy_key_invalid(key or None)
                err = " ".join(str(e).split())
                if len(err) > 72:
                    err = err[:72] + "…"
                self._set_meshy_test_status(f"连接失败 · {err}", "fail")
                return
            from maya_agent.tools.meshy_client import mark_meshy_key_valid

            mark_meshy_key_valid(key or None)
            # Balance payload varies; show a short summary
            preview = ""
            if isinstance(data, dict):
                for k in (
                    "balance",
                    "credits",
                    "remaining_credits",
                    "available_credits",
                ):
                    if k in data and data[k] is not None:
                        preview = f"{k}={data[k]}"
                        break
                if not preview:
                    preview = ", ".join(
                        f"{k}={data[k]}" for k in list(data.keys())[:3]
                    )
            msg = "连接成功"
            if preview:
                one = " ".join(str(preview).split())
                if len(one) > 48:
                    one = one[:48] + "…"
                msg = f"连接成功 · {one}"
            self._set_meshy_test_status(msg, "ok")
        except Exception as e:
            err = " ".join(str(e).split())
            if len(err) > 72:
                err = err[:72] + "…"
            self._set_meshy_test_status(f"连接失败 · {err}", "fail")
        finally:
            if btn is not None:
                btn.setEnabled(True)

    def show_subtab(self, name: str) -> None:
        """Switch to a sub-tab by label, e.g. 'LLM'."""
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == name:
                self.tabs.setCurrentIndex(i)
                return


def create_settings_panel(parent=None, *, on_saved=None):
    init_from_config()
    return SettingsPanel(parent, on_saved=on_saved)
