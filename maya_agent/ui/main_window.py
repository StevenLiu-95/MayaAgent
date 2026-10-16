"""Main dockable Maya Agent window."""

from __future__ import annotations

from typing import Optional

from maya_agent import __app_name__, __version__
from maya_agent.core.agent import MayaAgent
from maya_agent.core.session_manager import SessionManager
from maya_agent.i18n import init_from_config, t
from maya_agent.ui.agent_worker import create_agent_worker
from maya_agent.ui.chat import create_chat_panel
from maya_agent.ui.combo_widgets import create_toolbar_combo
from maya_agent.ui.composer import apply_send_stop_style, quick_command_specs
from maya_agent.ui.flow_layout import create_flow_layout
from maya_agent.ui.settings import (
    create_help_panel,
    create_settings_panel,
    create_tools_panel,
    create_ui_panel,
)
from maya_agent.ui.status_anim import create_animated_status
from maya_agent.ui.stylesheets import load_stylesheet
from maya_agent.ui.qt_bind import QtCore, QtGui, QtWidgets
from maya_agent.utils.config import get_config
from maya_agent.utils.maya_compat import (
    get_maya_main_window,
    in_maya,
    maya_version,
    wrap_maya_ptr,
)
from maya_agent.llm.base import stop_notice_for_reason
from maya_agent.llm.vision import model_supports_vision
from maya_agent.tools.fsutil import MAX_CHAT_FILES, stage_chat_files
from maya_agent.ui.image_attach import (
    MAX_IMAGES,
    attachment_from_path,
    attachments_from_clipboard,
    is_image_path,
)

_WINDOW_INSTANCE = None


def get_window_instance():
    """Return open Maya Agent window (floating or docked), if any."""
    global _WINDOW_INSTANCE
    if _WINDOW_INSTANCE is not None:
        try:
            _WINDOW_INSTANCE.isVisible()
            return _WINDOW_INSTANCE
        except Exception:
            _WINDOW_INSTANCE = None

    if not in_maya():
        return None
    try:
        import maya.cmds as cmds
        import maya.OpenMayaUI as omui
        from maya_agent.ui.dock import CONTROL_NAME

        if not cmds.workspaceControl(CONTROL_NAME, exists=True):
            return None
        ctrl_ptr = omui.MQtUtil.findControl(CONTROL_NAME)
        if ctrl_ptr:
            control_widget = wrap_maya_ptr(ctrl_ptr, QtWidgets.QWidget)
            win = getattr(control_widget, "_maya_agent_window", None)
            if win is not None:
                _WINDOW_INSTANCE = win
                return win
    except Exception:
        pass
    return None


def load_stylesheet_safe() -> str:
    try:
        return load_stylesheet()
    except Exception:
        return ""


def show_main_window():
    """Show Agent UI — docked in Maya when possible, otherwise floating."""
    init_from_config()
    if in_maya():
        try:
            from maya_agent.ui.dock import show_dockable

            result = show_dockable()
            return result
        except Exception:
            pass
    return show_floating_window()


def show_floating_window():
    """Show or raise a floating Maya Agent window."""
    global _WINDOW_INSTANCE
    init_from_config()

    if _WINDOW_INSTANCE is not None:
        try:
            _WINDOW_INSTANCE.show()
            _WINDOW_INSTANCE.raise_()
            _WINDOW_INSTANCE.activateWindow()
            return _WINDOW_INSTANCE
        except Exception:
            _WINDOW_INSTANCE = None

    parent = get_maya_main_window()
    win = MayaAgentWindow(parent=parent)
    win.setStyleSheet(load_stylesheet_safe())
    win.show()
    _WINDOW_INSTANCE = win
    return win


def reopen_main_window():
    """Close and recreate the panel (used after language change)."""
    global _WINDOW_INSTANCE
    win = get_window_instance()
    if win is not None:
        try:
            win.persist_sessions()
        except Exception:
            pass

    init_from_config()

    if in_maya():
        try:
            import maya.cmds as cmds
            from maya_agent.ui.dock import CONTROL_NAME

            if cmds.workspaceControl(CONTROL_NAME, exists=True):
                try:
                    cmds.deleteUI(CONTROL_NAME)
                except Exception:
                    try:
                        cmds.workspaceControl(CONTROL_NAME, edit=True, close=True)
                    except Exception:
                        pass
            _WINDOW_INSTANCE = None
            try:
                from maya_agent.plugin import menu as menu_mod

                menu_mod.install_menu()
                menu_mod.install_shelf()
            except Exception:
                pass
            return show_main_window()
        except Exception:
            pass

    if _WINDOW_INSTANCE is not None:
        try:
            _WINDOW_INSTANCE.close()
        except Exception:
            pass
        _WINDOW_INSTANCE = None
    return show_floating_window()


