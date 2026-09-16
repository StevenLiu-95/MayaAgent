"""Main dockable Maya Agent window."""

from __future__ import annotations

import json
import traceback

from maya_agent import __app_name__, __version__
from maya_agent.core.agent import MayaAgent
from maya_agent.core.session_manager import SessionManager
from maya_agent.ui.chat_widgets import create_chat_panel
from maya_agent.ui.combo_widgets import create_toolbar_combo
from maya_agent.ui.settings_panel import (
    create_help_panel,
    create_settings_panel,
    create_tools_panel,
)
from maya_agent.ui.status_anim import create_animated_status
from maya_agent.ui.stylesheets import load_stylesheet
from maya_agent.utils.config import get_config
from maya_agent.utils.maya_compat import (
    get_maya_main_window,
    import_qt,
    in_maya,
    maya_version,
    wrap_maya_ptr,
)
from maya_agent.llm.base import stop_notice_for_reason

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
        _, _, QtWidgets, _binding = import_qt()
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
    if in_maya():
        try:
            from maya_agent.ui.dock import show_dockable

            result = show_dockable()
            # Fallback if dock reported OK but nothing usable is visible.
            win = get_window_instance()
            if win is not None:
                try:
                    win.show()
                    win.raise_()
                    win.activateWindow()
                except Exception:
                    pass
            return result
        except Exception:
            pass
    return show_floating_window()


def show_floating_window():
    """Show or raise a floating Maya Agent window."""
    global _WINDOW_INSTANCE
    QtCore, QtGui, QtWidgets, binding = import_qt()

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


class _WorkerSignals:
    @staticmethod
    def create(QtCore):
        class Signals(QtCore.QObject):
            event = QtCore.Signal(dict)
            finished = QtCore.Signal()
            failed = QtCore.Signal(str)

        return Signals()


def _create_worker(QtCore, agent: MayaAgent, text: str, stream: bool):
    class Worker(QtCore.QThread):
        def __init__(self):
            super().__init__()
            self.signals = _WorkerSignals.create(QtCore)

        def run(self):
            try:
                for event in agent.chat(text, stream=stream):
                    self.signals.event.emit(event)
                self.signals.finished.emit()
            except Exception:
                self.signals.failed.emit(traceback.format_exc())

    return Worker()


