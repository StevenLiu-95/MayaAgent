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
        self.skills_enabled.toggled.connect(self._schedule_autosave)
        self.skills_dir_edit.textChanged.connect(self._schedule_autosave)

    def _load(self) -> None:
        self._suppress_dirty = True
        try:
            if self._autosave_timer.isActive():
                self._autosave_timer.stop()
            self.skills_enabled.setChecked(
                bool(self.cfg.get("agent.skills_enabled", True))
            )
            self.skills_dir_edit.setText(
                str(self.cfg.get("agent.skills_dir") or "").strip()
            )
            self.skills_dir_edit.setPlaceholderText(
                str(default_agent_skills_root()).replace("\\", "/")
            )
            self._refresh_skills_list(notify=False)
        finally:
            self._suppress_dirty = False
        self._mark_clean()

    def reload_from_config(self) -> None:
        self.cfg.reload()
        self._load()

    def _save(self) -> None:
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
            "agent.skills_enabled",
            defaults.get("skills_enabled", True),
        )
        self.cfg.set("agent.skills_dir", defaults.get("skills_dir", ""))
        self.cfg.save_user()
        skills_manager.reload_skills()
        self._load()
        self._notify_skills_changed()

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


def create_extensions_panel(parent=None, *, on_saved=None):
    init_from_config()
    return ExtensionsPanel(parent, on_saved=on_saved)
