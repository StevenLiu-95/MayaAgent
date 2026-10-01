"""Settings panel (API / Agent / UI) plus top-level tools / help factories."""

from __future__ import annotations

from typing import Callable, Optional

from maya_agent import __app_name__, __version__
from maya_agent.i18n import init_from_config, list_languages, t
from maya_agent.llm.registry import create_provider, list_providers
from maya_agent.tools.registry import ensure_tools_loaded, get_tool, tools_by_category
from maya_agent.ui.combo_widgets import create_toolbar_combo
from maya_agent.ui.spin_widgets import create_toolbar_spin
from maya_agent.ui.palette import COLOR_TEXT
from maya_agent.utils.config import get_config
from maya_agent.utils.maya_compat import import_qt


def create_settings_panel(
    parent=None,
    *,
    on_saved: Optional[Callable[..., None]] = None,
):
    """
    Build settings QWidget with sub-tabs (模型与 API / Agent / 界面).
    on_saved(language_changed=False) — refresh main window after settings change.
    """
    init_from_config()
    QtCore, QtGui, QtWidgets, _ = import_qt()

    class SettingsPanel(QtWidgets.QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setObjectName("settingsPanel")
            self.cfg = get_config()
            self._on_saved = on_saved
            self._build()
            self._load()

        # ---- layout helpers -------------------------------------------------

        def _scroll_page(self) -> tuple:
            page = QtWidgets.QWidget()
            page.setObjectName("settingsPage")
            scroll = QtWidgets.QScrollArea()
            scroll.setObjectName("settingsScroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            scroll.setWidget(page)
            root = QtWidgets.QVBoxLayout(page)
            root.setContentsMargins(14, 14, 14, 14)
            root.setSpacing(14)
            root.setAlignment(QtCore.Qt.AlignTop)
            return scroll, root

        def _section(self, title: str, hint: str = "") -> tuple:
            box = QtWidgets.QFrame()
            box.setObjectName("settingsSection")
            lay = QtWidgets.QVBoxLayout(box)
            lay.setContentsMargins(14, 12, 14, 14)
            lay.setSpacing(10)

            head = QtWidgets.QVBoxLayout()
            head.setContentsMargins(0, 0, 0, 0)
            head.setSpacing(3)
            title_lbl = QtWidgets.QLabel(title)
            title_lbl.setObjectName("settingsSectionTitle")
            head.addWidget(title_lbl)
            if hint:
                hint_lbl = QtWidgets.QLabel(hint)
                hint_lbl.setObjectName("settingsSectionHint")
                hint_lbl.setWordWrap(True)
                head.addWidget(hint_lbl)
            lay.addLayout(head)
            return box, lay

        def _form(self, parent_layout) -> "QtWidgets.QFormLayout":
            form = QtWidgets.QFormLayout()
            form.setContentsMargins(0, 2, 0, 0)
            form.setHorizontalSpacing(14)
            form.setVerticalSpacing(10)
            form.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            form.setFormAlignment(QtCore.Qt.AlignTop)
            form.setFieldGrowthPolicy(
                QtWidgets.QFormLayout.ExpandingFieldsGrow
            )
            parent_layout.addLayout(form)
            return form

        def _field_label(self, text: str) -> "QtWidgets.QLabel":
            lbl = QtWidgets.QLabel(text)
            lbl.setObjectName("settingsFieldLabel")
            return lbl

        def _option_row(
            self, checkbox: "QtWidgets.QCheckBox", desc: str
        ) -> "QtWidgets.QWidget":
            row = QtWidgets.QWidget()
            row.setObjectName("settingsOptionRow")
            lay = QtWidgets.QVBoxLayout(row)
            lay.setContentsMargins(0, 2, 0, 2)
            lay.setSpacing(2)
            checkbox.setObjectName("settingsCheck")
            lay.addWidget(checkbox)
            desc_lbl = QtWidgets.QLabel(desc)
            desc_lbl.setObjectName("settingsOptionHint")
            desc_lbl.setWordWrap(True)
            # indent under checkbox text
            desc_lbl.setContentsMargins(22, 0, 0, 0)
            lay.addWidget(desc_lbl)
            return row

        def _stretch_end(self, layout) -> None:
            layout.addStretch(1)

        # ---- build ----------------------------------------------------------

        def _build(self) -> None:
            outer = QtWidgets.QVBoxLayout(self)
            outer.setContentsMargins(0, 6, 0, 0)
            outer.setSpacing(10)

            self.tabs = QtWidgets.QTabWidget()
            self.tabs.setObjectName("settingsTabs")
            self.tabs.setDocumentMode(True)
            outer.addWidget(self.tabs, 1)

            self._build_api_tab()
            self._build_agent_tab()
            self._build_ui_tab()

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

        def _build_api_tab(self) -> None:
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

            self._stretch_end(root)
            self.tabs.addTab(scroll, t("settings.tab.api"))

        def _build_agent_tab(self) -> None:
            scroll, root = self._scroll_page()

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
            self.max_rounds.setRange(1, 50)
            self.max_rounds.setFixedHeight(30)
            self.max_rounds.setFixedWidth(100)
            lform.addRow(self._field_label(t("settings.max_rounds")), self.max_rounds)
            root.addWidget(lim)

            self._stretch_end(root)
            self.tabs.addTab(scroll, t("settings.tab.agent"))

        def _build_ui_tab(self) -> None:
            scroll, root = self._scroll_page()

            lang, lang_lay = self._section(
                t("settings.section.language"),
                t("settings.section.language_hint"),
            )
            lform = self._form(lang_lay)
            self.language_combo = create_toolbar_combo()
            self.language_combo.setMinimumHeight(30)
            for code, label in list_languages():
                self.language_combo.addItem(label, code)
            lform.addRow(self._field_label(t("settings.language")), self.language_combo)
            root.addWidget(lang)

            typo, typo_lay = self._section(
                t("settings.section.appearance"),
                t("settings.section.appearance_hint"),
            )
            form = self._form(typo_lay)
            self.font_family = QtWidgets.QLineEdit()
            self.font_family.setMinimumHeight(30)
            self.font_family.setPlaceholderText(t("settings.font_ph"))
            self.ui_scale = create_toolbar_spin()
            self.ui_scale.setRange(75, 175)
            self.ui_scale.setSingleStep(5)
            self.ui_scale.setSuffix("%")
            self.ui_scale.setFixedHeight(30)
            self.ui_scale.setFixedWidth(110)
            self.ui_scale.setToolTip(t("settings.ui_scale_tip"))
            form.addRow(self._field_label(t("settings.font")), self.font_family)
            form.addRow(self._field_label(t("settings.ui_scale")), self.ui_scale)
            root.addWidget(typo)

            self._stretch_end(root)
            self.tabs.addTab(scroll, t("settings.tab.ui"))

        # ---- data -----------------------------------------------------------

        def _snapshot(self) -> tuple:
            """Serializable form state used for dirty comparison."""
            return (
                self.provider_combo.currentData(),
                self.model_combo.currentText().strip(),
                self.vision_policy.currentData(),
                self.api_key_edit.text(),
                self.base_url_edit.text().strip(),
                round(float(self.temp_spin.value()), 4),
                int(self.max_tokens_spin.value()),
                bool(self.auto_undo.isChecked()),
                bool(self.confirm_destructive.isChecked()),
                bool(self.stream_check.isChecked()),
                bool(self.show_thinking.isChecked()),
                bool(self.show_tools.isChecked()),
                int(self.max_rounds.value()),
                self.language_combo.currentData(),
                self.font_family.text().strip(),
                int(self.ui_scale.value()),
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
                self.temp_spin.valueChanged,
                self.max_tokens_spin.valueChanged,
                self.auto_undo.toggled,
                self.confirm_destructive.toggled,
                self.stream_check.toggled,
                self.show_thinking.toggled,
                self.show_tools.toggled,
                self.max_rounds.valueChanged,
                self.language_combo.currentIndexChanged,
                self.font_family.textChanged,
                self.ui_scale.valueChanged,
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

        def _clear_test_status(self, *_args) -> None:
            self._set_test_status("", "")

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
                lang = str(self.cfg.get("app.language", "zh-CN") or "zh-CN")
                lidx = self.language_combo.findData(lang)
                self.language_combo.setCurrentIndex(lidx if lidx >= 0 else 0)
                self.font_family.setText(
                    self.cfg.get("ui.font_family", "Microsoft YaHei UI")
                )
                self.ui_scale.setValue(self._resolve_ui_scale_pct())
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
            self.cfg.set("maya.auto_undo", self.auto_undo.isChecked())
            self.cfg.set(
                "maya.confirm_destructive", self.confirm_destructive.isChecked()
            )
            self.cfg.set("agent.stream", self.stream_check.isChecked())
            self.cfg.set("agent.show_thinking", self.show_thinking.isChecked())
            self.cfg.set("agent.show_tool_calls", self.show_tools.isChecked())
            self.cfg.set("maya.max_tool_rounds", self.max_rounds.value())
            old_lang = str(self.cfg.get("app.language", "zh-CN") or "zh-CN")
            new_lang = str(self.language_combo.currentData() or "zh-CN")
            self.cfg.set("app.language", new_lang)
            self.cfg.set("ui.font_family", self.font_family.text().strip())
            self.cfg.set("ui.ui_scale", int(self.ui_scale.value()))
            # Drop legacy key so old font_size no longer affects scale migration
            ui_data = self.cfg._data.get("ui")
            if isinstance(ui_data, dict):
                ui_data.pop("font_size", None)
            self.cfg.save_user()
            self._mark_clean()
            language_changed = old_lang != new_lang
            if language_changed:
                init_from_config()
            if self._on_saved:
                self._on_saved(language_changed=language_changed)
            if silent:
                self.save_hint.setText(t("settings.saved"))
            else:
                QtWidgets.QMessageBox.information(
                    self,
                    t("settings.saved_dialog_title"),
                    t("settings.saved_dialog_body"),
                )

        def _resolve_ui_scale_pct(self) -> int:
            """Prefer ui.ui_scale; migrate legacy ui.font_size (13px ≈ 100%)."""
            raw = self.cfg.get("ui.ui_scale")
            if raw is not None:
                try:
                    return max(75, min(175, int(raw)))
                except (TypeError, ValueError):
                    return 100
            old = self.cfg.get("ui.font_size")
            if old is not None:
                try:
                    return max(75, min(175, int(round(float(old) / 13 * 100))))
                except (TypeError, ValueError):
                    pass
            return 100

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
                "ok": "#5dca8a",
                "fail": "#e07070",
                "info": "#8a8a93",
            }
            color = colors.get(kind, "#8a8a93")
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

        def show_subtab(self, name: str) -> None:
            """Switch to a sub-tab by label, e.g. '模型与 API'."""
            for i in range(self.tabs.count()):
                if self.tabs.tabText(i) == name:
                    self.tabs.setCurrentIndex(i)
                    return

    return SettingsPanel(parent)


def create_tools_panel(
    parent=None,
    *,
    on_tool_use: Optional[Callable[[str], None]] = None,
):
    """Top-level tools browser: categories, params, double-click → chat."""
    QtCore, QtGui, QtWidgets, _ = import_qt()

    class ToolsPanel(QtWidgets.QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setObjectName("settingsPanel")
            self._on_tool_use = on_tool_use
            self._build()

        def _build(self) -> None:
            layout = QtWidgets.QVBoxLayout(self)
            layout.setContentsMargins(14, 14, 14, 14)
            layout.setSpacing(10)

            head = QtWidgets.QFrame()
            head.setObjectName("settingsSection")
            head_lay = QtWidgets.QVBoxLayout(head)
            head_lay.setContentsMargins(14, 12, 14, 12)
            head_lay.setSpacing(3)
            title = QtWidgets.QLabel(t("tab.tools"))
            title.setObjectName("settingsSectionTitle")
            tip = QtWidgets.QLabel(t("tools.hint"))
            tip.setObjectName("settingsSectionHint")
            tip.setWordWrap(True)
            head_lay.addWidget(title)
            head_lay.addWidget(tip)
            layout.addWidget(head)

            ensure_tools_loaded()
            self.tool_tree = QtWidgets.QTreeWidget()
            self.tool_tree.setObjectName("settingsToolTree")
            self.tool_tree.setHeaderHidden(True)
            self.tool_tree.setRootIsDecorated(True)
            self.tool_tree.setAnimated(True)
            self.tool_tree.setIndentation(16)
            self.tool_tree.setUniformRowHeights(True)
            self.tool_tree.setExpandsOnDoubleClick(False)

            cats = tools_by_category()
            for cat in sorted(cats.keys()):
                parent_item = QtWidgets.QTreeWidgetItem([cat])
                parent_item.setFlags(QtCore.Qt.ItemIsEnabled)
                font = parent_item.font(0)
                font.setBold(True)
                parent_item.setFont(0, font)
                parent_item.setForeground(0, QtGui.QColor("#b8c4d4"))
                for reg in sorted(cats[cat], key=lambda x: x.name):
                    child = QtWidgets.QTreeWidgetItem([reg.name])
                    child.setToolTip(0, reg.description)
                    child.setData(0, QtCore.Qt.UserRole, reg.name)
                    child.setForeground(0, QtGui.QColor(COLOR_TEXT))
                    parent_item.addChild(child)
                self.tool_tree.addTopLevelItem(parent_item)
                parent_item.setExpanded(True)

            self.tool_tree.itemDoubleClicked.connect(self._on_tool_double_click)
            self.tool_tree.currentItemChanged.connect(self._on_tool_select)
            layout.addWidget(self.tool_tree, 1)

            self.tool_desc = QtWidgets.QTextEdit()
            self.tool_desc.setObjectName("settingsToolDesc")
            self.tool_desc.setReadOnly(True)
            self.tool_desc.setFixedHeight(350)
            self.tool_desc.setPlaceholderText("选择工具查看说明与参数…")
            layout.addWidget(self.tool_desc)
            self.tool_list = self.tool_tree

        def _on_tool_select(self, current, _previous) -> None:
            if not current:
                return
            name = current.data(0, QtCore.Qt.UserRole)
            if not name:
                self.tool_desc.setPlainText("")
                return
            tool = get_tool(name)
            if tool:
                import json

                self.tool_desc.setPlainText(
                    f"{tool.name}\n{t('tools.category', category=tool.category)}\n\n"
                    f"{tool.description}\n\n"
                    f"{t('tools.params')}\n"
                    f"{json.dumps(tool.parameters, ensure_ascii=False, indent=2)}"
                )

        def _on_tool_double_click(self, item, _column) -> None:
            name = item.data(0, QtCore.Qt.UserRole)
            if name and self._on_tool_use:
                self._on_tool_use(name)

    return ToolsPanel(parent)


def create_help_panel(parent=None):
    """Top-level help page (same visual language as settings sections)."""
    QtCore, QtGui, QtWidgets, _ = import_qt()

    def _scroll_page():
        page = QtWidgets.QWidget()
        page.setObjectName("settingsPage")
        scroll = QtWidgets.QScrollArea()
        scroll.setObjectName("settingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        root = QtWidgets.QVBoxLayout(page)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(14)
        root.setAlignment(QtCore.Qt.AlignTop)
        return scroll, root

    def _section(title: str, hint: str = ""):
        box = QtWidgets.QFrame()
        box.setObjectName("settingsSection")
        lay = QtWidgets.QVBoxLayout(box)
        lay.setContentsMargins(14, 12, 14, 14)
        lay.setSpacing(10)
        head = QtWidgets.QVBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(3)
        title_lbl = QtWidgets.QLabel(title)
        title_lbl.setObjectName("settingsSectionTitle")
        head.addWidget(title_lbl)
        if hint:
            hint_lbl = QtWidgets.QLabel(hint)
            hint_lbl.setObjectName("settingsSectionHint")
            hint_lbl.setWordWrap(True)
            head.addWidget(hint_lbl)
        lay.addLayout(head)
        return box, lay

    def _add_help_lines(layout, lines, *, numbered: bool = False) -> None:
        for i, line in enumerate(lines, start=1):
            prefix = f"{i}.  " if numbered else "·  "
            row = QtWidgets.QLabel(f"{prefix}{line}")
            row.setObjectName("settingsHelpItem")
            row.setWordWrap(True)
            layout.addWidget(row)

    scroll, root = _scroll_page()

    intro = QtWidgets.QFrame()
    intro.setObjectName("settingsSection")
    intro_lay = QtWidgets.QVBoxLayout(intro)
    intro_lay.setContentsMargins(14, 14, 14, 14)
    intro_lay.setSpacing(8)

    title_row = QtWidgets.QHBoxLayout()
    title_row.setSpacing(10)
    title = QtWidgets.QLabel(__app_name__)
    title.setObjectName("settingsHelpTitle")
    ver = QtWidgets.QLabel(f"v{__version__}")
    ver.setObjectName("settingsHelpVersion")
    title_row.addWidget(title, 0)
    title_row.addWidget(ver, 0)
    title_row.addStretch(1)
    intro_lay.addLayout(title_row)

    blurb = QtWidgets.QLabel(t("help.blurb"))
    blurb.setObjectName("settingsHelpBody")
    blurb.setWordWrap(True)
    intro_lay.addWidget(blurb)
    root.addWidget(intro)

    quick, quick_lay = _section(t("help.quick.title"), t("help.quick.hint"))
    _add_help_lines(
        quick_lay,
        (
            t("help.quick.1"),
            t("help.quick.2"),
            t("help.quick.3"),
            t("help.quick.4"),
        ),
        numbered=True,
    )
    root.addWidget(quick)

    chat, chat_lay = _section(t("help.chat.title"), t("help.chat.hint"))
    _add_help_lines(
        chat_lay,
        (
            t("help.chat.1"),
            t("help.chat.2"),
            t("help.chat.3"),
            t("help.chat.4"),
            t("help.chat.5"),
            t("help.chat.6"),
            t("help.chat.7"),
            t("help.chat.8"),
            t("help.chat.9"),
        ),
    )
    root.addWidget(chat)

    settings, settings_lay = _section(
        t("help.settings.title"), t("help.settings.hint")
    )
    _add_help_lines(
        settings_lay,
        (
            t("help.settings.1"),
            t("help.settings.2"),
            t("help.settings.3"),
            t("help.settings.4"),
        ),
    )
    root.addWidget(settings)

    tools, tools_lay = _section(t("help.tools.title"), t("help.tools.hint"))
    tool_groups = (
        (
            "场景 scene",
            "get_scene_info（含 bbox/相机裁剪/材质分布）、list_selection、select_objects、rename_object、batch_rename、"
            "create_group、delete_objects、parent_objects、duplicate_objects、clean_scene、"
            "set_frame_range、capture_viewport（show_only/display_mode/look_at）、"
            "capture_viewport_views（临时相机自动清理）、render_still（静帧展示图）",
        ),
        (
            "建模 modeling",
            "create_primitive、create_primitives（批量落位）、arrange_objects（stack/align/grid_array）、"
            "combine_meshes、separate_meshes、boolean_meshes、extrude_faces、"
            "bevel_edges、smooth_mesh、reduce_mesh、mirror_geometry、center_pivot、freeze_transform、"
            "get_mesh_stats（支持组/层级聚合）、check_meshes（非流形等质量检查）",
        ),
        (
            "UV",
            "auto_unwrap_uv、layout_uv、check_uv_overlaps",
        ),
        (
            "绑骨 rigging",
            "list_skeleton_templates、create_skeleton_*（biped/ue5/cat/dragon 等 15 种）、"
            "create_skin_cage、bind_from_skin_cage、build_fk_ik_controls、auto_rig_character、"
            "list_skinned_meshes、bake_mesh_to_world、extract_skinned_geometry 等"
            "（adv_* 仅在已安装 AdvancedSkeleton 且用户明确要求时使用）",
        ),
        (
            "动画 animation",
            "set_keyframe、delete_keyframes、bake_animation、playblast、copy_animation",
        ),
        (
            "材质 materials",
            "create_material（返回 shader+shading_group）、assign_material、describe_material_attrs、assign_texture、list_materials",
        ),
        (
            "灯光 lighting",
            "create_light、create_three_point_lighting、create_environment_light（天光/环境光）",
        ),
        (
            "导入导出 export",
            "export_fbx、import_fbx、export_obj、export_usd、export_abc、save_scene、open_scene",
        ),
        (
            "游戏管线 utilities",
            "set_transform、create_lod_group、create_collision_mesh、apply_game_naming、reset_transform",
        ),
        (
            "网络检索 web",
            "web_search、fetch_webpage、search_images、fetch_image、fetch_images"
            "（按需查文档/规范与参考图；fetch_image* 仅视觉模型可用）",
        ),
        (
            "脚本 scripting",
            "execute_python（atomic 默认回滚）、execute_mel、generate_python_snippet",
        ),
    )
    for cat, names in tool_groups:
        cat_lbl = QtWidgets.QLabel(cat)
        cat_lbl.setObjectName("settingsHelpCat")
        cat_lbl.setWordWrap(True)
        tools_lay.addWidget(cat_lbl)
        names_lbl = QtWidgets.QLabel(names)
        names_lbl.setObjectName("settingsHelpItem")
        names_lbl.setWordWrap(True)
        tools_lay.addWidget(names_lbl)
    note = QtWidgets.QLabel(
        "·  标记为危险的工具（删除、解绑、打开场景、执行脚本等）在开启「危险操作前确认」时会弹窗。"
    )
    note.setObjectName("settingsHelpItem")
    note.setWordWrap(True)
    tools_lay.addWidget(note)
    root.addWidget(tools)

    rules, rules_lay = _section(
        "使用约定与安全",
        "Agent 会遵循下列约束，请按此预期使用。",
    )
    _add_help_lines(
        rules_lay,
        (
            "所有操作默认在当前已打开场景中进行；除非你明确要求，否则不会新建空场景",
            "意图含糊、缺参数或多种方案时，会先用选项向你确认再动手",
            "删除物体、覆盖导出、执行任意脚本等危险操作会先确认",
            "优先使用已注册工具；复杂逻辑才用 execute_python / execute_mel",
            "修改应可撤销：请保持「自动 Undo 块」开启，便于一轮一次回退",
        ),
    )
    root.addWidget(rules)

    more, more_lay = _section(
        "菜单与重载",
        "安装后可从 Maya 菜单或工具架打开。",
    )
    _add_help_lines(
        more_lay,
        (
            "菜单「Maya Agent」：打开面板、重新加载、关于",
            "修改插件代码后可用「重新加载」刷新；依赖或安装路径变更建议重跑 install.bat 并重启 Maya",
            "API Key 也可通过环境变量配置（如 DEEPSEEK_API_KEY、OPENAI_API_KEY、DASHSCOPE_API_KEY 等）",
        ),
    )
    root.addWidget(more)
    root.addStretch(1)

    wrap = QtWidgets.QWidget(parent)
    wrap.setObjectName("settingsPanel")
    wrap_lay = QtWidgets.QVBoxLayout(wrap)
    wrap_lay.setContentsMargins(0, 6, 0, 0)
    wrap_lay.setSpacing(0)
    wrap_lay.addWidget(scroll, 1)
    return wrap
