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

    def _snapshot(self) -> tuple:
        return (
            self.language_combo.currentData(),
            self.font_family.text().strip(),
            int(self.ui_scale.value()),
            self.temp_dir_edit.text().strip(),
            self.adv_path_edit.text().strip(),
            bool(self.bridge_enabled.isChecked()),
            bool(self.bridge_auto_start.isChecked()),
            int(self.bridge_port.value()),
            bool(self.bridge_port_auto.isChecked()),
            str(self.bridge_confirm.currentData() or "maya_dialog"),
            bool(self.bridge_share.isChecked()),
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
        self.font_family.textChanged.connect(self._schedule_autosave)
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

    def _load(self) -> None:
        self._suppress_dirty = True
        try:
            if self._autosave_timer.isActive():
                self._autosave_timer.stop()
            lang = str(self.cfg.get("app.language", "zh-CN") or "zh-CN")
            lidx = self.language_combo.findData(lang)
            self.language_combo.setCurrentIndex(lidx if lidx >= 0 else 0)
            self.font_family.setText(
                self.cfg.get("ui.font_family", "Microsoft YaHei UI")
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
            self._refresh_bridge_status()
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
        self.cfg.set("ui.font_family", self.font_family.text().strip())
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


def create_ui_panel(parent=None, *, on_saved=None):
    init_from_config()
    return UiPanel(parent, on_saved=on_saved)
