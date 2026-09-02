"""Embedded settings panel (API / Agent / UI / tools / help)."""

from __future__ import annotations

from typing import Callable, Optional

from maya_agent import __app_name__
from maya_agent.llm.registry import create_provider, list_providers
from maya_agent.tools.registry import ensure_tools_loaded, get_tool, tools_by_category
from maya_agent.utils.config import get_config
from maya_agent.utils.maya_compat import import_qt


def help_html() -> str:
    family = get_config().get("ui.font_family", "Microsoft YaHei UI")
    return f"""
    <div style="color:#e8e8ea;font-family:'{family}';padding:8px;">
    <h3 style="color:#f0f0f2;">{__app_name__}</h3>
    <p>面向游戏开发的 Maya AI 助手。支持国内外主流大模型，覆盖建模、UV、绑骨、
    动画、材质、灯光、导出等管线操作。</p>
    <ul>
      <li>在「设置 → 模型与 API」中配置 API Key 与模型</li>
      <li>用自然语言描述任务，Agent 会自动调用工具</li>
      <li><b>Enter</b> 发送，<b>Shift+Enter</b> 换行；危险操作会弹窗确认</li>
      <li>支持<b>多组会话</b>，随 Maya 场景自动保存（sidecar 文件）</li>
      <li>Agent 修改合并为一次 Undo，可用面板「撤销」或 Maya <b>Ctrl+Z</b> 回退</li>
      <li>支持 Maya 2020–2026（PySide2 / PySide6）</li>
    </ul>
    </div>
    """


