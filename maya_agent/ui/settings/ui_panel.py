"""UI / language / temp-dir / MCP / ADV settings panel."""

from __future__ import annotations

from typing import Callable, Optional

from maya_agent.i18n import init_from_config, list_languages, t
from maya_agent.ui.combo_widgets import create_toolbar_combo
from maya_agent.ui.spin_widgets import create_toolbar_spin
from maya_agent.ui.qt_bind import QtCore, QtGui, QtWidgets
from maya_agent.ui.palette import COLOR_MUTED, COLOR_TEST_FAIL, COLOR_TEST_OK
from maya_agent.ui.settings.config_defaults import ConfigDefaults
from maya_agent.ui.settings.form_helpers import SettingsFormMixin
from maya_agent.ui.settings.ui_scale import _resolve_ui_scale_pct
from maya_agent.utils.config import get_config
from maya_agent.utils.paths import default_agent_temp_root

class UiPanel(SettingsFormMixin, QtWidgets.QWidget):
    def __init__(self, parent=None, *, on_saved: Optional[Callable[..., None]] = None):
        super().__init__(parent)
        self.setObjectName("settingsPanel")
        self.cfg = get_config()
        self._on_saved = on_saved
        self._build()
        self._load()

    def _build(self) -> None:
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 6, 0, 0)
        outer.setSpacing(10)

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
        self.font_family = create_toolbar_combo(editable=True)
        self.font_family.setMinimumHeight(30)
        self.font_family.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        editor = self.font_family.lineEdit()
        if editor is not None:
            editor.setPlaceholderText(t("settings.font_ph"))
        self._populate_font_families()
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

        temp, temp_lay = self._section(
            t("settings.section.temp_dir"),
            t("settings.section.temp_dir_hint"),
        )
        tform = self._form(temp_lay)
        temp_row = QtWidgets.QWidget()
        temp_row_lay = QtWidgets.QHBoxLayout(temp_row)
        temp_row_lay.setContentsMargins(0, 0, 0, 0)
        temp_row_lay.setSpacing(8)
        self.temp_dir_edit = QtWidgets.QLineEdit()
        self.temp_dir_edit.setMinimumHeight(30)
        self.temp_dir_edit.setPlaceholderText(
            str(default_agent_temp_root()).replace("\\", "/")
        )
        self.temp_dir_edit.setToolTip(t("settings.temp_dir_tip"))
        self.temp_dir_browse = QtWidgets.QPushButton(t("settings.temp_dir_browse"))
        self.temp_dir_browse.setObjectName("secondaryBtn")
        self.temp_dir_browse.setCursor(QtCore.Qt.PointingHandCursor)
        self.temp_dir_browse.setMinimumHeight(30)
        self.temp_dir_browse.setMinimumWidth(72)
        self.temp_dir_browse.clicked.connect(self._browse_temp_dir)
        temp_row_lay.addWidget(self.temp_dir_edit, 1)
        temp_row_lay.addWidget(self.temp_dir_browse, 0)
        tform.addRow(self._field_label(t("settings.temp_dir")), temp_row)
        root.addWidget(temp)

        adv, adv_lay = self._section(
            t("settings.section.adv"),
            t("settings.section.adv_hint"),
        )
        aform = self._form(adv_lay)
        self.adv_path_edit = QtWidgets.QLineEdit()
        self.adv_path_edit.setMinimumHeight(30)
        self.adv_path_edit.setPlaceholderText(t("settings.adv_path_ph"))
        self.adv_path_edit.setToolTip(t("settings.adv_path_tip"))
        self.adv_path_browse = QtWidgets.QPushButton(t("settings.adv_path_browse"))
        self.adv_path_browse.setObjectName("secondaryBtn")
        self.adv_path_browse.setCursor(QtCore.Qt.PointingHandCursor)
        self.adv_path_browse.setMinimumHeight(30)
        self.adv_path_browse.setMinimumWidth(72)
        self.adv_path_browse.clicked.connect(self._browse_adv_path)
        adv_row = QtWidgets.QWidget()
        adv_row_lay = QtWidgets.QHBoxLayout(adv_row)
        adv_row_lay.setContentsMargins(0, 0, 0, 0)
        adv_row_lay.setSpacing(8)
        adv_row_lay.addWidget(self.adv_path_edit, 1)
        adv_row_lay.addWidget(self.adv_path_browse, 0)
        aform.addRow(self._field_label(t("settings.adv_path")), adv_row)
        adv_actions = QtWidgets.QHBoxLayout()
        adv_actions.setContentsMargins(0, 4, 0, 0)
        adv_actions.setSpacing(10)
        self.adv_status = QtWidgets.QLabel("")
        self.adv_status.setObjectName("testConnStatus")
        self.adv_status.setWordWrap(True)
        self.adv_status.setAlignment(
            QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter
        )
        self.adv_status.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred
        )
        adv_actions.addWidget(self.adv_status, 1)
        self.adv_detect_btn = QtWidgets.QPushButton(t("settings.adv_detect"))
        self.adv_detect_btn.setObjectName("secondaryBtn")
        self.adv_detect_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.adv_detect_btn.setMinimumWidth(96)
        self.adv_detect_btn.setMinimumHeight(30)
        self.adv_detect_btn.clicked.connect(self._detect_adv)
        adv_actions.addWidget(self.adv_detect_btn, 0)
        adv_lay.addLayout(adv_actions)
        root.addWidget(adv)

        bridge, bridge_lay = self._section(
            t("settings.section.bridge"),
            t("settings.section.bridge_hint"),
        )
        self.bridge_enabled = QtWidgets.QCheckBox(t("settings.bridge_enabled"))
        self.bridge_auto_start = QtWidgets.QCheckBox(t("settings.bridge_auto_start"))
        bridge_lay.addWidget(self.bridge_enabled)
        bridge_lay.addWidget(self.bridge_auto_start)
        bform = self._form(bridge_lay)
        self.bridge_port = create_toolbar_spin()
        self.bridge_port.setRange(1024, 65535)
        self.bridge_port.setFixedHeight(30)
        self.bridge_port.setFixedWidth(110)
        self.bridge_port_auto = QtWidgets.QCheckBox(t("settings.bridge_port_auto"))
        self.bridge_confirm = create_toolbar_combo()
        self.bridge_confirm.setMinimumHeight(30)
        self.bridge_confirm.addItem(t("settings.bridge_confirm_dialog"), "maya_dialog")
        self.bridge_confirm.addItem(t("settings.bridge_confirm_allow"), "allow")
        self.bridge_share = QtWidgets.QCheckBox(t("settings.bridge_share_agent"))
        bform.addRow(self._field_label(t("settings.bridge_port")), self.bridge_port)
        bridge_lay.addWidget(self.bridge_port_auto)
        bform.addRow(
            self._field_label(t("settings.bridge_confirm")), self.bridge_confirm
        )
        bridge_lay.addWidget(self.bridge_share)
        bridge_actions = QtWidgets.QHBoxLayout()
        bridge_actions.setContentsMargins(0, 4, 0, 0)
        bridge_actions.setSpacing(8)
        self.bridge_status = QtWidgets.QLabel("")
        self.bridge_status.setObjectName("testConnStatus")
        self.bridge_status.setWordWrap(True)
        self.bridge_status.setAlignment(
            QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter
        )
        self.bridge_status.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred
        )
        bridge_actions.addWidget(self.bridge_status, 1)
        self.bridge_start_btn = QtWidgets.QPushButton(t("settings.bridge_start"))
        self.bridge_start_btn.setObjectName("secondaryBtn")
        self.bridge_start_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.bridge_start_btn.setMinimumHeight(30)
        self.bridge_start_btn.clicked.connect(self._bridge_start)
        self.bridge_stop_btn = QtWidgets.QPushButton(t("settings.bridge_stop"))
        self.bridge_stop_btn.setObjectName("secondaryBtn")
        self.bridge_stop_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.bridge_stop_btn.setMinimumHeight(30)
        self.bridge_stop_btn.clicked.connect(self._bridge_stop)
        self.bridge_copy_btn = QtWidgets.QPushButton(t("settings.bridge_copy_mcp"))
        self.bridge_copy_btn.setObjectName("secondaryBtn")
        self.bridge_copy_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.bridge_copy_btn.setMinimumHeight(30)
        self.bridge_copy_btn.clicked.connect(self._bridge_copy_mcp)
        bridge_actions.addWidget(self.bridge_start_btn, 0)
        bridge_actions.addWidget(self.bridge_stop_btn, 0)
        bridge_actions.addWidget(self.bridge_copy_btn, 0)
        bridge_lay.addLayout(bridge_actions)
        root.addWidget(bridge)

        rules, rules_lay = self._section(
            t("rules.section"),
            t("rules.section_hint"),
        )
        self.user_rules_enabled = QtWidgets.QCheckBox(t("rules.enabled"))
        self.user_rules_enabled.setToolTip(t("rules.enabled_tip"))
        rules_lay.addWidget(self.user_rules_enabled)

        # Top: rule list + actions. Bottom: editor. Vertical stack fits narrow panels.
        self.rules_list = QtWidgets.QListWidget()
        self.rules_list.setObjectName("rulesList")
        self.rules_list.setMinimumHeight(100)
        self.rules_list.setMaximumHeight(160)
        self.rules_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.rules_list.currentItemChanged.connect(self._on_rule_selected)
        rules_lay.addWidget(self.rules_list)

        list_btns = QtWidgets.QHBoxLayout()
        list_btns.setSpacing(6)
        self.rules_new_btn = QtWidgets.QPushButton(t("rules.new"))
        self.rules_new_btn.setObjectName("secondaryBtn")
        self.rules_new_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.rules_new_btn.setMinimumHeight(28)
        self.rules_new_btn.clicked.connect(self._rules_new)
        self.rules_refresh_btn = QtWidgets.QPushButton(t("rules.refresh"))
        self.rules_refresh_btn.setObjectName("secondaryBtn")
        self.rules_refresh_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.rules_refresh_btn.setMinimumHeight(28)
        self.rules_refresh_btn.clicked.connect(self._rules_reload)
        self.rules_open_btn = QtWidgets.QPushButton(t("rules.open_dir"))
        self.rules_open_btn.setObjectName("secondaryBtn")
        self.rules_open_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.rules_open_btn.setMinimumHeight(28)
        self.rules_open_btn.clicked.connect(self._rules_open_dir)
        list_btns.addWidget(self.rules_new_btn)
        list_btns.addWidget(self.rules_refresh_btn)
        list_btns.addWidget(self.rules_open_btn)
        list_btns.addStretch(1)
        rules_lay.addLayout(list_btns)

        self._rules_status = QtWidgets.QLabel("")
        self._rules_status.setObjectName("settingsSectionHint")
        self._rules_status.setWordWrap(True)
        rules_lay.addWidget(self._rules_status)

        self.rules_title_edit = QtWidgets.QLineEdit()
        self.rules_title_edit.setMinimumHeight(30)
        self.rules_title_edit.setPlaceholderText(t("rules.title_ph"))
        self.rules_title_edit.textChanged.connect(self._on_rule_editor_changed)
        rules_lay.addWidget(self.rules_title_edit)
        self.rules_content_edit = QtWidgets.QPlainTextEdit()
        self.rules_content_edit.setObjectName("rulesEditor")
        self.rules_content_edit.setMinimumHeight(120)
        self.rules_content_edit.setPlaceholderText(t("rules.content_ph"))
        self.rules_content_edit.textChanged.connect(self._on_rule_editor_changed)
        rules_lay.addWidget(self.rules_content_edit)
        self.rules_file_hint = QtWidgets.QLabel(t("rules.file_readonly"))
        self.rules_file_hint.setObjectName("settingsSectionHint")
        self.rules_file_hint.setWordWrap(True)
        self.rules_file_hint.hide()
        rules_lay.addWidget(self.rules_file_hint)
        save_row = QtWidgets.QHBoxLayout()
        save_row.addStretch(1)
        self.rules_save_btn = QtWidgets.QPushButton(t("rules.save"))
        self.rules_save_btn.setObjectName("secondaryBtn")
        self.rules_save_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.rules_save_btn.setMinimumHeight(28)
        self.rules_save_btn.clicked.connect(self._rules_save_current)
        save_row.addWidget(self.rules_save_btn)
        rules_lay.addLayout(save_row)
        root.addWidget(rules)

        self._rules_by_id = {}
        self._current_rule_id = None
        self._loading_rule = False

        root.addStretch(1)

        outer.addWidget(scroll, 1)
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
        self.reset_btn.setToolTip(t("settings.reset_ui_tip"))
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

    @staticmethod
    def _system_font_families() -> list:
        """Installed font family names, preferred UI fonts first."""
        preferred = (
            "Microsoft YaHei UI",
            "Microsoft YaHei",
            "Segoe UI",
            "PingFang SC",
            "Hiragino Sans GB",
            "Noto Sans CJK SC",
            "Source Han Sans SC",
            "Arial",
            "Helvetica Neue",
            "Tahoma",
        )
        try:
            # PySide6: static; PySide2: instance method.
            families_fn = getattr(QtGui.QFontDatabase, "families", None)
            if callable(families_fn):
                try:
                    families = list(families_fn())
                except TypeError:
                    families = list(QtGui.QFontDatabase().families())
            else:
                families = list(QtGui.QFontDatabase().families())
        except Exception:
            families = []
        # Case-insensitive de-dupe while preserving first-seen casing.
        by_lower = {}
        for name in families:
            key = str(name).strip()
            if not key:
                continue
            by_lower.setdefault(key.lower(), key)
        ordered = []
        seen = set()
        for name in preferred:
            real = by_lower.get(name.lower())
            if real and real.lower() not in seen:
                ordered.append(real)
                seen.add(real.lower())
        for name in sorted(by_lower.values(), key=lambda s: s.lower()):
            if name.lower() not in seen:
                ordered.append(name)
                seen.add(name.lower())
        return ordered

    def _populate_font_families(self) -> None:
        combo = self.font_family
        current = combo.currentText().strip() if combo.count() else ""
        families = self._system_font_families()
        combo.blockSignals(True)
        try:
            combo.clear()
            for family in families:
                combo.addItem(family)
            # Typing filters the long system-font list.
            completer = QtWidgets.QCompleter(families, combo)
            completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
            completer.setFilterMode(QtCore.Qt.MatchContains)
            combo.setCompleter(completer)
            if current:
                self._set_font_family(current)
        finally:
            combo.blockSignals(False)

    def _font_family_value(self) -> str:
        return self.font_family.currentText().strip()

    def _set_font_family(self, family: str) -> None:
        name = (family or "").strip() or "Microsoft YaHei UI"
        idx = self.font_family.findText(name, QtCore.Qt.MatchFixedString)
        if idx < 0:
            # Keep a custom / missing family selectable without polluting the list.
            self.font_family.insertItem(0, name)
            idx = 0
        self.font_family.setCurrentIndex(idx)
        if self.font_family.isEditable() and self.font_family.lineEdit() is not None:
            self.font_family.setEditText(name)

    def _snapshot(self) -> tuple:
        return (
            self.language_combo.currentData(),
            self._font_family_value(),
            int(self.ui_scale.value()),
            self.temp_dir_edit.text().strip(),
            self.adv_path_edit.text().strip(),
            bool(self.bridge_enabled.isChecked()),
            bool(self.bridge_auto_start.isChecked()),
            int(self.bridge_port.value()),
            bool(self.bridge_port_auto.isChecked()),
            str(self.bridge_confirm.currentData() or "maya_dialog"),
            bool(self.bridge_share.isChecked()),
            bool(self.user_rules_enabled.isChecked()),
        )

    def _set_bridge_status(self, text: str, kind: str = "") -> None:
        """Inline bridge status. kind: ok | fail | info | ''."""
        label = getattr(self, "bridge_status", None)
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

    def _refresh_bridge_status(self) -> None:
        try:
            from maya_agent.bridge import status as bridge_status

            st = bridge_status()
            if st.get("running"):
                self._set_bridge_status(
                    t("settings.bridge_status_on", url=st.get("base_url") or ""),
                    "ok",
                )
            else:
                self._set_bridge_status(t("settings.bridge_status_off"), "fail")
        except Exception:
            self._set_bridge_status("", "")

    def _bridge_start(self) -> None:
        self._save()
        try:
            from maya_agent.bridge import start

            result = start()
            if result.get("ok"):
                self._set_bridge_status(
                    t(
                        "settings.bridge_status_on",
                        url=result.get("base_url") or "",
                    ),
                    "ok",
                )
            else:
                self._set_bridge_status(
                    t(
                        "bridge.start_failed",
                        error=result.get("error") or "unknown",
                    ),
                    "fail",
                )
        except Exception as e:
            self._set_bridge_status(str(e), "fail")

    def _bridge_stop(self) -> None:
        try:
            from maya_agent.bridge import stop

            stop()
            self._set_bridge_status(t("settings.bridge_status_off"), "fail")
        except Exception as e:
            self._set_bridge_status(str(e), "fail")

    def _bridge_copy_mcp(self) -> None:
        try:
            from maya_agent.bridge import copy_mcp_config

            result = copy_mcp_config()
            text = result.get("text") or ""
            clip = QtWidgets.QApplication.clipboard()
            if clip is not None and text:
                clip.setText(text)
                self._set_bridge_status(t("settings.bridge_mcp_copied"), "info")
            else:
                self._set_bridge_status(t("bridge.mcp_copy_failed"), "fail")
        except Exception as e:
            self._set_bridge_status(str(e), "fail")

    def _browse_temp_dir(self) -> None:
        start = self.temp_dir_edit.text().strip() or str(default_agent_temp_root())
        chosen = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            t("settings.temp_dir_pick"),
            start,
        )
        if chosen:
            self.temp_dir_edit.setText(chosen.replace("\\", "/"))

    def _set_adv_status(self, text: str, kind: str = "") -> None:
        label = getattr(self, "adv_status", None)
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

    def _clear_adv_status(self, *_args) -> None:
        self._set_adv_status("", "")

    def _browse_adv_path(self) -> None:
        start = self.adv_path_edit.text().strip() or ""
        chosen = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            t("settings.adv_path_pick"),
            start,
        )
        if chosen:
            self.adv_path_edit.setText(chosen.replace("\\", "/"))

    def _detect_adv(self) -> None:
        path = self.adv_path_edit.text().strip().replace("\\", "/")
        self.cfg.set("maya.advanced_skeleton_path", path)
        self._set_adv_status(t("settings.adv_detect_running"), "info")
        btn = getattr(self, "adv_detect_btn", None)
        if btn is not None:
            btn.setEnabled(False)
        try:
            QtWidgets.QApplication.processEvents()
            from maya_agent.tools.adv_rig import _find_adv_root, adv_tools_available

            root = _find_adv_root()
            if adv_tools_available() and root:
                self._set_adv_status(
                    t("settings.adv_detect_ok").format(path=root), "ok"
                )
                if not path:
                    self.adv_path_edit.setText(root.replace("\\", "/"))
            else:
                self._set_adv_status(t("settings.adv_detect_fail"), "fail")
        except Exception as e:
            err = " ".join(str(e).split())
            if len(err) > 72:
                err = err[:72] + "…"
            self._set_adv_status(
                f"{t('settings.adv_detect_fail')} · {err}", "fail"
            )
        finally:
            if btn is not None:
                btn.setEnabled(True)

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
        self._save()

    def _wire_dirty_tracking(self) -> None:
        self.language_combo.currentIndexChanged.connect(self._schedule_autosave)
        self.font_family.currentIndexChanged.connect(self._schedule_autosave)
        self.font_family.editTextChanged.connect(self._schedule_autosave)
        self.ui_scale.valueChanged.connect(self._schedule_autosave)
        self.temp_dir_edit.textChanged.connect(self._schedule_autosave)
        self.adv_path_edit.textChanged.connect(self._schedule_autosave)
        self.adv_path_edit.textChanged.connect(self._clear_adv_status)
        self.bridge_enabled.toggled.connect(self._schedule_autosave)
        self.bridge_auto_start.toggled.connect(self._schedule_autosave)
        self.bridge_port.valueChanged.connect(self._schedule_autosave)
        self.bridge_port_auto.toggled.connect(self._schedule_autosave)
        self.bridge_confirm.currentIndexChanged.connect(self._schedule_autosave)
        self.bridge_share.toggled.connect(self._schedule_autosave)
        self.user_rules_enabled.toggled.connect(self._schedule_autosave)

    def _load(self) -> None:
        self._suppress_dirty = True
        try:
            if self._autosave_timer.isActive():
                self._autosave_timer.stop()
            lang = str(self.cfg.get("app.language", "zh-CN") or "zh-CN")
            lidx = self.language_combo.findData(lang)
            self.language_combo.setCurrentIndex(lidx if lidx >= 0 else 0)
            self._set_font_family(
                str(self.cfg.get("ui.font_family", "Microsoft YaHei UI") or "")
            )
            self.ui_scale.setValue(_resolve_ui_scale_pct(self.cfg))
            self.temp_dir_edit.setText(
                str(self.cfg.get("ui.temp_dir") or "").strip()
            )
            self.temp_dir_edit.setPlaceholderText(
                str(default_agent_temp_root()).replace("\\", "/")
            )
            self.adv_path_edit.setText(
                str(self.cfg.get("maya.advanced_skeleton_path") or "").strip()
            )
            self.bridge_enabled.setChecked(
                bool(self.cfg.get("bridge.enabled", True))
            )
            self.bridge_auto_start.setChecked(
                bool(self.cfg.get("bridge.auto_start", False))
            )
            try:
                self.bridge_port.setValue(int(self.cfg.get("bridge.port", 8765) or 8765))
            except (TypeError, ValueError):
                self.bridge_port.setValue(8765)
            self.bridge_port_auto.setChecked(
                bool(self.cfg.get("bridge.port_auto", True))
            )
            mode = str(self.cfg.get("bridge.confirm_mode", "maya_dialog") or "maya_dialog")
            cidx = self.bridge_confirm.findData(mode)
            self.bridge_confirm.setCurrentIndex(cidx if cidx >= 0 else 0)
            self.bridge_share.setChecked(
                bool(self.cfg.get("bridge.share_panel_agent", True))
            )
            self.user_rules_enabled.setChecked(
                bool(self.cfg.get("agent.user_rules_enabled", True))
            )
            self._refresh_bridge_status()
            self._rules_reload(select_id=self._current_rule_id)
        finally:
            self._suppress_dirty = False
        self._mark_clean()

    def reload_from_config(self) -> None:
        self.cfg.reload()
        self._load()

    def _save(self) -> None:
        old_lang = str(self.cfg.get("app.language", "zh-CN") or "zh-CN")
        new_lang = str(self.language_combo.currentData() or "zh-CN")
        self.cfg.set("app.language", new_lang)
        self.cfg.set("ui.font_family", self._font_family_value())
        self.cfg.set("ui.ui_scale", int(self.ui_scale.value()))
        self.cfg.set(
            "ui.temp_dir",
            self.temp_dir_edit.text().strip().replace("\\", "/"),
        )
        self.cfg.set(
            "maya.advanced_skeleton_path",
            self.adv_path_edit.text().strip().replace("\\", "/"),
        )
        self.cfg.set("bridge.enabled", self.bridge_enabled.isChecked())
        self.cfg.set("bridge.auto_start", self.bridge_auto_start.isChecked())
        self.cfg.set("bridge.port", int(self.bridge_port.value()))
        self.cfg.set("bridge.port_auto", self.bridge_port_auto.isChecked())
        self.cfg.set(
            "bridge.confirm_mode",
            str(self.bridge_confirm.currentData() or "maya_dialog"),
        )
        self.cfg.set("bridge.share_panel_agent", self.bridge_share.isChecked())
        self.cfg.set(
            "agent.user_rules_enabled",
            bool(self.user_rules_enabled.isChecked()),
        )
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
        self.save_hint.setText(t("settings.saved"))

    def _restore_defaults(self) -> None:
        reply = QtWidgets.QMessageBox.question(
            self,
            t("settings.reset_title"),
            t("settings.reset_ui_body"),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        if self._autosave_timer.isActive():
            self._autosave_timer.stop()
        old_lang = str(self.cfg.get("app.language", "zh-CN") or "zh-CN")
        defaults = ConfigDefaults.load()
        self.cfg.set("app.language", defaults["language"])
        self.cfg.set("ui.font_family", defaults["font_family"])
        self.cfg.set("ui.ui_scale", defaults["ui_scale"])
        self.cfg.set("ui.temp_dir", defaults["temp_dir"])
        self.cfg.set(
            "maya.advanced_skeleton_path",
            defaults.get("advanced_skeleton_path", ""),
        )
        self.cfg.set("bridge.enabled", defaults.get("bridge_enabled", True))
        self.cfg.set("bridge.auto_start", defaults.get("bridge_auto_start", False))
        self.cfg.set("bridge.port", defaults.get("bridge_port", 8765))
        self.cfg.set("bridge.port_auto", defaults.get("bridge_port_auto", True))
        self.cfg.set(
            "bridge.confirm_mode",
            defaults.get("bridge_confirm_mode", "maya_dialog"),
        )
        self.cfg.set(
            "bridge.share_panel_agent",
            defaults.get("bridge_share_agent", True),
        )
        ui_data = self.cfg._data.get("ui")
        if isinstance(ui_data, dict):
            ui_data.pop("font_size", None)
        self.cfg.save_user()
        init_from_config()
        self._load()
        new_lang = str(self.cfg.get("app.language", "zh-CN") or "zh-CN")
        if self._on_saved:
            self._on_saved(language_changed=(old_lang != new_lang))
        self.save_hint.setText(t("settings.reset_done"))

    def _set_rules_status(self, text: str) -> None:
        label = getattr(self, "_rules_status", None)
        if label is not None:
            label.setText(text or "")

    def _make_rule_row_widget(
        self,
        rid: str,
        label: str,
        *,
        enabled: bool,
        can_edit: bool,
        unsaved: bool = False,
    ):
        """List row: enable + title + status badges + delete (UI rules only).

        Parent to the list immediately — an unparented QWidget flashes as a
        tiny Maya native window before setItemWidget reparents it.
        """
        row = QtWidgets.QWidget(self.rules_list)
        row.setObjectName("rulesListRow")
        row.setProperty("rule_id", rid)
        lay = QtWidgets.QHBoxLayout(row)
        lay.setContentsMargins(8, 0, 6, 0)
        lay.setSpacing(6)
        enable_cb = QtWidgets.QCheckBox(row)
        enable_cb.setObjectName("rulesRowEnableCb")
        enable_cb.setToolTip(t("rules.item_enabled"))
        enable_cb.setChecked(bool(enabled))
        enable_cb.setEnabled(can_edit)
        enable_cb.setCursor(
            QtCore.Qt.PointingHandCursor if can_edit else QtCore.Qt.ArrowCursor
        )
        if can_edit:
            enable_cb.toggled.connect(
                lambda checked, rule_id=rid: self._on_rule_enabled_toggled(
                    rule_id, checked
                )
            )
        lay.addWidget(enable_cb, 0, QtCore.Qt.AlignVCenter)
        title_lab = QtWidgets.QLabel(label, row)
        title_lab.setObjectName("rulesListTitle")
        title_lab.setWordWrap(False)
        title_lab.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred
        )
        lay.addWidget(title_lab, 1, QtCore.Qt.AlignVCenter)

        inactive_badge = QtWidgets.QLabel(t("rules.badge_inactive"), row)
        inactive_badge.setObjectName("rulesBadgeInactive")
        inactive_badge.setAlignment(QtCore.Qt.AlignCenter)
        inactive_badge.setVisible(not bool(enabled))
        lay.addWidget(inactive_badge, 0, QtCore.Qt.AlignVCenter)

        unsaved_badge = QtWidgets.QLabel(t("rules.badge_unsaved"), row)
        unsaved_badge.setObjectName("rulesBadgeUnsaved")
        unsaved_badge.setAlignment(QtCore.Qt.AlignCenter)
        unsaved_badge.setVisible(bool(unsaved) and can_edit)
        lay.addWidget(unsaved_badge, 0, QtCore.Qt.AlignVCenter)

        del_btn = QtWidgets.QPushButton("\u00d7", row)
        del_btn.setObjectName("rulesRowDeleteBtn")
        # Hit area larger than glyph so the × is not clipped at 16px.
        del_btn.setFixedSize(22, 22)
        del_btn.setCursor(QtCore.Qt.PointingHandCursor)
        del_btn.setToolTip(t("rules.delete"))
        del_btn.setFlat(True)
        del_btn.setAutoDefault(False)
        del_btn.setDefault(False)
        del_btn.setFocusPolicy(QtCore.Qt.NoFocus)
        del_btn.setVisible(can_edit)
        del_btn.setEnabled(can_edit)
        if can_edit:
            del_btn.clicked.connect(
                lambda _checked=False, rule_id=rid: self._rules_delete(rule_id)
            )
        lay.addWidget(del_btn, 0, QtCore.Qt.AlignVCenter)
        return row

    def _find_rule_row(self, rule_id: str):
        rid = str(rule_id or "")
        if not rid:
            return None
        for i in range(self.rules_list.count()):
            item = self.rules_list.item(i)
            if item is None:
                continue
            if str(item.data(QtCore.Qt.UserRole) or "") == rid:
                return self.rules_list.itemWidget(item)
        return None

    def _is_rule_unsaved(self, rule_id: str) -> bool:
        rid = str(rule_id or "")
        if not rid or rid != self._current_rule_id or self._loading_rule:
            return False
        rule = self._rules_by_id.get(rid) or {}
        if str(rule.get("source") or "ui") == "file":
            return False
        saved_title = str(rule.get("title") or "").strip()
        saved_content = str(rule.get("content") or "")
        cur_title = self.rules_title_edit.text().strip()
        cur_content = self.rules_content_edit.toPlainText()
        return cur_title != saved_title or cur_content != saved_content

    def _refresh_rule_badges(self, rule_id: str = "") -> None:
        rid = str(rule_id or self._current_rule_id or "")
        row = self._find_rule_row(rid)
        if row is None:
            return
        rule = self._rules_by_id.get(rid) or {}
        enabled = bool(rule.get("enabled", True))
        can_edit = str(rule.get("source") or "ui") != "file"
        inactive = row.findChild(QtWidgets.QLabel, "rulesBadgeInactive")
        unsaved = row.findChild(QtWidgets.QLabel, "rulesBadgeUnsaved")
        if inactive is not None:
            inactive.setVisible(not enabled)
        if unsaved is not None:
            unsaved.setVisible(can_edit and self._is_rule_unsaved(rid))

    def _on_rule_editor_changed(self, *_args) -> None:
        if self._loading_rule or not self._current_rule_id:
            return
        self._refresh_rule_badges(self._current_rule_id)

    def _rules_reload(self, *_args, select_id=None) -> None:
        from maya_agent.core.rules_manager import get_all_rules, reload_rules

        reload_rules()
        rules = get_all_rules(force_reload=True)
        self._rules_by_id = {str(r.get("id")): r for r in rules}
        keep = select_id if select_id else self._current_rule_id
        self.rules_list.blockSignals(True)
        self.rules_list.clear()
        select_row = -1
        for i, rule in enumerate(rules):
            rid = str(rule.get("id") or "")
            title = str(rule.get("title") or t("rules.untitled")).strip() or t(
                "rules.untitled"
            )
            source = str(rule.get("source") or "ui")
            tag = t("rules.source_file") if source == "file" else t("rules.source_ui")
            enabled = bool(rule.get("enabled", True))
            can_edit = source != "file"
            label = f"{title}  [{tag}]"
            item = QtWidgets.QListWidgetItem()
            item.setData(QtCore.Qt.UserRole, rid)
            item.setSizeHint(QtCore.QSize(0, 32))
            self.rules_list.addItem(item)
            row = self._make_rule_row_widget(
                rid,
                label,
                enabled=enabled,
                can_edit=can_edit,
                unsaved=False,
            )
            self.rules_list.setItemWidget(item, row)
            if keep and rid == keep:
                select_row = i
        self.rules_list.blockSignals(False)
        if select_row < 0 and self.rules_list.count() > 0:
            select_row = 0
        if select_row >= 0:
            self.rules_list.setCurrentRow(select_row)
        else:
            self._current_rule_id = None
            self._clear_rule_editor()
        if not rules:
            self._set_rules_status(t("rules.empty_hint"))
        else:
            self._set_rules_status("")

    def _clear_rule_editor(self) -> None:
        self._loading_rule = True
        try:
            self.rules_title_edit.clear()
            self.rules_content_edit.clear()
            self.rules_title_edit.setEnabled(False)
            self.rules_content_edit.setEnabled(False)
            self.rules_save_btn.setEnabled(False)
            self.rules_file_hint.hide()
        finally:
            self._loading_rule = False

    def _on_rule_selected(self, current, _previous=None) -> None:
        prev_id = self._current_rule_id
        if current is None:
            self._current_rule_id = None
            self._clear_rule_editor()
            if prev_id:
                self._refresh_rule_badges(prev_id)
            return
        rid = str(current.data(QtCore.Qt.UserRole) or "")
        rule = self._rules_by_id.get(rid) or {}
        self._current_rule_id = rid
        is_file = str(rule.get("source") or "ui") == "file"
        self._loading_rule = True
        try:
            self.rules_title_edit.setText(str(rule.get("title") or ""))
            self.rules_content_edit.setPlainText(str(rule.get("content") or ""))
            self.rules_title_edit.setEnabled(not is_file)
            self.rules_content_edit.setEnabled(not is_file)
            self.rules_save_btn.setEnabled(not is_file)
            self.rules_file_hint.setVisible(is_file)
        finally:
            self._loading_rule = False
        # Switching discards unsaved edits; clear previous badge first.
        if prev_id and prev_id != rid:
            self._refresh_rule_badges(prev_id)
        self._refresh_rule_badges(rid)

    def _on_rule_enabled_toggled(self, rule_id: str, checked: bool) -> None:
        rid = str(rule_id or "")
        if not rid:
            return
        rule = self._rules_by_id.get(rid) or {}
        if str(rule.get("source") or "ui") == "file":
            return
        from maya_agent.core.rules_manager import update_rule

        update_rule(rid, enabled=bool(checked))
        # Keep local cache in sync without rebuilding the row (avoids checkbox flicker).
        if rid in self._rules_by_id:
            self._rules_by_id[rid]["enabled"] = bool(checked)
        self._refresh_rule_badges(rid)
        self._notify_rules_changed()

    def _rules_new(self) -> None:
        from maya_agent.core.rules_manager import add_rule

        rule = add_rule(title=t("rules.new_title"), content="")
        self._rules_reload(select_id=str(rule.get("id")))
        self._notify_rules_changed()
        self._set_rules_status(t("rules.created"))

    def _rules_delete(self, rule_id: str = "") -> None:
        rid = str(rule_id or self._current_rule_id or "")
        if not rid:
            return
        rule = self._rules_by_id.get(rid) or {}
        if str(rule.get("source") or "ui") == "file":
            self._set_rules_status(t("rules.file_readonly"))
            return
        reply = QtWidgets.QMessageBox.question(
            self,
            t("rules.delete_title"),
            t("rules.delete_confirm", title=str(rule.get("title") or "")),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        from maya_agent.core.rules_manager import delete_rule

        delete_rule(rid)
        if self._current_rule_id == rid:
            self._current_rule_id = None
        self._rules_reload()
        self._notify_rules_changed()
        self._set_rules_status(t("rules.deleted"))

    def _rules_save_current(self) -> None:
        rid = self._current_rule_id
        if not rid:
            return
        rule = self._rules_by_id.get(rid) or {}
        if str(rule.get("source") or "ui") == "file":
            self._set_rules_status(t("rules.file_readonly"))
            return
        from maya_agent.core.rules_manager import update_rule

        update_rule(
            rid,
            title=self.rules_title_edit.text().strip(),
            content=self.rules_content_edit.toPlainText(),
        )
        self._rules_reload(select_id=rid)
        self._notify_rules_changed()
        self._set_rules_status(t("rules.saved"))

    def _rules_open_dir(self) -> None:
        from maya_agent.core.rules_manager import ensure_rules_dir

        path = ensure_rules_dir()
        try:
            QtGui.QDesktopServices.openUrl(
                QtCore.QUrl.fromLocalFile(str(path.resolve()))
            )
            self._set_rules_status(t("rules.opened_dir", path=str(path)))
        except Exception as e:
            self._set_rules_status(str(e))

    def _notify_rules_changed(self) -> None:
        # Rule CRUD already wrote user_rules.json. Only refresh the agent
        # system prompt — avoid full settings-saved (stylesheet + panel
        # reload), which flashes a Maya native window chrome.
        if self._on_saved:
            try:
                self._on_saved(language_changed=False, rules_only=True)
            except TypeError:
                try:
                    self._on_saved(language_changed=False)
                except Exception:
                    pass
            except Exception:
                pass


def create_ui_panel(parent=None, *, on_saved=None):
    init_from_config()
    return UiPanel(parent, on_saved=on_saved)