class MayaAgentWindow(QtWidgets.QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MayaAgentWindow")
        self.setWindowTitle(f"{__app_name__} v{__version__}")
        cfg = get_config()
        self.resize(
            int(cfg.get("ui.window_width", 420)),
            int(cfg.get("ui.window_height", 720)),
        )
        self.setMinimumWidth(380)
        self.setMinimumHeight(520)

        self.agent = MayaAgent(confirm_callback=self._confirm_destructive)
        try:
            from maya_agent.bridge import register_panel_agent

            register_panel_agent(self.agent)
        except Exception:
            pass
        self.sessions = SessionManager()
        self._session_switching = False
        self._worker = None
        self._skip_confirm_this_turn = False
        self._stopped_by_user = False
        self._stream_buf = ""
        self._thinking_buf = ""
        self._pending_images = []
        self._pending_files = []  # [{path, name, size_bytes}, ...]
        self._vision_enabled = False
        self._stream_timer = QtCore.QTimer(self)
        self._stream_timer.setSingleShot(True)
        # Slightly longer coalesce cuts layout churn during fast streams.
        self._stream_timer.setInterval(100)
        self._stream_timer.timeout.connect(self._flush_stream)
        self._save_timer = QtCore.QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(800)
        self._save_timer.timeout.connect(self.persist_sessions)

        self._build_ui()
        self._apply_provider_from_config()
        self._load_active_session()

    def _build_ui(self):
        central = QtWidgets.QWidget()
        central.setObjectName("centralRoot")
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(10, 8, 10, 10)
        root.setSpacing(8)

        header = QtWidgets.QHBoxLayout()
        header.setSpacing(8)
        title = QtWidgets.QLabel(__app_name__)
        title.setObjectName("titleLabel")
        self.scene_hint = QtWidgets.QLabel("")
        self.scene_hint.setObjectName("sceneHintLabel")
        self.scene_hint.setAlignment(
            QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft
        )
        self.scene_hint.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred
        )
        self.scene_hint.setWordWrap(False)
        ver = maya_version() if in_maya() else "standalone"
        hint = QtWidgets.QLabel(f"v{__version__}  ·  Maya {ver}")
        hint.setObjectName("hintLabel")
        header.addWidget(title, 0)
        header.addWidget(self.scene_hint, 1)
        header.addWidget(hint, 0)
        root.addLayout(header)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setObjectName("mainTabs")
        root.addWidget(self.tabs, 1)

        self._build_chat_tab()
        self._build_settings_tab()
        self._build_ui_tab()
        self._build_tools_tab()
        self._build_help_tab()

    def _build_session_bar(self):
        session_wrap = QtWidgets.QFrame()
        session_wrap.setObjectName("sessionFrame")
        session_row = QtWidgets.QHBoxLayout(session_wrap)
        session_row.setContentsMargins(0, 0, 0, 0)
        session_row.setSpacing(6)

        session_lab = QtWidgets.QLabel(t("session.label"))
        session_lab.setObjectName("toolbarLabel")
        session_lab.setFixedHeight(28)

        self.session_combo = create_toolbar_combo()
        self.session_combo.setEditable(False)
        self.session_combo.setFixedHeight(28)
        self.session_combo.setMinimumWidth(120)
        self.session_combo.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
        )
        self.session_combo.activated.connect(self._on_session_activated)

        new_sess_btn = QtWidgets.QPushButton(t("session.new"))
        new_sess_btn.setObjectName("toolbarBtn")
        new_sess_btn.setFixedSize(52, 28)
        new_sess_btn.setCursor(QtCore.Qt.PointingHandCursor)
        new_sess_btn.clicked.connect(self._on_new_session)

        rename_sess_btn = QtWidgets.QPushButton(t("session.rename"))
        rename_sess_btn.setObjectName("toolbarBtn")
        rename_sess_btn.setFixedSize(64, 28)
        rename_sess_btn.setCursor(QtCore.Qt.PointingHandCursor)
        rename_sess_btn.clicked.connect(self._on_rename_session)

        del_sess_btn = QtWidgets.QPushButton(t("session.delete"))
        del_sess_btn.setObjectName("toolbarBtn")
        del_sess_btn.setFixedSize(52, 28)
        del_sess_btn.setCursor(QtCore.Qt.PointingHandCursor)
        del_sess_btn.clicked.connect(self._on_delete_session)

        session_row.addWidget(session_lab, 0)
        session_row.addWidget(self.session_combo, 1)
        session_row.addWidget(new_sess_btn, 0)
        session_row.addWidget(rename_sess_btn, 0)
        session_row.addWidget(del_sess_btn, 0)
        return session_wrap

    def _build_chat_tab(self):
        chat_page = QtWidgets.QWidget()
        chat_layout = QtWidgets.QVBoxLayout(chat_page)
        chat_layout.setContentsMargins(0, 8, 0, 0)
        chat_layout.setSpacing(6)

        chat_layout.addWidget(self._build_session_bar())

        splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        splitter.setObjectName("chatSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(3)
        try:
            splitter.setOpaqueResize(True)
        except Exception:
            pass

        self.chat = create_chat_panel(chat_page)
        self.chat.set_choice_handler(self._on_choice_reply)
        splitter.addWidget(self.chat)

        composer = self._build_composer()
        splitter.addWidget(composer)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.splitterMoved.connect(self._on_composer_splitter_moved)

        self._chat_splitter = splitter
        self._composer_save_timer = QtCore.QTimer(self)
        self._composer_save_timer.setSingleShot(True)
        self._composer_save_timer.setInterval(400)
        self._composer_save_timer.timeout.connect(self._persist_composer_height)

        chat_layout.addWidget(splitter, 1)
        self.tabs.addTab(chat_page, t("tab.chat"))
        self._chat_tab_index = self.tabs.count() - 1
        QtCore.QTimer.singleShot(0, self._apply_composer_splitter_sizes)

    def _build_composer(self):
        composer = QtWidgets.QFrame()
        composer.setObjectName("composerFrame")
        composer.setMinimumHeight(96)
        composer.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred
        )
        composer_layout = QtWidgets.QVBoxLayout(composer)
        composer_layout.setContentsMargins(8, 6, 8, 6)
        composer_layout.setSpacing(4)

        # 展开后的快捷芯片（默认收起，超出宽度自动换行）
        self._quick_body = QtWidgets.QWidget()
        self._quick_body.setObjectName("quickHost")
        self._quick_body.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred
        )
        quick = create_flow_layout(hspacing=6, vspacing=6)
        self._quick_body.setLayout(quick)
        self._quick_scroll = None
        for label, prompt in quick_command_specs():
            b = QtWidgets.QPushButton(label)
            b.setObjectName("chipBtn")
            b.setCursor(QtCore.Qt.PointingHandCursor)
            b.setSizePolicy(
                QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed
            )
            b.clicked.connect(lambda checked=False, p=prompt: self._quick(p))
            quick.addWidget(b)
        self._quick_body.hide()
        composer_layout.addWidget(self._quick_body)

        # Compact by default (chip 68 + margins 8); grow only when h-scrollbar appears.
        self._ATTACH_STRIP_BASE_H = 76
        self._ATTACH_STRIP_BAR_H = 10
        self._image_strip = QtWidgets.QScrollArea()
        self._image_strip.setObjectName("imageStrip")
        self._image_strip.setWidgetResizable(True)
        self._image_strip.setFrameShape(QtWidgets.QFrame.NoFrame)
        self._image_strip.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self._image_strip.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self._image_strip.setFixedHeight(self._ATTACH_STRIP_BASE_H)
        self._image_strip.hide()
        strip_host = QtWidgets.QWidget()
        strip_host.setObjectName("imageStripHost")
        self._image_strip_lay = QtWidgets.QHBoxLayout(strip_host)
        self._image_strip_lay.setContentsMargins(2, 4, 2, 4)
        self._image_strip_lay.setSpacing(8)
        self._image_strip_lay.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        self._image_strip_lay.addStretch(1)
        self._image_strip.setWidget(strip_host)
        # Prefer horizontal wheel over QScrollArea's default vertical handling.
        self._image_strip.installEventFilter(self)
        self._image_strip.viewport().installEventFilter(self)
        strip_host.installEventFilter(self)
        self._image_strip.horizontalScrollBar().rangeChanged.connect(
            lambda *_args: self._sync_attach_strip_height()
        )
        composer_layout.addWidget(self._image_strip)

        self.input_edit = QtWidgets.QPlainTextEdit()
        self.input_edit.setObjectName("composerInput")
        self.input_edit.setPlaceholderText(t("composer.placeholder_attach"))
        self.input_edit.setMinimumHeight(48)
        self.input_edit.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
        )
        self.input_edit.setAcceptDrops(True)
        self.input_edit.installEventFilter(self)
        self.input_edit.viewport().installEventFilter(self)
        composer_layout.addWidget(self.input_edit, 1)

        # 底栏：附件 + 状态 + 快捷 / 清空 / 发送·停止（合并）
        action_row = QtWidgets.QHBoxLayout()
        action_row.setSpacing(6)
        action_row.setContentsMargins(0, 0, 0, 0)

        self.image_btn = QtWidgets.QPushButton("+")
        self.image_btn.setObjectName("attachBtn")
        self.image_btn.setFixedSize(26, 26)
        self.image_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.image_btn.setToolTip(t("composer.attach_tip"))
        self.image_btn.clicked.connect(self._on_pick_attachments)

        self.status_label = create_animated_status(composer)
        self.status_label.setObjectName("composerStatus")
        self.status_label.setMinimumWidth(0)
        self.status_label.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred
        )

        self._quick_toggle = QtWidgets.QPushButton(t("composer.quick"))
        self._quick_toggle.setObjectName("quickCmdBtn")
        self._quick_toggle.setCursor(QtCore.Qt.PointingHandCursor)
        self._quick_toggle.setCheckable(True)
        self._quick_toggle.setChecked(False)
        self._quick_toggle.setFixedHeight(26)
        self._quick_toggle.setMinimumWidth(44)
        self._quick_toggle.toggled.connect(self._on_quick_commands_toggled)

        clear_btn = QtWidgets.QPushButton(t("composer.clear"))
        clear_btn.setObjectName("composerBtn")
        clear_btn.setFixedSize(44, 26)
        clear_btn.setCursor(QtCore.Qt.PointingHandCursor)
        clear_btn.clicked.connect(self._on_clear)

        # 发送 / 停止 合并：空闲绿「发送」，忙碌红「停止」
        self.send_btn = QtWidgets.QPushButton(t("composer.send"))
        self.send_btn.setObjectName("sendBtn")
        self.send_btn.setFixedSize(56, 26)
        self.send_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.send_btn.clicked.connect(self._on_send_or_stop)
        self._send_busy = False

        action_row.addWidget(self.image_btn, 0, QtCore.Qt.AlignVCenter)
        action_row.addWidget(self.status_label, 1, QtCore.Qt.AlignVCenter)
        action_row.addWidget(self._quick_toggle, 0, QtCore.Qt.AlignVCenter)
        action_row.addWidget(clear_btn, 0, QtCore.Qt.AlignVCenter)
        action_row.addWidget(self.send_btn, 0, QtCore.Qt.AlignVCenter)
        composer_layout.addLayout(action_row)

        self._sync_quick_toggle_label()
        return composer

    def _apply_composer_splitter_sizes(self) -> None:
        splitter = getattr(self, "_chat_splitter", None)
        if splitter is None:
            return
        total = int(splitter.height() or 0)
        if total <= 0:
            QtCore.QTimer.singleShot(50, self._apply_composer_splitter_sizes)
            return
        desired = int(get_config().get("ui.composer_height", 120) or 120)
        min_composer = max(96, int(splitter.widget(1).minimumHeight() or 96))
        max_composer = max(min_composer, total // 2)
        composer_h = max(min_composer, min(desired, max_composer))
        chat_h = max(120, total - composer_h)
        splitter.blockSignals(True)
        splitter.setSizes([chat_h, composer_h])
        splitter.blockSignals(False)

    def _on_composer_splitter_moved(self, *_args) -> None:
        timer = getattr(self, "_composer_save_timer", None)
        if timer is not None:
            timer.start()

    def _persist_composer_height(self) -> None:
        splitter = getattr(self, "_chat_splitter", None)
        if splitter is None:
            return
        sizes = splitter.sizes()
        if len(sizes) < 2 or sizes[1] <= 0:
            return
        cfg = get_config()
        cfg.set("ui.composer_height", int(sizes[1]))
        try:
            cfg.save_user()
        except Exception:
            pass

    def _sync_quick_toggle_label(self) -> None:
        if not getattr(self, "_quick_toggle", None):
            return
        expanded = bool(self._quick_toggle.isChecked())
        self._quick_toggle.setText(
            t("composer.collapse") if expanded else t("composer.quick")
        )
        self._quick_toggle.setToolTip(
            t("composer.collapse_tip")
            if expanded
            else t("composer.quick_tip")
        )

    def _on_quick_commands_toggled(self, checked: bool) -> None:
        if hasattr(self, "_quick_body"):
            self._quick_body.setVisible(bool(checked))
        self._sync_quick_toggle_label()

    def _build_settings_tab(self):
        self.settings_panel = None
        self._settings_placeholder = QtWidgets.QWidget()
        self._settings_tab_index = self.tabs.addTab(
            self._settings_placeholder, t("tab.settings")
        )

    def _build_ui_tab(self):
        self.ui_panel = None
        self._ui_placeholder = QtWidgets.QWidget()
        self._ui_tab_index = self.tabs.addTab(self._ui_placeholder, t("tab.ui"))

    def _build_tools_tab(self):
        self.tools_panel = None
        self._tools_placeholder = QtWidgets.QWidget()
        self._tools_tab_index = self.tabs.addTab(
            self._tools_placeholder, t("tab.tools")
        )

    def _build_help_tab(self):
        self.help_panel = None
        self._help_placeholder = QtWidgets.QWidget()
        self._help_tab_index = self.tabs.addTab(self._help_placeholder, t("tab.help"))
        self.tabs.currentChanged.connect(self._on_tab_changed)

    def _on_tab_changed(self, index: int) -> None:
        self._ensure_tab_loaded(index)

    def _ensure_tab_loaded(self, index: int) -> None:
        if index == getattr(self, "_settings_tab_index", -1):
            self._ensure_settings_panel()
        elif index == getattr(self, "_ui_tab_index", -1):
            self._ensure_ui_panel()
        elif index == getattr(self, "_tools_tab_index", -1):
            self._ensure_tools_panel()
        elif index == getattr(self, "_help_tab_index", -1):
            self._ensure_help_panel()

    def _replace_tab_widget(self, index: int, widget) -> None:
        label = self.tabs.tabText(index)
        self.tabs.blockSignals(True)
        self.tabs.removeTab(index)
        self.tabs.insertTab(index, widget, label)
        self.tabs.setCurrentIndex(index)
        self.tabs.blockSignals(False)

    def _ensure_settings_panel(self):
        if self.settings_panel is not None:
            return self.settings_panel
        self.settings_panel = create_settings_panel(
            self, on_saved=self._on_settings_saved
        )
        self._replace_tab_widget(self._settings_tab_index, self.settings_panel)
        return self.settings_panel

    def _ensure_ui_panel(self):
        if self.ui_panel is not None:
            return self.ui_panel
        self.ui_panel = create_ui_panel(self, on_saved=self._on_settings_saved)
        self._replace_tab_widget(self._ui_tab_index, self.ui_panel)
        return self.ui_panel

    def _ensure_tools_panel(self):
        if self.tools_panel is not None:
            return self.tools_panel
        self.tools_panel = create_tools_panel(
            self, on_tool_use=self._use_tool_from_settings
        )
        self._replace_tab_widget(self._tools_tab_index, self.tools_panel)
        return self.tools_panel

    def _ensure_help_panel(self):
        if self.help_panel is not None:
            return self.help_panel
        self.help_panel = create_help_panel(self)
        self._replace_tab_widget(self._help_tab_index, self.help_panel)
        return self.help_panel

    def eventFilter(self, obj, event):
        strip = getattr(self, "_image_strip", None)
        if (
            strip is not None
            and obj is strip
            and event.type() == QtCore.QEvent.Resize
        ):
            # Width changes may show/hide the h-bar; sync after layout settles.
            QtCore.QTimer.singleShot(0, self._sync_attach_strip_height)
        if event.type() == QtCore.QEvent.Wheel and self._is_attach_strip_target(obj):
            if self._scroll_attach_strip_horizontal(event):
                return True
        if self._is_composer_target(obj) and event.type() == QtCore.QEvent.KeyPress:
            mods = event.modifiers()
            ctrl_v = event.key() == QtCore.Qt.Key_V and bool(
                mods & QtCore.Qt.ControlModifier
            )
            try:
                is_paste = bool(event.matches(QtGui.QKeySequence.Paste))
            except Exception:
                is_paste = False
            if (is_paste or ctrl_v) and self._try_paste_images():
                return True
            if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
                mods = event.modifiers()
                # Shift+Enter → 换行；Enter → 发送
                if mods & QtCore.Qt.ShiftModifier:
                    return False
                if mods & (
                    QtCore.Qt.ControlModifier
                    | QtCore.Qt.AltModifier
                    | QtCore.Qt.MetaModifier
                ):
                    return False
                self._on_send()
                return True
        if self._is_composer_target(obj) and event.type() in (
            QtCore.QEvent.DragEnter,
            QtCore.QEvent.DragMove,
        ):
            if self._drop_has_local_files(event):
                event.acceptProposedAction()
                return True
        if self._is_composer_target(obj) and event.type() == QtCore.QEvent.Drop:
            if self._take_dropped_files(event):
                event.acceptProposedAction()
                return True
        return super().eventFilter(obj, event)

    def _is_composer_target(self, obj) -> bool:
        edit = getattr(self, "input_edit", None)
        if edit is None:
            return False
        return obj is edit or obj is edit.viewport()

    def _is_attach_strip_target(self, obj) -> bool:
        strip = getattr(self, "_image_strip", None)
        if strip is None or obj is None:
            return False
        if obj is strip or obj is strip.viewport():
            return True
        host = strip.widget()
        if host is not None and obj is host:
            return True
        # Chips / remove buttons live under the host — still treat as strip.
        try:
            w = obj
            while w is not None:
                if w is host or w is strip:
                    return True
                w = w.parentWidget()
        except Exception:
            pass
        return False

    def _scroll_attach_strip_horizontal(self, event) -> bool:
        strip = getattr(self, "_image_strip", None)
        if strip is None or not strip.isVisible():
            return False
        from maya_agent.ui.qt_wheel import scroll_area_horizontal_by_wheel

        if scroll_area_horizontal_by_wheel(strip, event):
            try:
                event.accept()
            except Exception:
                pass
            return True
        return False

    def _attach_strip_needs_scrollbar(self) -> bool:
        strip = getattr(self, "_image_strip", None)
        if strip is None:
            return False
        try:
            bar = strip.horizontalScrollBar()
            if bar is None:
                return False
            if int(bar.maximum()) > int(bar.minimum()):
                return True
            # Fallback: content wider than viewport before range updates.
            host = strip.widget()
            if host is None:
                return False
            return int(host.sizeHint().width()) > int(strip.viewport().width())
        except Exception:
            return False

    def _sync_attach_strip_height(self) -> None:
        """Tight height by default; expand only while the h-scrollbar is needed."""
        strip = getattr(self, "_image_strip", None)
        if strip is None:
            return
        base = int(getattr(self, "_ATTACH_STRIP_BASE_H", 76) or 76)
        bar_h = int(getattr(self, "_ATTACH_STRIP_BAR_H", 10) or 10)
        if not strip.isVisible():
            if strip.height() != base:
                strip.setFixedHeight(base)
            return
        need_bar = self._attach_strip_needs_scrollbar()
        target = base + (bar_h if need_bar else 0)
        if int(strip.height()) != target:
            strip.setFixedHeight(target)

    def _show_welcome(self):
        self.chat.clear()

    def _norm_session_id(self, value) -> str:
        if value is None:
            return ""
        return str(value).strip()

    def _find_session_combo_index(self, session_id) -> int:
        target = self._norm_session_id(session_id)
        if not target:
            return -1
        for i in range(self.session_combo.count()):
            item_id = self._norm_session_id(
                self.session_combo.itemData(i, QtCore.Qt.UserRole)
            )
            if item_id == target:
                return i
        return -1

    def _select_session_in_combo(self, session_id) -> None:
        row = self._find_session_combo_index(session_id)
        if row < 0:
            self._refresh_session_combo(select_id=session_id)
            return
        self.session_combo.blockSignals(True)
        self.session_combo.setCurrentIndex(-1)
        self.session_combo.setCurrentIndex(row)
        self.session_combo.blockSignals(False)
        # Maya/Qt 有时 clear 后不会立即刷新显示文本，延迟再设一次
        QtCore.QTimer.singleShot(
            0,
            lambda r=row: self._force_combo_index(r),
        )

    def _force_combo_index(self, row: int) -> None:
        if row < 0 or row >= self.session_combo.count():
            return
        self.session_combo.blockSignals(True)
        if self.session_combo.currentIndex() != row:
            self.session_combo.setCurrentIndex(row)
        self.session_combo.blockSignals(False)

    def _refresh_session_combo(self, select_id=None):
        target_id = self._norm_session_id(
            select_id or self.sessions.active().id
        )
        self.session_combo.blockSignals(True)
        self.session_combo.clear()
        for s in self.sessions.list_sessions():
            self.session_combo.addItem(s.title)
            idx = self.session_combo.count() - 1
            self.session_combo.setItemData(idx, s.id, QtCore.Qt.UserRole)

        row = self._find_session_combo_index(target_id)
        if row < 0 and self.session_combo.count() > 0:
            row = 0
        if row >= 0:
            self.session_combo.setCurrentIndex(row)
        self.session_combo.blockSignals(False)
        if row >= 0:
            QtCore.QTimer.singleShot(
                0,
                lambda r=row: self._force_combo_index(r),
            )
        self.scene_hint.setText(self.sessions.scene_label())
        self.scene_hint.setToolTip(self.sessions.storage_hint())

    def _cancel_pending_save(self):
        if self._save_timer.isActive():
            self._save_timer.stop()

    def _persist_active_session(self, *, refresh_combo=False):
        if self._session_switching:
            return
        try:
            active_id = self.sessions.active().id
            self.sessions.sync_session(
                active_id,
                self.agent.memory.messages,
                self.chat.blocks,
            )
            if refresh_combo:
                self._refresh_session_combo(select_id=active_id)
                self._select_session_in_combo(active_id)
        except Exception:
            pass

    def _apply_session(self, session):
        self._stream_buf = ""
        self._thinking_buf = ""
        if self._stream_timer.isActive():
            self._stream_timer.stop()
        if self.chat._current is not None:
            self.chat.finish_assistant()
        blocks = session.ui_blocks
        if blocks:
            self.agent.load_session_memory(session.memory)
            self.chat.restore_blocks(blocks)
        else:
            self.agent.reset()
            self._show_welcome()

    def _load_active_session(self):
        self._cancel_pending_save()
        self._session_switching = True
        try:
            active = self.sessions.active()
            self._apply_session(active)
            self._refresh_session_combo(select_id=active.id)
            self._select_session_in_combo(active.id)
        finally:
            self._session_switching = False

    def _schedule_persist(self):
        if self._session_switching:
            return
        self._cancel_pending_save()
        self._save_timer.start()

    def persist_sessions(self):
        self._persist_active_session(refresh_combo=True)

    def on_scene_changed(self, reload_only: bool = True):
        if self._worker and self._worker.isRunning():
            return
        self._cancel_pending_save()
        # Flush UI into the *currently bound* project and save to that
        # project's sidecar first. Do NOT write into the newly opened
        # scene path — get_maya_scene_path() already points there.
        self._persist_active_session(refresh_combo=False)
        self.sessions.reload_from_disk()
        self._load_active_session()
        if reload_only:
            self.status_label.setText(t("session.project_switched"))

    def _on_session_activated(self, index: int):
        if self._session_switching:
            return
        sid = self._norm_session_id(
            self.session_combo.itemData(index, QtCore.Qt.UserRole)
        )
        if not sid:
            return
        if sid == self._norm_session_id(self.sessions.active().id):
            return
        if self._worker and self._worker.isRunning():
            QtWidgets.QMessageBox.information(
                self, t("session.switch_title"), t("session.switch_busy")
            )
            self._select_session_in_combo(self.sessions.active().id)
            return

        self._cancel_pending_save()
        self._session_switching = True
        session = None
        try:
            prev_id = self.sessions.active().id
            self.sessions.sync_session(
                prev_id,
                self.agent.memory.messages,
                self.chat.blocks,
            )
            session = self.sessions.switch(sid)
            self._apply_session(session)
            self._refresh_session_combo(select_id=session.id)
            self._select_session_in_combo(session.id)
        except KeyError:
            self._refresh_session_combo()
            self.status_label.setText(t("session.switch_fail"))
            return
        except Exception:
            self._refresh_session_combo()
            self.status_label.setText(t("session.switch_error"))
            return
        finally:
            self._session_switching = False

        if session is not None:
            self.status_label.setText(t("session.switched", title=session.title))

    def _on_new_session(self):
        if self._worker and self._worker.isRunning():
            return
        self._cancel_pending_save()
        self._persist_active_session(refresh_combo=False)
        session = self.sessions.create_session(t("session.default_title"), set_active=True)
        self._session_switching = True
        try:
            self.agent.reset()
            self._show_welcome()
            self._refresh_session_combo(select_id=session.id)
            self._select_session_in_combo(session.id)
        finally:
            self._session_switching = False
        self.status_label.setText(t("session.created", title=session.title))

    def _on_rename_session(self):
        sid = self.session_combo.currentData() or self.sessions.active().id
        session = self.sessions.project.get_session(sid)
        if not session:
            return
        text, ok = QtWidgets.QInputDialog.getText(
            self,
            t("session.rename_title"),
            t("session.rename_prompt"),
            QtWidgets.QLineEdit.Normal,
            session.title,
        )
        if ok and text.strip():
            self.sessions.rename(sid, text.strip())
            self._refresh_session_combo()

    def _on_delete_session(self):
        sid = self.session_combo.currentData() or self.sessions.active().id
        title = self.session_combo.currentText()
        reply = QtWidgets.QMessageBox.question(
            self,
            t("session.delete_title"),
            t("session.delete_confirm", title=title),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        # Last session: create a replacement first so delete can proceed.
        if len(self.sessions.project.sessions) <= 1:
            self.sessions.create_session(
                t("session.default_title"), set_active=True
            )
        new_active = self.sessions.delete(sid)
        if new_active is None:
            self.sessions.create_session(
                t("session.default_title"), set_active=True
            )
        self._session_switching = True
        try:
            self._load_active_session()
        finally:
            self._session_switching = False
        self.status_label.setText(t("session.deleted"))

    def _flush_stream(self):
        if self._thinking_buf:
            piece = self._thinking_buf
            self._thinking_buf = ""
            self.chat.append_thinking(piece)
        if self._stream_buf:
            piece = self._stream_buf
            self._stream_buf = ""
            self.chat.append_assistant_text(piece)

    def _on_settings_saved(self, language_changed: bool = False):
        get_config().reload()
        init_from_config()
        if language_changed:
            # Rebuild UI so all labels pick up the new catalog
            QtCore.QTimer.singleShot(0, reopen_main_window)
            return
        self.setStyleSheet(load_stylesheet_safe())
        self._apply_provider_from_config()
        ui_panel = getattr(self, "ui_panel", None)
        if ui_panel is not None:
            try:
                ui_panel.reload_from_config()
            except Exception:
                pass
        QtCore.QTimer.singleShot(0, self._apply_composer_splitter_sizes)

    def _use_tool_from_settings(self, name: str):
        self.input_edit.setPlainText(t("composer.use_tool", name=name))
        idx = getattr(self, "_chat_tab_index", 0)
        self.tabs.setCurrentIndex(idx)
        self.input_edit.setFocus()

    def _apply_provider_from_config(self):
        cfg = get_config()
        pid = cfg.get("llm.active_provider", "deepseek")
        model = cfg.get(f"providers.{pid}.default_model", "")
        if pid:
            self.agent.set_provider(pid, model or None)
        self._refresh_image_input()

    def _refresh_image_input(self):
        cfg = get_config()
        pid = cfg.get("llm.active_provider", "deepseek")
        model = (cfg.get(f"providers.{pid}.default_model", "") or "").strip()
        self._vision_enabled = model_supports_vision(pid, model)
        busy = bool(self._worker and self._worker.isRunning())
        if hasattr(self, "image_btn"):
            self.image_btn.setEnabled(not busy)
            self.image_btn.setToolTip(t("composer.attach_tip"))
        if hasattr(self, "input_edit"):
            self.input_edit.setPlaceholderText(t("composer.placeholder_attach"))
        # Vision-only image payloads cannot be sent without a vision model —
        # demote them to path-based file attachments when possible is not available
        # (ImageAttachment has no original path), so clear pending images.
        if not self._vision_enabled and self._pending_images:
            self._pending_images = []
            self._rebuild_attach_strip()

    def _on_pick_attachments(self):
        paths, _selected = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            t("composer.pick_files"),
            "",
            t("composer.file_filter"),
        )
        if not paths:
            return
        self._ingest_local_paths(paths)

    def _try_paste_images(self) -> bool:
        try:
            found = attachments_from_clipboard(QtWidgets.QApplication.clipboard())
        except Exception:
            return False
        if not found:
            return False
        if not self._vision_enabled:
            self.status_label.set_idle(t("status.no_vision"))
            return True
        self._add_pending_images(found)
        return True

    def _drop_has_local_files(self, event) -> bool:
        mime = event.mimeData()
        if mime is None or not mime.hasUrls():
            return False
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            if path and QtCore.QFileInfo(path).isFile():
                return True
        return False

    def _take_dropped_files(self, event) -> bool:
        if not self._drop_has_local_files(event):
            return False
        mime = event.mimeData()
        if mime is None:
            return False
        paths = []
        for url in mime.urls() or []:
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            if path and QtCore.QFileInfo(path).isFile():
                paths.append(path)
        if not paths:
            return False
        self._ingest_local_paths(paths)
        return True

    def _file_ref_from_path(self, path: str) -> Optional[dict]:
        info = QtCore.QFileInfo(path)
        if not info.isFile():
            return None
        abs_path = info.absoluteFilePath().replace("\\", "/")
        return {
            "path": abs_path,
            "name": info.fileName() or abs_path.rsplit("/", 1)[-1],
            "size_bytes": int(info.size()),
        }

    def _ingest_local_paths(self, paths) -> None:
        """Classify paths into vision images (when supported) or file attachments."""
        images = []
        files = []
        errors = []
        for path in paths or []:
            path = (path or "").strip()
            if not path:
                continue
            if is_image_path(path) and self._vision_enabled:
                try:
                    images.append(attachment_from_path(path))
                    continue
                except Exception as e:
                    # Fall through: still attach as a file path for tools.
                    errors.append(str(e))
            ref = self._file_ref_from_path(path)
            if ref is None:
                errors.append(t("status.file_missing", path=path))
                continue
            files.append(ref)
        self._add_pending_images(images)
        self._add_pending_files(files)
        if errors:
            self.status_label.set_idle(errors[0])

    def _add_pending_images(self, images) -> None:
        if not images:
            return
        room = MAX_IMAGES - len(self._pending_images)
        if room <= 0:
            self.status_label.set_idle(t("status.max_images", n=MAX_IMAGES))
            return
        extra = list(images)
        if len(extra) > room:
            self.status_label.set_idle(t("status.max_images", n=MAX_IMAGES))
            extra = extra[:room]
        self._pending_images.extend(extra)
        self._rebuild_attach_strip()

    def _add_pending_files(self, files) -> None:
        if not files:
            return
        existing = {str(f.get("path") or "") for f in self._pending_files}
        room = MAX_CHAT_FILES - len(self._pending_files)
        if room <= 0:
            self.status_label.set_idle(t("status.max_files", n=MAX_CHAT_FILES))
            return
        extra = []
        for f in files:
            p = str(f.get("path") or "")
            if not p or p in existing:
                continue
            existing.add(p)
            extra.append(f)
            if len(extra) >= room:
                if len(files) > len(extra):
                    self.status_label.set_idle(
                        t("status.max_files", n=MAX_CHAT_FILES)
                    )
                break
        if not extra:
            return
        self._pending_files.extend(extra)
        self._rebuild_attach_strip()

    def _format_size(self, size_bytes: int) -> str:
        try:
            n = int(size_bytes or 0)
        except (TypeError, ValueError):
            n = 0
        if n < 1024:
            return f"{n} B"
        if n < 1024 * 1024:
            return f"{n / 1024:.1f} KB"
        if n < 1024 * 1024 * 1024:
            return f"{n / (1024 * 1024):.1f} MB"
        return f"{n / (1024 * 1024 * 1024):.1f} GB"

    @staticmethod
    def _file_ext_style(name: str):
        """Return (badge_text, bg_hex, fg_hex) for a file chip badge."""
        ext = ""
        raw = name or ""
        if "." in raw:
            ext = raw.rsplit(".", 1)[-1].lower().strip()
        badge = (ext[:4].upper() if ext else "FILE") or "FILE"
        # (extensions, bg, fg)
        groups = (
            (
                {"mp4", "mov", "avi", "mkv", "webm", "wmv", "m4v"},
                "#3a2848",
                "#e0b8ff",
            ),
            (
                {
                    "fbx",
                    "obj",
                    "abc",
                    "glb",
                    "gltf",
                    "usd",
                    "usda",
                    "usdc",
                    "ma",
                    "mb",
                    "blend",
                    "stl",
                    "ply",
                },
                "#1e3648",
                "#9fd0f5",
            ),
            (
                {"png", "jpg", "jpeg", "webp", "gif", "bmp", "tga", "exr", "tif", "tiff"},
                "#1e3a2a",
                "#9fd4b0",
            ),
            (
                {"wav", "mp3", "flac", "ogg", "aac", "aiff"},
                "#3a3420",
                "#e8d080",
            ),
            (
                {"py", "mel", "js", "ts", "json", "yaml", "yml", "xml", "cs", "cpp", "h"},
                "#282848",
                "#b8b8f0",
            ),
            (
                {"zip", "rar", "7z", "tar", "gz"},
                "#3a2e20",
                "#e0b888",
            ),
            (
                {"txt", "md", "csv", "log", "pdf", "doc", "docx"},
                "#243038",
                "#a8c8d8",
            ),
        )
        for exts, bg, fg in groups:
            if ext in exts:
                return badge, bg, fg
        return badge, "#2a2b34", "#b4b4bc"

    def _make_remove_btn(self, on_click) -> "QtWidgets.QPushButton":
        remove = QtWidgets.QPushButton("×")
        remove.setObjectName("imageChipRemove")
        remove.setFixedSize(18, 18)
        remove.setCursor(QtCore.Qt.PointingHandCursor)
        remove.setToolTip(t("composer.remove_attach"))
        remove.clicked.connect(on_click)
        return remove

    def _make_file_chip(self, fref: dict, index: int) -> "QtWidgets.QFrame":
        name = fref.get("name") or t("composer.file_alt")
        size_text = self._format_size(int(fref.get("size_bytes") or 0))
        path = fref.get("path") or ""
        badge_text, bg, fg = self._file_ext_style(name)

        chip = QtWidgets.QFrame()
        chip.setObjectName("fileChip")
        chip.setFixedSize(168, 60)
        chip.setAttribute(QtCore.Qt.WA_Hover, True)
        tip = name if not path else f"{name}\n{size_text}\n{path}"
        chip.setToolTip(tip)
        chip.setCursor(QtCore.Qt.ArrowCursor)

        root = QtWidgets.QGridLayout(chip)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QtWidgets.QWidget(chip)
        row = QtWidgets.QHBoxLayout(body)
        row.setContentsMargins(8, 8, 22, 8)
        row.setSpacing(8)

        badge = QtWidgets.QLabel(badge_text)
        badge.setObjectName("fileChipBadge")
        badge.setFixedSize(40, 40)
        badge.setAlignment(QtCore.Qt.AlignCenter)
        badge.setStyleSheet(
            f"QLabel#fileChipBadge {{"
            f" background-color: {bg}; color: {fg};"
            f" border: none; border-radius: 8px;"
            f" font-size: 10px; font-weight: 700;"
            f" }}"
        )

        text_col = QtWidgets.QVBoxLayout()
        text_col.setContentsMargins(0, 2, 0, 2)
        text_col.setSpacing(2)

        name_lbl = QtWidgets.QLabel()
        name_lbl.setObjectName("fileChipName")
        name_lbl.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        fm = name_lbl.fontMetrics()
        name_lbl.setText(fm.elidedText(name, QtCore.Qt.ElideMiddle, 108))
        name_lbl.setToolTip(name)

        meta_lbl = QtWidgets.QLabel(size_text)
        meta_lbl.setObjectName("fileChipMeta")
        meta_lbl.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)

        text_col.addWidget(name_lbl)
        text_col.addWidget(meta_lbl)
        row.addWidget(badge, 0, QtCore.Qt.AlignVCenter)
        row.addLayout(text_col, 1)

        remove = self._make_remove_btn(
            lambda checked=False, i=index: self._remove_pending_file(i)
        )
        root.addWidget(body, 0, 0)
        root.addWidget(remove, 0, 0, QtCore.Qt.AlignTop | QtCore.Qt.AlignRight)
        return chip

    def _rebuild_attach_strip(self) -> None:
        lay = self._image_strip_lay
        while lay.count() > 1:
            item = lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        has_any = bool(self._pending_images or self._pending_files)
        if not has_any:
            self._image_strip.hide()
            self._sync_attach_strip_height()
            return
        for idx, img in enumerate(self._pending_images):
            chip = QtWidgets.QFrame()
            chip.setObjectName("imageChip")
            chip.setFixedSize(68, 68)
            chip.setAttribute(QtCore.Qt.WA_Hover, True)
            chip.setToolTip(img.name or img.mime or t("composer.image_alt"))
            box = QtWidgets.QGridLayout(chip)
            box.setContentsMargins(4, 4, 4, 4)
            box.setSpacing(0)
            from maya_agent.ui.image_viewer import make_clickable_thumb

            thumb = make_clickable_thumb(
                img,
                edge=56,
                fixed_w=60,
                fixed_h=60,
                parent=chip,
                gallery=list(self._pending_images),
                index=idx,
                tooltip=img.name or img.mime or t("composer.image_alt"),
                stylesheet=(
                    "QLabel {"
                    " background:#14151a; border:none; border-radius:6px;"
                    " }"
                ),
            )
            remove = self._make_remove_btn(
                lambda checked=False, i=idx: self._remove_pending_image(i)
            )
            box.addWidget(thumb, 0, 0)
            box.addWidget(remove, 0, 0, QtCore.Qt.AlignTop | QtCore.Qt.AlignRight)
            chip.installEventFilter(self)
            lay.insertWidget(lay.count() - 1, chip)
        for idx, fref in enumerate(self._pending_files):
            chip = self._make_file_chip(fref, idx)
            chip.installEventFilter(self)
            lay.insertWidget(lay.count() - 1, chip)
        self._image_strip.show()
        # Height depends on whether content overflows — update after layout.
        self._sync_attach_strip_height()
        QtCore.QTimer.singleShot(0, self._sync_attach_strip_height)

    def _remove_pending_image(self, index: int) -> None:
        if 0 <= index < len(self._pending_images):
            del self._pending_images[index]
            self._rebuild_attach_strip()

    def _remove_pending_file(self, index: int) -> None:
        if 0 <= index < len(self._pending_files):
            del self._pending_files[index]
            self._rebuild_attach_strip()

    def _build_file_attachment_note(self, staged: list) -> str:
        if not staged:
            return ""
        lines = [t("composer.attached_files_header")]
        for item in staged:
            name = item.get("original_name") or item.get("name") or ""
            path = item.get("path") or ""
            if name and path:
                lines.append(f"- {name}: {path}")
            elif path:
                lines.append(f"- {path}")
        return "\n".join(lines)

    def _confirm_destructive(self, name: str, args: dict) -> bool:
        # 「允许本轮对话执行」后，本轮内后续危险工具不再弹窗
        if self._skip_confirm_this_turn:
            return True

        args_text = json.dumps(args, ensure_ascii=False, indent=2)
        if len(args_text) > 600:
            args_text = args_text[:600] + "\n…"

        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle(t("confirm.title"))
        box.setIcon(QtWidgets.QMessageBox.Question)
        box.setText(t("confirm.body", name=name))
        box.setInformativeText(t("confirm.args", args=args_text))

        btn_once = box.addButton(
            t("confirm.allow_once"), QtWidgets.QMessageBox.AcceptRole
        )
        btn_turn = box.addButton(
            t("confirm.allow_turn"), QtWidgets.QMessageBox.ActionRole
        )
        btn_no = box.addButton(t("confirm.cancel"), QtWidgets.QMessageBox.RejectRole)
        box.setDefaultButton(btn_once)
        box.exec_()

        clicked = box.clickedButton()
        if clicked is btn_turn:
            self._skip_confirm_this_turn = True
            return True
        if clicked is btn_once:
            return True
        return False

    def _quick(self, prompt: str):
        self.input_edit.setPlainText(prompt)
        self._on_send()

    def _on_choice_reply(self, reply: str):
        """Auto-send when user clicks a confirmation button."""
        text = (reply or "").strip()
        if not text:
            return
        if self._worker and self._worker.isRunning():
            return
        self.input_edit.setPlainText(text)
        self._on_send()

    def _on_clear(self):
        reply = QtWidgets.QMessageBox.question(
            self,
            t("composer.clear_title"),
            t("composer.clear_confirm"),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        self._cancel_pending_save()
        self.sessions.reset_active()
        self.agent.reset()
        self._pending_images = []
        self._pending_files = []
        self._rebuild_attach_strip()
        self._show_welcome()
        self._persist_active_session(refresh_combo=True)
        self.status_label.set_idle(t("status.cleared"))

    def _on_send_or_stop(self):
        if getattr(self, "_send_busy", False):
            self._on_stop()
        else:
            self._on_send()

    def _on_stop(self):
        self._stopped_by_user = True
        self._stream_timer.stop()
        try:
            self.agent.request_cancel()
        except Exception:
            pass
        if self._worker and self._worker.isRunning():
            try:
                self._worker.signals.event.disconnect(self._on_event)
            except Exception:
                pass
            # Brief cooperative wait (keep UI responsive — short only).
            self._worker.wait(800)
            if self._worker.isRunning():
                self._schedule_force_kill_worker()
        try:
            self.agent.undo.cancel_open()
        except Exception:
            pass
        try:
            self.agent.memory.drop_incomplete_tool_round()
        except Exception:
            pass
        # Finish the bubble immediately so late stream events cannot reopen it.
        self._flush_stream()
        self._stream_buf = ""
        self._thinking_buf = ""
        self.chat.finish_assistant(
            stop_notice=stop_notice_for_reason("user_cancel")
        )
        self._set_busy(False)
        self._skip_confirm_this_turn = False
        self.status_label.set_idle(t("status.stopped"))
        self._schedule_persist()

    def _schedule_force_kill_worker(self) -> None:
        """If cooperative cancel stalls, terminate after a longer grace period."""
        worker = self._worker
        if worker is None:
            return

        def _check():
            w = getattr(self, "_worker", None)
            if w is None or w is not worker:
                return
            if not w.isRunning():
                return
            try:
                w.terminate()
                w.wait(1000)
            except Exception:
                pass
            try:
                from maya_agent.bridge.agent_remote import force_reset_agent_lock

                force_reset_agent_lock()
            except Exception:
                pass

        QtCore.QTimer.singleShot(10000, _check)

    def _apply_send_stop_style(self, busy: bool) -> None:
        """Toggle merged send/stop button label and QSS objectName."""
        self._send_busy = bool(busy)
        apply_send_stop_style(getattr(self, "send_btn", None), busy)

    def _set_busy(self, busy: bool):
        self._apply_send_stop_style(busy)
        self.input_edit.setReadOnly(busy)
        if hasattr(self, "image_btn"):
            self.image_btn.setEnabled(not busy)

    def _on_send(self):
        text = self.input_edit.toPlainText().strip()
        images = list(self._pending_images)
        files = list(self._pending_files)
        if not text and not images and not files:
            return
        if self._worker and self._worker.isRunning():
            return
        if images and not self._vision_enabled:
            self.status_label.set_idle(t("status.no_vision"))
            return

        pid = get_config().get("llm.active_provider", "deepseek")
        model = (
            get_config().get(f"providers.{pid}.default_model", "") or ""
        ).strip()
        if pid:
            self.agent.set_provider(pid, model or None)
        self._vision_enabled = model_supports_vision(pid, model)
        if images and not self._vision_enabled:
            self.status_label.set_idle(t("status.no_vision"))
            self._refresh_image_input()
            return

        staged_files = []
        if files:
            try:
                staged_files = stage_chat_files([f.get("path") for f in files])
            except Exception as e:
                self.status_label.set_idle(str(e))
                return
            if not staged_files:
                self.status_label.set_idle(t("status.attach_failed"))
                return

        file_note = self._build_file_attachment_note(staged_files)
        if text and file_note:
            agent_text = f"{text}\n\n{file_note}"
        elif file_note:
            agent_text = file_note
        elif text:
            agent_text = text
        else:
            agent_text = t("composer.view_image")

        if text:
            display = text
            if staged_files:
                names = ", ".join(
                    (x.get("original_name") or x.get("name") or "")
                    for x in staged_files
                )
                display = f"{text}\n{t('composer.attached_files_short', names=names)}"
        elif staged_files:
            names = ", ".join(
                (x.get("original_name") or x.get("name") or "") for x in staged_files
            )
            display = t("composer.attached_files_short", names=names)
        else:
            display = t("composer.view_image")

        self.chat.add_user(display, images=images or None)
        self.chat.begin_assistant()
        self._stream_buf = ""
        self._thinking_buf = ""
        self._skip_confirm_this_turn = False
        self._stopped_by_user = False
        self.input_edit.clear()
        self._pending_images = []
        self._pending_files = []
        self._rebuild_attach_strip()
        self._set_busy(True)
        self.status_label.set_thinking()

        stream = bool(get_config().get("agent.stream", True))
        self._worker = create_agent_worker(
            self.agent, agent_text, stream, images or None, parent=self
        )
        self._worker.signals.event.connect(self._on_event)
        self._worker.signals.finished.connect(self._on_finished)
        self._worker.signals.failed.connect(self._on_failed)
        self._worker.start()

    def _on_event(self, event: dict):
        if getattr(self, "_stopped_by_user", False):
            return
        et = event.get("type")
        handler = {
            "thinking": self._evt_thinking,
            "text": self._evt_text,
            "tool_start": self._evt_tool_start,
            "tool_progress": self._evt_tool_progress,
            "tool_end": self._evt_tool_end,
            "vision_context": self._evt_vision_context,
            "chat_images_staged": self._evt_chat_images_staged,
            "error": self._evt_error,
            "stopped": self._evt_stopped,
            "done": self._evt_done,
            "undo_ready": self._evt_undo_ready,
        }.get(et)
        if handler:
            handler(event)

    def _evt_thinking(self, event: dict) -> None:
        if not get_config().get("agent.show_thinking", True):
            return
        self._thinking_buf += event.get("content", "")
        if not self._stream_timer.isActive():
            self._stream_timer.start()

    def _evt_text(self, event: dict) -> None:
        if self._thinking_buf:
            self._flush_stream()
            self.chat.finish_thinking()
        self._stream_buf += event.get("content", "")
        if not self._stream_timer.isActive():
            self._stream_timer.start()

    def _evt_tool_start(self, event: dict) -> None:
        self._flush_stream()
        self.chat.finish_thinking()
        if get_config().get("agent.show_tool_calls", True):
            self.chat.tool_start(event.get("name", ""))
            self.status_label.set_tool(event.get("name", ""))

    def _evt_tool_progress(self, event: dict) -> None:
        name = event.get("name", "")
        progress = event.get("progress")
        status = event.get("status", "")
        message = event.get("message", "")
        if get_config().get("agent.show_tool_calls", True):
            self.chat.tool_progress(
                name=name,
                progress=progress,
                status=status,
                message=message,
            )
        self.status_label.set_tool_progress(
            name=name or getattr(self.status_label, "_tool_name", ""),
            progress=progress,
            status=status,
        )

    def _evt_tool_end(self, event: dict) -> None:
        self._flush_stream()
        if get_config().get("agent.show_tool_calls", True):
            self.chat.tool_end(
                event.get("name", ""),
                event.get("result") or "",
                images=event.get("images"),
            )
        if self._worker and self._worker.isRunning():
            self.status_label.set_thinking()

    def _evt_vision_context(self, event: dict) -> None:
        count = int(event.get("count") or 0)
        if count:
            self.status_label.set_idle(t("status.vision_context", count=count))
        if self._worker and self._worker.isRunning():
            self.status_label.set_thinking()

    def _evt_chat_images_staged(self, event: dict) -> None:
        count = int(event.get("count") or 0)
        if count:
            self.status_label.set_idle(f"已保存 {count} 张对话附图到本地")
        if self._worker and self._worker.isRunning():
            self.status_label.set_thinking()

    def _evt_error(self, event: dict) -> None:
        self._flush_stream()
        self.chat.finish_thinking()
        if self.chat._current is not None:
            self.chat.finish_assistant(
                stop_notice=event.get("stop_notice")
                or stop_notice_for_reason("llm_error")
            )
        self.chat.add_error(event.get("content", ""))

    def _evt_stopped(self, event: dict) -> None:
        self._flush_stream()
        self.chat.finish_thinking()
        notice = (
            event.get("stop_notice")
            or stop_notice_for_reason(event.get("reason") or "")
        )
        final = event.get("content")
        self.chat.finish_assistant(
            final if final else None,
            model=event.get("model") or "",
            usage=event.get("usage") or {},
            llm_calls=int(event.get("llm_calls") or 0),
            stop_notice=notice,
        )
        self.status_label.set_idle(t("status.stopped"))

    def _evt_done(self, event: dict) -> None:
        self._flush_stream()
        self.chat.finish_thinking()
        final = event.get("content")
        self.chat.finish_assistant(
            final if final else None,
            model=event.get("model") or "",
            usage=event.get("usage") or {},
            llm_calls=int(event.get("llm_calls") or 0),
            stop_notice=event.get("stop_notice") or "",
        )

    def _evt_undo_ready(self, event: dict) -> None:
        if event.get("can_undo"):
            tip = self.status_label.text()
            if tip in (
                t("status.ready"),
                "",
                t("status.thinking"),
                t("status.thinking") + "…",
            ):
                self.status_label.set_idle(t("status.ready_undo"))

    def _on_finished(self):
        if self._stopped_by_user:
            self._stopped_by_user = False
            self._stream_timer.stop()
            self._schedule_persist()
            return
        self._flush_stream()
        # ensure assistant bubble finalized (idempotent-ish)
        if self.chat._current is not None:
            self.chat.finish_assistant()
        self._stream_timer.stop()
        self._skip_confirm_this_turn = False
        self._set_busy(False)
        if self.agent.undo.can_undo:
            self.status_label.set_idle(t("status.ready_undo"))
        else:
            self.status_label.set_idle(t("status.ready"))
        self._schedule_persist()

    def _on_failed(self, err: str):
        if self._stopped_by_user:
            # terminate() may surface as failure — tip already shown in _on_stop
            self._stopped_by_user = False
            self._stream_timer.stop()
            self._set_busy(False)
            self._schedule_persist()
            return
        self._flush_stream()
        if self.chat._current is not None:
            self.chat.finish_assistant(
                stop_notice=stop_notice_for_reason("worker_error")
            )
        self.chat.add_error(err)
        self._stream_timer.stop()
        self._skip_confirm_this_turn = False
        self._set_busy(False)
        self.status_label.set_error(t("status.error"))
        self._schedule_persist()

    def closeEvent(self, event):
        global _WINDOW_INSTANCE
        try:
            self.persist_sessions()
        except Exception:
            pass
        try:
            from maya_agent.bridge import unregister_panel_agent

            unregister_panel_agent(self.agent)
        except Exception:
            pass
        _WINDOW_INSTANCE = None
        super().closeEvent(event)