def create_settings_panel(
    parent=None,
    *,
    on_saved: Optional[Callable[[], None]] = None,
    on_tool_use: Optional[Callable[[str], None]] = None,
):
    """
    Build settings QWidget with sub-tabs.
    on_tool_use(name) — e.g. insert prompt and switch to chat tab.
    on_saved() — refresh main window after save.
    """
    QtCore, QtGui, QtWidgets, _ = import_qt()

    class SettingsPanel(QtWidgets.QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setObjectName("settingsPanel")
            self.cfg = get_config()
            self._on_saved = on_saved
            self._on_tool_use = on_tool_use
            self._build()
            self._load()

        def _build(self) -> None:
            outer = QtWidgets.QVBoxLayout(self)
            outer.setContentsMargins(0, 8, 0, 0)
            outer.setSpacing(8)

            self.tabs = QtWidgets.QTabWidget()
            self.tabs.setObjectName("settingsTabs")
            outer.addWidget(self.tabs, 1)

            self._build_api_tab()
            self._build_agent_tab()
            self._build_ui_tab()
            self._build_tools_tab()
            self._build_help_tab()

            footer = QtWidgets.QHBoxLayout()
            footer.addStretch(1)
            save_btn = QtWidgets.QPushButton("保存设置")
            save_btn.setObjectName("sendBtn")
            save_btn.setFixedWidth(96)
            save_btn.clicked.connect(self._save)
            footer.addWidget(save_btn)
            outer.addLayout(footer)

        def _build_api_tab(self) -> None:
            page = QtWidgets.QWidget()
            form = QtWidgets.QFormLayout(page)
            form.setContentsMargins(8, 12, 8, 8)
            form.setSpacing(10)

            self.provider_combo = QtWidgets.QComboBox()
            self.model_combo = QtWidgets.QComboBox()
            self.model_combo.setEditable(True)
            self.api_key_edit = QtWidgets.QLineEdit()
            self.api_key_edit.setEchoMode(QtWidgets.QLineEdit.Password)
            self.base_url_edit = QtWidgets.QLineEdit()
            self.temp_spin = QtWidgets.QDoubleSpinBox()
            self.temp_spin.setRange(0, 2)
            self.temp_spin.setSingleStep(0.1)
            self.max_tokens_spin = QtWidgets.QSpinBox()
            self.max_tokens_spin.setRange(256, 128000)
            self.max_tokens_spin.setSingleStep(256)

            for p in list_providers():
                self.provider_combo.addItem(p["label"], p["id"])
            self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)

            form.addRow("当前服务商", self.provider_combo)
            form.addRow("模型", self.model_combo)
            form.addRow("API Key", self.api_key_edit)
            form.addRow("Base URL", self.base_url_edit)
            form.addRow("Temperature", self.temp_spin)
            form.addRow("Max Tokens", self.max_tokens_spin)

            test_btn = QtWidgets.QPushButton("测试连接")
            test_btn.setObjectName("secondaryBtn")
            test_btn.clicked.connect(self._test_connection)
            form.addRow("", test_btn)
            self.tabs.addTab(page, "模型与 API")

        def _build_agent_tab(self) -> None:
            page = QtWidgets.QWidget()
            form = QtWidgets.QFormLayout(page)
            form.setContentsMargins(8, 12, 8, 8)
            form.setSpacing(10)

            self.auto_undo = QtWidgets.QCheckBox("自动 Undo 块")
            self.confirm_destructive = QtWidgets.QCheckBox("危险操作前确认")
            self.stream_check = QtWidgets.QCheckBox("流式输出")
            self.show_tools = QtWidgets.QCheckBox("显示工具调用详情")
            self.max_rounds = QtWidgets.QSpinBox()
            self.max_rounds.setRange(1, 30)

            form.addRow(self.auto_undo)
            form.addRow(self.confirm_destructive)
            form.addRow(self.stream_check)
            form.addRow(self.show_tools)
            form.addRow("最大工具轮次", self.max_rounds)
            self.tabs.addTab(page, "Agent")

        def _build_ui_tab(self) -> None:
            page = QtWidgets.QWidget()
            form = QtWidgets.QFormLayout(page)
            form.setContentsMargins(8, 12, 8, 8)
            form.setSpacing(10)

            self.font_family = QtWidgets.QLineEdit()
            self.font_size = QtWidgets.QSpinBox()
            self.font_size.setRange(10, 20)
            form.addRow("字体", self.font_family)
            form.addRow("字号", self.font_size)
            self.tabs.addTab(page, "界面")

        def _build_tools_tab(self) -> None:
            page = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout(page)
            layout.setContentsMargins(8, 8, 8, 8)
            layout.setSpacing(8)

            tip = QtWidgets.QLabel("双击工具名可插入对话输入框")
            tip.setObjectName("hintLabel")
            layout.addWidget(tip)

            ensure_tools_loaded()
            self.tool_list = QtWidgets.QListWidget()
            cats = tools_by_category()
            for cat in sorted(cats.keys()):
                header = QtWidgets.QListWidgetItem(f"▸ {cat}")
                header.setFlags(QtCore.Qt.NoItemFlags)
                self.tool_list.addItem(header)
                for t in sorted(cats[cat], key=lambda x: x.name):
                    item = QtWidgets.QListWidgetItem(f"    {t.name}")
                    item.setToolTip(t.description)
                    item.setData(QtCore.Qt.UserRole, t.name)
                    self.tool_list.addItem(item)

            self.tool_list.itemDoubleClicked.connect(self._on_tool_double_click)
            self.tool_list.currentItemChanged.connect(self._on_tool_select)
            layout.addWidget(self.tool_list, 1)

            self.tool_desc = QtWidgets.QTextEdit()
            self.tool_desc.setReadOnly(True)
            self.tool_desc.setFixedHeight(120)
            self.tool_desc.setPlaceholderText("选择工具查看说明…")
            layout.addWidget(self.tool_desc)
            self.tabs.addTab(page, "工具")

        def _build_help_tab(self) -> None:
            page = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout(page)
            layout.setContentsMargins(8, 8, 8, 8)
            browser = QtWidgets.QTextBrowser()
            browser.setOpenExternalLinks(True)
            browser.setHtml(help_html())
            layout.addWidget(browser)
            self.tabs.addTab(page, "帮助")

        def _on_provider_changed(self) -> None:
            pid = self.provider_combo.currentData()
            pconf = self.cfg.get(f"providers.{pid}", {}) or {}
            self.model_combo.clear()
            for m in pconf.get("models") or []:
                self.model_combo.addItem(m)
            self.model_combo.setCurrentText(pconf.get("default_model", ""))
            self.base_url_edit.setText(pconf.get("base_url", ""))
            self.api_key_edit.setText(self.cfg.get_api_key(pid))

        def _load(self) -> None:
            active = self.cfg.get("llm.active_provider", "deepseek")
            idx = self.provider_combo.findData(active)
            if idx >= 0:
                self.provider_combo.setCurrentIndex(idx)
            self._on_provider_changed()
            self.temp_spin.setValue(float(self.cfg.get("llm.temperature", 0.3)))
            self.max_tokens_spin.setValue(int(self.cfg.get("llm.max_tokens", 4096)))
            self.auto_undo.setChecked(bool(self.cfg.get("maya.auto_undo", True)))
            self.confirm_destructive.setChecked(
                bool(self.cfg.get("maya.confirm_destructive", True))
            )
            self.stream_check.setChecked(bool(self.cfg.get("agent.stream", True)))
            self.show_tools.setChecked(bool(self.cfg.get("agent.show_tool_calls", True)))
            self.max_rounds.setValue(int(self.cfg.get("maya.max_tool_rounds", 12)))
            self.font_family.setText(
                self.cfg.get("ui.font_family", "Microsoft YaHei UI")
            )
            self.font_size.setValue(int(self.cfg.get("ui.font_size", 13)))

        def reload_from_config(self) -> None:
            self.cfg.reload()
            self._load()

        def _save(self) -> None:
            pid = self.provider_combo.currentData()
            model = self.model_combo.currentText().strip()
            self.cfg.set("llm.active_provider", pid)
            self.cfg.set("llm.temperature", self.temp_spin.value())
            self.cfg.set("llm.max_tokens", self.max_tokens_spin.value())
            self.cfg.set(f"providers.{pid}.default_model", model)
            self.cfg.set(
                f"providers.{pid}.base_url", self.base_url_edit.text().strip()
            )
            self.cfg.set_api_key(pid, self.api_key_edit.text().strip())
            self.cfg.set("maya.auto_undo", self.auto_undo.isChecked())
            self.cfg.set(
                "maya.confirm_destructive", self.confirm_destructive.isChecked()
            )
            self.cfg.set("agent.stream", self.stream_check.isChecked())
            self.cfg.set("agent.show_tool_calls", self.show_tools.isChecked())
            self.cfg.set("maya.max_tool_rounds", self.max_rounds.value())
            self.cfg.set("ui.font_family", self.font_family.text().strip())
            self.cfg.set("ui.font_size", self.font_size.value())
            self.cfg.save_user()
            if self._on_saved:
                self._on_saved()
            QtWidgets.QMessageBox.information(self, "已保存", "设置已保存并生效。")

        def _test_connection(self) -> None:
            pid = self.provider_combo.currentData()
            model = self.model_combo.currentText().strip()
            key = self.api_key_edit.text().strip()
            base = self.base_url_edit.text().strip()
            try:
                provider = create_provider(
                    pid, model=model, api_key=key or None, base_url=base or None
                )
                result = provider.test_connection()
                if result.get("ok"):
                    QtWidgets.QMessageBox.information(
                        self, "成功", f"连接正常\n{result.get('preview', '')}"
                    )
                else:
                    QtWidgets.QMessageBox.warning(
                        self, "失败", result.get("error", "未知错误")
                    )
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "错误", str(e))

        def _on_tool_select(self, current, _previous) -> None:
            if not current:
                return
            name = current.data(QtCore.Qt.UserRole)
            if not name:
                self.tool_desc.setPlainText("")
                return
            t = get_tool(name)
            if t:
                import json

                self.tool_desc.setPlainText(
                    f"{t.name}\n类别: {t.category}\n\n{t.description}\n\n"
                    f"参数:\n{json.dumps(t.parameters, ensure_ascii=False, indent=2)}"
                )

        def _on_tool_double_click(self, item) -> None:
            name = item.data(QtCore.Qt.UserRole)
            if name and self._on_tool_use:
                self._on_tool_use(name)

        def show_subtab(self, name: str) -> None:
            """Switch to a sub-tab by label, e.g. '工具' or '模型与 API'."""
            for i in range(self.tabs.count()):
                if self.tabs.tabText(i) == name:
                    self.tabs.setCurrentIndex(i)
                    return

    return SettingsPanel(parent)
