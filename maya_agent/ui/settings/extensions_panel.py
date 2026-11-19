"""Extensions tab — Agent Skills configuration (agentskills.io packages)."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from maya_agent.core import skills_manager
from maya_agent.i18n import init_from_config, t
from maya_agent.ui.palette import COLOR_MUTED, COLOR_TEST_FAIL, COLOR_TEST_OK
from maya_agent.ui.qt_bind import QtCore, QtGui, QtWidgets
from maya_agent.ui.settings.config_defaults import ConfigDefaults
from maya_agent.ui.settings.form_helpers import SettingsFormMixin
from maya_agent.utils.config import get_config
from maya_agent.utils.paths import default_agent_skills_root


class _ElidedLabel(QtWidgets.QLabel):
    """Single-line label that elides overflowing text (middle by default)."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full = text or ""
        self._elide = QtCore.Qt.ElideMiddle
        self.setWordWrap(False)
        self.setText(self._full)

    def set_full_text(self, text: str) -> None:
        self._full = text or ""
        self._update_elide()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_elide()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._update_elide()

    def _update_elide(self) -> None:
        width = max(0, self.width())
        if width <= 0:
            return
        elided = self.fontMetrics().elidedText(self._full, self._elide, width)
        if elided != self.text():
            self.setText(elided)