class MayaAgentWindow:
    """Dynamically builds QMainWindow subclass with current Qt binding."""

    def __new__(cls, parent=None):
        QtCore, QtGui, QtWidgets, _ = import_qt()

        class _MayaAgentWindow(QtWidgets.QMainWindow):
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
                self.sessions = SessionManager()
                self._session_switching = False
                self._worker = None
                self._skip_confirm_this_turn = False
                self._stopped_by_user = False
                self._stream_buf = ""
                self._thinking_buf = ""
                self._stream_timer = QtCore.QTimer(self)
                self._stream_timer.setSingleShot(True)
                self._stream_timer.setInterval(80)
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
                self._build_tools_tab()
                self._build_help_tab()

            def _build_session_bar(self):
                session_wrap = QtWidgets.QFrame()
                session_wrap.setObjectName("sessionFrame")
                session_row = QtWidgets.QHBoxLayout(session_wrap)
                session_row.setContentsMargins(0, 0, 0, 0)
                session_row.setSpacing(6)

                session_lab = QtWidgets.QLabel("会话")
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

                new_sess_btn = QtWidgets.QPushButton("新建")
                new_sess_btn.setObjectName("toolbarBtn")
                new_sess_btn.setFixedSize(52, 28)
                new_sess_btn.setCursor(QtCore.Qt.PointingHandCursor)
                new_sess_btn.clicked.connect(self._on_new_session)

                rename_sess_btn = QtWidgets.QPushButton("重命名")
                rename_sess_btn.setObjectName("toolbarBtn")
                rename_sess_btn.setFixedSize(64, 28)
                rename_sess_btn.setCursor(QtCore.Qt.PointingHandCursor)
                rename_sess_btn.clicked.connect(self._on_rename_session)

                del_sess_btn = QtWidgets.QPushButton("删除")
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
                chat_layout.setSpacing(8)

                chat_layout.addWidget(self._build_session_bar())

                self.chat = create_chat_panel(chat_page)
                self.chat.set_choice_handler(self._on_choice_reply)
                chat_layout.addWidget(self.chat, 1)

                composer = QtWidgets.QFrame()
                composer.setObjectName("composerFrame")
                composer_layout = QtWidgets.QVBoxLayout(composer)
                composer_layout.setContentsMargins(8, 8, 8, 8)
                composer_layout.setSpacing(6)

                # 1) AI 执行状态 — 文本框上方（带动画）
                status_row = QtWidgets.QHBoxLayout()
                status_row.setContentsMargins(2, 0, 2, 0)
                self.status_label = create_animated_status(composer)
                status_row.addWidget(self.status_label, 1)
                composer_layout.addLayout(status_row)

                # 2) 输入框
                self.input_edit = QtWidgets.QPlainTextEdit()
                self.input_edit.setObjectName("composerInput")
                self.input_edit.setPlaceholderText("描述你想做的事…  Enter 发送，Shift+Enter 换行")
                self.input_edit.setFixedHeight(78)
                self.input_edit.installEventFilter(self)
                composer_layout.addWidget(self.input_edit)

                # 3) 快捷按钮（可横向滚动） + 清空/停止/发送 — 同一行
                action_row = QtWidgets.QHBoxLayout()
                action_row.setSpacing(8)
                action_row.setContentsMargins(0, 2, 0, 0)

                quick_scroll = QtWidgets.QScrollArea()
                quick_scroll.setObjectName("quickScroll")
                quick_scroll.setWidgetResizable(False)
                quick_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
                quick_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
                quick_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
                quick_scroll.setFixedHeight(42)
                quick_scroll.setSizePolicy(
                    QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
                )
                quick_scroll.viewport().installEventFilter(self)
                self._quick_scroll = quick_scroll

                quick_host = QtWidgets.QWidget()
                quick_host.setObjectName("quickHost")
                quick = QtWidgets.QHBoxLayout(quick_host)
                quick.setContentsMargins(0, 0, 0, 0)
                quick.setSpacing(6)
                quick.setSizeConstraint(QtWidgets.QLayout.SetFixedSize)
                for label, prompt in (
                    ("场景信息", "请查看当前场景信息并简要汇总。"),
                    ("网格统计", "对当前选中的网格做拓扑统计。"),
                    ("导出 FBX", "帮我把当前选择导出为 FBX，先询问保存路径建议。"),
                    ("三点光", "在场景中创建三点布光。"),
                    ("新建场景", "新建一个空场景。"),
                    ("清空场景", "清空当前场景。"),
                ):
                    b = QtWidgets.QPushButton(label)
                    b.setObjectName("chipBtn")
                    b.setCursor(QtCore.Qt.PointingHandCursor)
                    b.setSizePolicy(
                        QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed
                    )
                    b.clicked.connect(lambda checked=False, p=prompt: self._quick(p))
                    quick.addWidget(b)
                quick_scroll.setWidget(quick_host)
                action_row.addWidget(quick_scroll, 1)

                clear_btn = QtWidgets.QPushButton("清空")
                clear_btn.setObjectName("secondaryBtn")
                clear_btn.setFixedWidth(56)
                clear_btn.clicked.connect(self._on_clear)
                self.stop_btn = QtWidgets.QPushButton("停止")
                self.stop_btn.setObjectName("secondaryBtn")
                self.stop_btn.setFixedWidth(56)
                self.stop_btn.setEnabled(False)
                self.stop_btn.clicked.connect(self._on_stop)
                self.send_btn = QtWidgets.QPushButton("发送")
                self.send_btn.setObjectName("sendBtn")
                self.send_btn.setFixedWidth(72)
                self.send_btn.clicked.connect(self._on_send)
                action_row.addWidget(clear_btn, 0)
                action_row.addWidget(self.stop_btn, 0)
                action_row.addWidget(self.send_btn, 0)
                composer_layout.addLayout(action_row)

                chat_layout.addWidget(composer)
                self.tabs.addTab(chat_page, "对话")

            def _build_settings_tab(self):
                self.settings_panel = create_settings_panel(
                    self,
                    on_saved=self._on_settings_saved,
                )
                self.tabs.addTab(self.settings_panel, "设置")

            def _build_tools_tab(self):
                self.tools_panel = create_tools_panel(
                    self,
                    on_tool_use=self._use_tool_from_settings,
                )
                self.tabs.addTab(self.tools_panel, "工具")

            def _build_help_tab(self):
                self.help_panel = create_help_panel(self)
                self.tabs.addTab(self.help_panel, "帮助")

            def eventFilter(self, obj, event):
                # 快捷栏：鼠标滚轮改为横向滑动
                if (
                    hasattr(self, "_quick_scroll")
                    and self._quick_scroll is not None
                    and obj is self._quick_scroll.viewport()
                    and event.type() == QtCore.QEvent.Wheel
                ):
                    bar = self._quick_scroll.horizontalScrollBar()
                    delta = event.angleDelta().y()
                    if delta == 0:
                        delta = event.angleDelta().x()
                    bar.setValue(bar.value() - delta)
                    return True

                if obj is self.input_edit and event.type() == QtCore.QEvent.KeyPress:
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
                return super().eventFilter(obj, event)

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
                self._persist_active_session(refresh_combo=False)
                self.sessions.reload_from_disk()
                self._load_active_session()
                if reload_only:
                    self.status_label.setText("已切换工程会话")

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
                        self, "切换会话", "请等待当前回复完成后再切换会话。"
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
                    self.status_label.setText("切换失败：会话不存在")
                    return
                except Exception:
                    self._refresh_session_combo()
                    self.status_label.setText("切换会话出错")
                    return
                finally:
                    self._session_switching = False

                if session is not None:
                    self.status_label.setText(f"已切换: {session.title}")

            def _on_new_session(self):
                if self._worker and self._worker.isRunning():
                    return
                self._cancel_pending_save()
                self._persist_active_session(refresh_combo=False)
                session = self.sessions.create_session("新对话", set_active=True)
                self._session_switching = True
                try:
                    self.agent.reset()
                    self._show_welcome()
                    self._refresh_session_combo(select_id=session.id)
                    self._select_session_in_combo(session.id)
                finally:
                    self._session_switching = False
                self.status_label.setText(f"新建会话: {session.title}")

            def _on_rename_session(self):
                sid = self.session_combo.currentData() or self.sessions.active().id
                session = self.sessions.project.get_session(sid)
                if not session:
                    return
                text, ok = QtWidgets.QInputDialog.getText(
                    self,
                    "重命名会话",
                    "会话名称:",
                    QtWidgets.QLineEdit.Normal,
                    session.title,
                )
                if ok and text.strip():
                    self.sessions.rename(sid, text.strip())
                    self._refresh_session_combo()

            def _on_delete_session(self):
                if len(self.sessions.project.sessions) <= 1:
                    QtWidgets.QMessageBox.information(
                        self, "删除会话", "至少需要保留一个会话。"
                    )
                    return
                sid = self.session_combo.currentData() or self.sessions.active().id
                title = self.session_combo.currentText()
                reply = QtWidgets.QMessageBox.question(
                    self,
                    "删除会话",
                    f"确定删除会话「{title}」？此操作不可恢复。",
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                )
                if reply != QtWidgets.QMessageBox.Yes:
                    return
                new_active = self.sessions.delete(sid)
                if new_active is None:
                    self.sessions.create_session("新对话", set_active=True)
                self._session_switching = True
                try:
                    self._load_active_session()
                finally:
                    self._session_switching = False
                self.status_label.setText("会话已删除")

            def _flush_stream(self):
                if self._thinking_buf:
                    piece = self._thinking_buf
                    self._thinking_buf = ""
                    self.chat.append_thinking(piece)
                if self._stream_buf:
                    piece = self._stream_buf
                    self._stream_buf = ""
                    self.chat.append_assistant_text(piece)

            def _on_settings_saved(self):
                get_config().reload()
                self.setStyleSheet(load_stylesheet_safe())
                self._apply_provider_from_config()

            def _use_tool_from_settings(self, name: str):
                self.input_edit.setPlainText(
                    f"请调用工具 {name}，根据当前场景自动填参。"
                )
                for i in range(self.tabs.count()):
                    if self.tabs.tabText(i) == "对话":
                        self.tabs.setCurrentIndex(i)
                        break
                self.input_edit.setFocus()

            def _apply_provider_from_config(self):
                cfg = get_config()
                pid = cfg.get("llm.active_provider", "deepseek")
                model = cfg.get(f"providers.{pid}.default_model", "")
                if pid:
                    self.agent.set_provider(pid, model or None)

            def _confirm_destructive(self, name: str, args: dict) -> bool:
                # 「允许本轮对话执行」后，本轮内后续危险工具不再弹窗
                if self._skip_confirm_this_turn:
                    return True

                args_text = json.dumps(args, ensure_ascii=False, indent=2)
                if len(args_text) > 600:
                    args_text = args_text[:600] + "\n…"

                box = QtWidgets.QMessageBox(self)
                box.setWindowTitle("确认操作")
                box.setIcon(QtWidgets.QMessageBox.Question)
                box.setText(f"工具「{name}」可能修改/删除场景内容。")
                box.setInformativeText(f"参数:\n{args_text}\n\n是否继续？")

                btn_once = box.addButton(
                    "允许本次执行", QtWidgets.QMessageBox.AcceptRole
                )
                btn_turn = box.addButton(
                    "允许本轮对话执行", QtWidgets.QMessageBox.ActionRole
                )
                btn_no = box.addButton("取消执行", QtWidgets.QMessageBox.RejectRole)
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
                self._cancel_pending_save()
                self.sessions.reset_active()
                self.agent.reset()
                self._show_welcome()
                self._persist_active_session(refresh_combo=True)
                self.status_label.set_idle("当前会话已清空")

            def _on_stop(self):
                self._stopped_by_user = True
                if self._worker and self._worker.isRunning():
                    self._worker.terminate()
                    self._worker.wait(1000)
                try:
                    self.agent.undo.cancel_open()
                except Exception:
                    pass
                try:
                    self.agent.memory.drop_incomplete_tool_round()
                except Exception:
                    pass
                self._flush_stream()
                self.chat.finish_assistant(
                    stop_notice=stop_notice_for_reason("user_cancel")
                )
                self._set_busy(False)
                self._skip_confirm_this_turn = False
                self.status_label.set_idle("已停止")
                self._schedule_persist()

            def _set_busy(self, busy: bool):
                self.send_btn.setEnabled(not busy)
                self.stop_btn.setEnabled(busy)
                self.input_edit.setReadOnly(busy)

            def _on_send(self):
                text = self.input_edit.toPlainText().strip()
                if not text:
                    return
                if self._worker and self._worker.isRunning():
                    return

                pid = get_config().get("llm.active_provider", "deepseek")
                model = (
                    get_config().get(f"providers.{pid}.default_model", "") or ""
                ).strip()
                if pid:
                    self.agent.set_provider(pid, model or None)

                self.chat.add_user(text)
                self.chat.begin_assistant()
                self._stream_buf = ""
                self._thinking_buf = ""
                self._skip_confirm_this_turn = False
                self._stopped_by_user = False
                self.input_edit.clear()
                self._set_busy(True)
                self.status_label.set_thinking()

                stream = bool(get_config().get("agent.stream", True))
                self._worker = _create_worker(QtCore, self.agent, text, stream)
                self._worker.signals.event.connect(self._on_event)
                self._worker.signals.finished.connect(self._on_finished)
                self._worker.signals.failed.connect(self._on_failed)
                self._worker.start()

            def _on_event(self, event: dict):
                et = event.get("type")
                show_tools = get_config().get("agent.show_tool_calls", True)
                show_thinking = get_config().get("agent.show_thinking", False)

                if et == "thinking" and show_thinking:
                    self._thinking_buf += event.get("content", "")
                    if not self._stream_timer.isActive():
                        self._stream_timer.start()

                elif et == "text":
                    if self._thinking_buf:
                        self._flush_stream()
                        self.chat.finish_thinking()
                    self._stream_buf += event.get("content", "")
                    if not self._stream_timer.isActive():
                        self._stream_timer.start()

                elif et == "tool_start":
                    self._flush_stream()
                    self.chat.finish_thinking()
                    if show_tools:
                        self.chat.tool_start(event.get("name", ""))
                        self.status_label.set_tool(event.get("name", ""))

                elif et == "tool_end":
                    self._flush_stream()
                    if show_tools:
                        self.chat.tool_end(
                            event.get("name", ""), event.get("result") or ""
                        )
                    if self._worker and self._worker.isRunning():
                        self.status_label.set_thinking()

                elif et == "error":
                    self._flush_stream()
                    self.chat.finish_thinking()
                    # Keep any partial reply, then tip + error bubble
                    if self.chat._current is not None:
                        self.chat.finish_assistant(
                            stop_notice=event.get("stop_notice")
                            or stop_notice_for_reason("llm_error")
                        )
                    self.chat.add_error(event.get("content", ""))

                elif et == "stopped":
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
                    self.status_label.set_idle("已停止")

                elif et == "done":
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

                elif et == "undo_ready":
                    if event.get("can_undo"):
                        tip = self.status_label.text()
                        if tip in ("就绪", "", "思考中", "思考中…"):
                            self.status_label.set_idle("就绪 · 可用 Ctrl+Z 撤销")

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
                    self.status_label.set_idle("就绪 · 可用 Ctrl+Z 撤销")
                else:
                    self.status_label.set_idle("就绪")
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
                self.status_label.set_error("出错")
                self._schedule_persist()

            def closeEvent(self, event):
                global _WINDOW_INSTANCE
                try:
                    self.persist_sessions()
                except Exception:
                    pass
                _WINDOW_INSTANCE = None
                super().closeEvent(event)

        return _MayaAgentWindow(parent)