class ExtensionsPanel(SettingsFormMixin, QtWidgets.QWidget):
    def __init__(self, parent=None, *, on_saved: Optional[Callable[..., None]] = None):
        super().__init__(parent)
        self.setObjectName("settingsPanel")
        self.cfg = get_config()
        self._on_saved = on_saved
        self._suppress_dirty = False
        self._baseline = None
        self._build()
        self._load()

    def _build(self) -> None:
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 6, 0, 0)
        outer.setSpacing(10)

        scroll, root = self._scroll_page()

        rules, rules_lay = self._section(
            t("rules.section"),
            t("rules.section_hint"),
        )
        self.user_rules_enabled = QtWidgets.QCheckBox(t("rules.enabled"))
        self.user_rules_enabled.setToolTip(t("rules.enabled_tip"))
        rules_lay.addWidget(self.user_rules_enabled)

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

        skills, skills_lay = self._section(
            t("extensions.skills.section"),
            t("extensions.skills.section_hint"),
        )
        self.skills_enabled = QtWidgets.QCheckBox(t("extensions.skills.enabled"))
        self.skills_enabled.setToolTip(t("extensions.skills.enabled_tip"))
        skills_lay.addWidget(self.skills_enabled)

        sform = self._form(skills_lay)
        path_row = QtWidgets.QWidget()
        path_lay = QtWidgets.QHBoxLayout(path_row)
        path_lay.setContentsMargins(0, 0, 0, 0)
        path_lay.setSpacing(8)
        self.skills_dir_edit = QtWidgets.QLineEdit()
        self.skills_dir_edit.setMinimumHeight(30)
        self.skills_dir_edit.setPlaceholderText(
            str(default_agent_skills_root()).replace("\\", "/")
        )
        self.skills_dir_edit.setToolTip(t("extensions.skills.dir_tip"))
        self.skills_dir_browse = QtWidgets.QPushButton(t("extensions.skills.browse"))
        self.skills_dir_browse.setObjectName("secondaryBtn")
        self.skills_dir_browse.setCursor(QtCore.Qt.PointingHandCursor)
        self.skills_dir_browse.setMinimumHeight(30)
        self.skills_dir_browse.setMinimumWidth(72)
        self.skills_dir_browse.clicked.connect(self._browse_skills_dir)
        self.skills_dir_open = QtWidgets.QPushButton(t("extensions.skills.open_dir"))
        self.skills_dir_open.setObjectName("secondaryBtn")
        self.skills_dir_open.setCursor(QtCore.Qt.PointingHandCursor)
        self.skills_dir_open.setMinimumHeight(30)
        self.skills_dir_open.clicked.connect(self._open_skills_dir)
        path_lay.addWidget(self.skills_dir_edit, 1)
        path_lay.addWidget(self.skills_dir_browse, 0)
        path_lay.addWidget(self.skills_dir_open, 0)
        sform.addRow(self._field_label(t("extensions.skills.dir")), path_row)

        list_head = QtWidgets.QHBoxLayout()
        list_head.setContentsMargins(0, 4, 0, 0)
        list_head.setSpacing(8)
        list_label = QtWidgets.QLabel(t("extensions.skills.list"))
        list_label.setObjectName("settingsFieldLabel")
        list_head.addWidget(list_label, 1)
        self.skills_refresh_btn = QtWidgets.QPushButton(t("extensions.skills.refresh"))
        self.skills_refresh_btn.setObjectName("secondaryBtn")
        self.skills_refresh_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.skills_refresh_btn.setMinimumHeight(30)
        self.skills_refresh_btn.clicked.connect(self._refresh_skills_list)
        list_head.addWidget(self.skills_refresh_btn, 0)
        skills_lay.addLayout(list_head)

        self.skills_list = QtWidgets.QListWidget()
        self.skills_list.setObjectName("skillsList")
        self.skills_list.setMinimumHeight(140)
        self.skills_list.setMaximumHeight(240)
        self.skills_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.skills_list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.skills_list.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.skills_list.setSpacing(2)
        self.skills_list.setToolTip(t("extensions.skills.list_tip"))
        self.skills_list.itemDoubleClicked.connect(self._on_skill_double_clicked)
        self.skills_list.installEventFilter(self)
        skills_lay.addWidget(self.skills_list)

        self.skills_status = QtWidgets.QLabel("")
        self.skills_status.setObjectName("testConnStatus")
        self.skills_status.setWordWrap(True)
        skills_lay.addWidget(self.skills_status)

        root.addWidget(skills)
        self._stretch_end(root)
        outer.addWidget(scroll, 1)

        foot = QtWidgets.QHBoxLayout()
        foot.setContentsMargins(14, 0, 14, 10)
        foot.setSpacing(10)
        self.save_hint = QtWidgets.QLabel(t("settings.autosave_hint"))
        self.save_hint.setObjectName("settingsAutosaveHint")
        self.save_hint.setWordWrap(True)
        foot.addWidget(self.save_hint, 1)
        self.reset_btn = QtWidgets.QPushButton(t("extensions.reset"))
        self.reset_btn.setObjectName("secondaryBtn")
        self.reset_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.reset_btn.setMinimumHeight(30)
        self.reset_btn.clicked.connect(self._restore_defaults)
        foot.addWidget(self.reset_btn, 0)
        outer.addLayout(foot)

        self._autosave_timer = QtCore.QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(450)
        self._autosave_timer.timeout.connect(self._autosave_now)
        self._wire_dirty_tracking()
        self._apply_no_wheel()

    def _set_status(self, text: str, kind: str = "") -> None:
        self.skills_status.setText(text or "")
        colors = {
            "ok": COLOR_TEST_OK,
            "fail": COLOR_TEST_FAIL,
            "info": COLOR_MUTED,
        }
        color = colors.get(kind, COLOR_MUTED)
        self.skills_status.setStyleSheet(
            f"QLabel#testConnStatus {{ color: {color}; font-size: 12px; "
            f"background: transparent; border: none; padding: 0; }}"
        )

    def _snapshot(self) -> tuple:
        return (
            bool(self.user_rules_enabled.isChecked()),
            bool(self.skills_enabled.isChecked()),
            self.skills_dir_edit.text().strip().replace("\\", "/"),
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
        self._save()

    def _wire_dirty_tracking(self) -> None:
        self.user_rules_enabled.toggled.connect(self._schedule_autosave)
        self.skills_enabled.toggled.connect(self._schedule_autosave)
        self.skills_dir_edit.textChanged.connect(self._schedule_autosave)

    def _load(self) -> None:
        self._suppress_dirty = True
        try:
            if self._autosave_timer.isActive():
                self._autosave_timer.stop()
            self.user_rules_enabled.setChecked(
                bool(self.cfg.get("agent.user_rules_enabled", True))
            )
            self.skills_enabled.setChecked(
                bool(self.cfg.get("agent.skills_enabled", True))
            )
            self.skills_dir_edit.setText(
                str(self.cfg.get("agent.skills_dir") or "").strip()
            )
            self.skills_dir_edit.setPlaceholderText(
                str(default_agent_skills_root()).replace("\\", "/")
            )
            self._rules_reload(select_id=self._current_rule_id)
            self._refresh_skills_list(notify=False)
        finally:
            self._suppress_dirty = False
        self._mark_clean()

    def reload_from_config(self) -> None:
        self.cfg.reload()
        self._load()

    def _save(self) -> None:
        self.cfg.set(
            "agent.user_rules_enabled",
            bool(self.user_rules_enabled.isChecked()),
        )
        self.cfg.set("agent.skills_enabled", bool(self.skills_enabled.isChecked()))
        self.cfg.set(
            "agent.skills_dir",
            self.skills_dir_edit.text().strip().replace("\\", "/"),
        )
        self.cfg.save_user()
        self._mark_clean()
        skills_manager.reload_skills()
        self._refresh_skills_list(notify=False)
        self._notify_skills_changed()
        self._notify_rules_changed()
        self.save_hint.setText(t("settings.saved"))

    def _restore_defaults(self) -> None:
        reply = QtWidgets.QMessageBox.question(
            self,
            t("extensions.reset_title"),
            t("extensions.reset_body"),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        if self._autosave_timer.isActive():
            self._autosave_timer.stop()
        defaults = ConfigDefaults.load()
        self.cfg.set(
            "agent.user_rules_enabled",
            defaults.get("user_rules_enabled", True),
        )
        self.cfg.set(
            "agent.skills_enabled",
            defaults.get("skills_enabled", True),
        )
        self.cfg.set("agent.skills_dir", defaults.get("skills_dir", ""))
        self.cfg.save_user()
        skills_manager.reload_skills()
        self._load()
        self._notify_skills_changed()
        self._notify_rules_changed()

    def _browse_skills_dir(self) -> None:
        start = self.skills_dir_edit.text().strip() or str(default_agent_skills_root())
        chosen = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            t("extensions.skills.dir_pick"),
            start,
        )
        if chosen:
            self.skills_dir_edit.setText(chosen.replace("\\", "/"))

    def _open_skills_dir(self) -> None:
        # Persist path first so agent_skills_root() sees the current edit.
        if self._snapshot() != self._baseline:
            self._save()
        try:
            path = skills_manager.ensure_skills_dir()
            QtGui.QDesktopServices.openUrl(
                QtCore.QUrl.fromLocalFile(str(path.resolve()))
            )
            self._set_status(
                t("extensions.skills.opened_dir", path=str(path)),
                "info",
            )
        except Exception as e:
            self._set_status(str(e), "fail")

    def _make_skill_row(
        self,
        *,
        name: str,
        path_full: str,
        description: str,
        manual: bool,
    ) -> QtWidgets.QWidget:
        """List row: title left, optional badge, absolute path right (elided)."""
        row = QtWidgets.QWidget(self.skills_list)
        row.setObjectName("skillsListRow")
        row.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
        )
        lay = QtWidgets.QHBoxLayout(row)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(12)

        title = QtWidgets.QLabel(name, row)
        title.setObjectName("skillsListTitle")
        title.setWordWrap(False)
        title.setSizePolicy(
            QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Preferred
        )
        lay.addWidget(title, 0, QtCore.Qt.AlignVCenter)

        if manual:
            badge = QtWidgets.QLabel(t("extensions.skills.manual"), row)
            badge.setObjectName("skillsListBadge")
            badge.setAlignment(QtCore.Qt.AlignCenter)
            lay.addWidget(badge, 0, QtCore.Qt.AlignVCenter)

        # Path fills remaining width; text stays right-aligned and middle-elided.
        path_lab = _ElidedLabel(path_full, row)
        path_lab.setObjectName("skillsListPath")
        path_lab.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        path_lab.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred
        )
        path_lab.setMinimumWidth(120)
        lay.addWidget(path_lab, 1, QtCore.Qt.AlignVCenter)

        tip_parts = []
        if description:
            tip_parts.append(description)
        tip_parts.append(path_full)
        tip_parts.append(t("extensions.skills.dblclick_tip"))
        tip = "\n".join(tip_parts)
        row.setToolTip(tip)
        title.setToolTip(tip)
        path_lab.setToolTip(tip)
        return row

    def _sync_skill_row_widths(self) -> None:
        """Make item widgets span the list viewport so the path stays visible."""
        viewport = self.skills_list.viewport()
        if viewport is None:
            return
        width = max(0, int(viewport.width()) - 4)
        if width <= 0:
            return
        for i in range(self.skills_list.count()):
            item = self.skills_list.item(i)
            if item is None:
                continue
            row = self.skills_list.itemWidget(item)
            height = 34
            if row is not None:
                hint = row.sizeHint()
                if hint.isValid() and hint.height() > 0:
                    height = max(34, int(hint.height()))
                row.setFixedWidth(width)
            item.setSizeHint(QtCore.QSize(width, height))

    def eventFilter(self, obj, event):
        if obj is self.skills_list and event.type() in (
            QtCore.QEvent.Resize,
            QtCore.QEvent.Show,
        ):
            QtCore.QTimer.singleShot(0, self._sync_skill_row_widths)
        return super().eventFilter(obj, event)

    def _refresh_skills_list(self, notify: bool = True) -> None:
        self.skills_list.clear()
        try:
            # Persist dirty path so discovery uses the path shown in the UI.
            if self._baseline is not None and self._snapshot() != self._baseline:
                self.cfg.set(
                    "agent.skills_enabled",
                    bool(self.skills_enabled.isChecked()),
                )
                self.cfg.set(
                    "agent.skills_dir",
                    self.skills_dir_edit.text().strip().replace("\\", "/"),
                )
                self.cfg.save_user()
                self._mark_clean()
            skills_manager.reload_skills()
            skills = skills_manager.discover_skills(force_reload=True)
        except Exception as e:
            self._set_status(str(e), "fail")
            return

        viewport = self.skills_list.viewport()
        row_width = max(200, int(viewport.width()) - 4) if viewport else 200

        for s in skills:
            path_full = str(s.path).replace("\\", "/")
            item = QtWidgets.QListWidgetItem()
            item.setData(QtCore.Qt.UserRole, s.name)
            item.setData(QtCore.Qt.UserRole + 1, path_full)
            row = self._make_skill_row(
                name=s.name,
                path_full=path_full,
                description=s.description or "",
                manual=bool(s.disable_model_invocation),
            )
            item.setSizeHint(QtCore.QSize(row_width, 34))
            self.skills_list.addItem(item)
            self.skills_list.setItemWidget(item, row)
            row.setFixedWidth(row_width)

        QtCore.QTimer.singleShot(0, self._sync_skill_row_widths)

        count = len(skills)
        root_text = skills_manager.skills_root_display()
        self._set_status(
            t("extensions.skills.status", count=count, path=root_text),
            "ok" if count else "info",
        )
        if notify:
            self._notify_skills_changed()

    def _on_skill_double_clicked(self, item) -> None:
        if item is None:
            return
        path_text = item.data(QtCore.Qt.UserRole + 1)
        if not path_text:
            name = item.data(QtCore.Qt.UserRole)
            info = skills_manager.get_skill(str(name or ""))
            path_text = str(info.path) if info else ""
        if not path_text:
            return
        try:
            path = Path(str(path_text))
            if not path.is_dir():
                self._set_status(
                    t("extensions.skills.open_fail", path=path_text),
                    "fail",
                )
                return
            QtGui.QDesktopServices.openUrl(
                QtCore.QUrl.fromLocalFile(str(path.resolve()))
            )
            self._set_status(
                t("extensions.skills.opened_dir", path=str(path)),
                "info",
            )
        except Exception as e:
            self._set_status(str(e), "fail")

    def _notify_skills_changed(self) -> None:
        if self._on_saved:
            try:
                self._on_saved(language_changed=False, skills_only=True)
            except TypeError:
                try:
                    self._on_saved(language_changed=False)
                except Exception:
                    pass
            except Exception:
                pass

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
        """List row: enable + title + status badges + delete (UI rules only)."""
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


def create_extensions_panel(parent=None, *, on_saved=None):
    init_from_config()
    return ExtensionsPanel(parent, on_saved=on_saved)
