"""Embedded settings panel (API / Agent / UI / tools / help)."""

from __future__ import annotations

from typing import Callable, Optional

from maya_agent import __app_name__, __version__
from maya_agent.llm.registry import create_provider, list_providers
from maya_agent.tools.registry import ensure_tools_loaded, get_tool, tools_by_category
from maya_agent.ui.combo_widgets import create_toolbar_combo
from maya_agent.ui.spin_widgets import create_toolbar_spin
from maya_agent.ui.palette import (
    COLOR_ACCENT,
    COLOR_BORDER,
    COLOR_MUTED,
    COLOR_PANEL,
    COLOR_TEXT,
)
from maya_agent.utils.config import get_config
from maya_agent.utils.maya_compat import import_qt


def help_html() -> str:
    family = get_config().get("ui.font_family", "Microsoft YaHei UI")
    return f"""
    <div style="color:{COLOR_TEXT};font-family:'{family}';font-size:13px;line-height:1.55;padding:4px 2px;">
      <div style="margin-bottom:18px;">
        <div style="font-size:18px;font-weight:600;color:#f0f0f2;letter-spacing:0.2px;">
          {__app_name__}
          <span style="font-size:12px;font-weight:500;color:{COLOR_MUTED};margin-left:8px;">v{__version__}</span>
        </div>
        <p style="margin:8px 0 0 0;color:#c4c4cc;">
          面向游戏开发的 Maya AI 助手。支持国内外主流大模型，覆盖建模、UV、绑骨、
          动画、材质、灯光、导出等管线操作。
        </p>
      </div>

      <div style="margin-bottom:14px;padding:12px 14px;background:{COLOR_PANEL};border:1px solid {COLOR_BORDER};border-radius:8px;">
        <div style="font-size:12px;font-weight:600;color:{COLOR_ACCENT};margin-bottom:8px;">快速上手</div>
        <div style="color:#d0d0d6;">
          1. 在「模型与 API」填写 Key 与模型<br/>
          2. 回到「对话」，用自然语言描述任务<br/>
          3. Agent 自动调用工具并回报结果
        </div>
      </div>

      <div style="margin-bottom:14px;padding:12px 14px;background:{COLOR_PANEL};border:1px solid {COLOR_BORDER};border-radius:8px;">
        <div style="font-size:12px;font-weight:600;color:{COLOR_ACCENT};margin-bottom:8px;">操作提示</div>
        <ul style="margin:0;padding-left:18px;color:#d0d0d6;">
          <li style="margin-bottom:6px;"><b>Enter</b> 发送，<b>Shift+Enter</b> 换行</li>
          <li style="margin-bottom:6px;">支持多组会话，随 Maya 场景自动保存（sidecar）</li>
          <li style="margin-bottom:6px;">意图不清时会给出可点击选项，点选即回复</li>
          <li style="margin-bottom:6px;">危险操作会先确认；可用「撤销」或 <b>Ctrl+Z</b></li>
          <li>兼容 Maya 2020–2026（PySide2 / PySide6）</li>
        </ul>
      </div>
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
            self._build_tools_tab()
            self._build_help_tab()

            footer = QtWidgets.QFrame()
            footer.setObjectName("settingsFooter")
            foot = QtWidgets.QHBoxLayout(footer)
            foot.setContentsMargins(0, 2, 0, 0)
            foot.setSpacing(10)
            self.save_hint = QtWidgets.QLabel("修改后点击保存才会写入本地配置")
            self.save_hint.setObjectName("settingsSectionHint")
            foot.addWidget(self.save_hint, 1)
            save_btn = QtWidgets.QPushButton("保存设置")
            save_btn.setObjectName("sendBtn")
            save_btn.setCursor(QtCore.Qt.PointingHandCursor)
            save_btn.setMinimumWidth(108)
            save_btn.setMinimumHeight(32)
            save_btn.clicked.connect(self._save)
            foot.addWidget(save_btn, 0, QtCore.Qt.AlignRight)
            outer.addWidget(footer)

        def _build_api_tab(self) -> None:
            scroll, root = self._scroll_page()

            conn, conn_lay = self._section(
                "连接",
                "选择服务商并填写 API Key。Base URL 一般无需修改。",
            )
            form = self._form(conn_lay)

            self.provider_combo = create_toolbar_combo()
            self.provider_combo.setMinimumHeight(30)
            self.model_combo = create_toolbar_combo(editable=True)
            self.model_combo.setMinimumHeight(30)
            self.api_key_edit = QtWidgets.QLineEdit()
            self.api_key_edit.setEchoMode(QtWidgets.QLineEdit.Password)
            self.api_key_edit.setPlaceholderText("sk-… 或对应厂商的密钥")
            self.api_key_edit.setMinimumHeight(30)
            self.base_url_edit = QtWidgets.QLineEdit()
            self.base_url_edit.setMinimumHeight(30)
            self.base_url_edit.setPlaceholderText("https://api.example.com/v1")

            for p in list_providers():
                self.provider_combo.addItem(p["label"], p["id"])
            self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)

            form.addRow(self._field_label("服务商"), self.provider_combo)
            form.addRow(self._field_label("模型"), self.model_combo)
            form.addRow(self._field_label("API Key"), self.api_key_edit)
            form.addRow(self._field_label("Base URL"), self.base_url_edit)

            actions = QtWidgets.QHBoxLayout()
            actions.setContentsMargins(0, 4, 0, 0)
            actions.addStretch(1)
            test_btn = QtWidgets.QPushButton("测试连接")
            test_btn.setObjectName("secondaryBtn")
            test_btn.setCursor(QtCore.Qt.PointingHandCursor)
            test_btn.setMinimumWidth(96)
            test_btn.setMinimumHeight(30)
            test_btn.clicked.connect(self._test_connection)
            actions.addWidget(test_btn)
            conn_lay.addLayout(actions)
            root.addWidget(conn)

            gen, gen_lay = self._section(
                "生成参数",
                "影响回复风格与长度。Agent 任务建议 Temperature 偏低。",
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
            gform.addRow(self._field_label("Temperature"), self.temp_spin)
            gform.addRow(self._field_label("Max Tokens"), self.max_tokens_spin)
            root.addWidget(gen)

            self._stretch_end(root)
            self.tabs.addTab(scroll, "模型与 API")

        def _build_agent_tab(self) -> None:
            scroll, root = self._scroll_page()

            beh, beh_lay = self._section(
                "行为",
                "控制 Agent 执行方式与界面反馈。",
            )
            self.auto_undo = QtWidgets.QCheckBox("自动 Undo 块")
            self.confirm_destructive = QtWidgets.QCheckBox("危险操作前确认")
            self.stream_check = QtWidgets.QCheckBox("流式输出")
            self.show_tools = QtWidgets.QCheckBox("显示工具调用详情")

            beh_lay.addWidget(
                self._option_row(
                    self.auto_undo, "将一轮对话中的场景修改合并，便于一次撤销"
                )
            )
            beh_lay.addWidget(
                self._option_row(
                    self.confirm_destructive, "删除、清空等操作前弹出确认对话框"
                )
            )
            beh_lay.addWidget(
                self._option_row(self.stream_check, "边生成边显示回复，响应更快")
            )
            beh_lay.addWidget(
                self._option_row(
                    self.show_tools, "在对话中展示工具名称与执行结果摘要"
                )
            )
            root.addWidget(beh)

            lim, lim_lay = self._section(
                "限制",
                "防止单次任务调用工具过多导致卡顿。",
            )
            lform = self._form(lim_lay)
            self.max_rounds = create_toolbar_spin()
            self.max_rounds.setRange(1, 30)
            self.max_rounds.setFixedHeight(30)
            self.max_rounds.setFixedWidth(100)
            lform.addRow(self._field_label("最大工具轮次"), self.max_rounds)
            root.addWidget(lim)

            self._stretch_end(root)
            self.tabs.addTab(scroll, "Agent")

        def _build_ui_tab(self) -> None:
            scroll, root = self._scroll_page()

            typo, typo_lay = self._section(
                "字体",
                "影响面板内文字显示。部分控件需重新打开窗口后完全生效。",
            )
            form = self._form(typo_lay)
            self.font_family = QtWidgets.QLineEdit()
            self.font_family.setMinimumHeight(30)
            self.font_family.setPlaceholderText("例如 Microsoft YaHei UI")
            self.font_size = create_toolbar_spin()
            self.font_size.setRange(10, 20)
            self.font_size.setFixedHeight(30)
            self.font_size.setFixedWidth(100)
            form.addRow(self._field_label("字体"), self.font_family)
            form.addRow(self._field_label("字号"), self.font_size)
            root.addWidget(typo)

            self._stretch_end(root)
            self.tabs.addTab(scroll, "界面")

        def _build_tools_tab(self) -> None:
            page = QtWidgets.QWidget()
            page.setObjectName("settingsPage")
            layout = QtWidgets.QVBoxLayout(page)
            layout.setContentsMargins(14, 14, 14, 14)
            layout.setSpacing(10)

            head = QtWidgets.QFrame()
            head.setObjectName("settingsSection")
            head_lay = QtWidgets.QVBoxLayout(head)
            head_lay.setContentsMargins(14, 12, 14, 12)
            head_lay.setSpacing(3)
            title = QtWidgets.QLabel("工具浏览")
            title.setObjectName("settingsSectionTitle")
            tip = QtWidgets.QLabel("双击工具名可插入对话输入框，便于快速试用。")
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
                parent = QtWidgets.QTreeWidgetItem([cat])
                parent.setFlags(QtCore.Qt.ItemIsEnabled)
                font = parent.font(0)
                font.setBold(True)
                parent.setFont(0, font)
                parent.setForeground(0, QtGui.QColor("#b8c4d4"))
                for t in sorted(cats[cat], key=lambda x: x.name):
                    child = QtWidgets.QTreeWidgetItem([t.name])
                    child.setToolTip(0, t.description)
                    child.setData(0, QtCore.Qt.UserRole, t.name)
                    child.setForeground(0, QtGui.QColor(COLOR_TEXT))
                    parent.addChild(child)
                self.tool_tree.addTopLevelItem(parent)
                parent.setExpanded(True)

            self.tool_tree.itemDoubleClicked.connect(self._on_tool_double_click)
            self.tool_tree.currentItemChanged.connect(self._on_tool_select)
            layout.addWidget(self.tool_tree, 1)

            self.tool_desc = QtWidgets.QTextEdit()
            self.tool_desc.setObjectName("settingsToolDesc")
            self.tool_desc.setReadOnly(True)
            self.tool_desc.setFixedHeight(128)
            self.tool_desc.setPlaceholderText("选择工具查看说明与参数…")
            layout.addWidget(self.tool_desc)

            # keep old attribute name for any external refs
            self.tool_list = self.tool_tree
            self.tabs.addTab(page, "工具")

        def _build_help_tab(self) -> None:
            page = QtWidgets.QWidget()
            page.setObjectName("settingsPage")
            layout = QtWidgets.QVBoxLayout(page)
            layout.setContentsMargins(14, 14, 14, 14)
            browser = QtWidgets.QTextBrowser()
            browser.setObjectName("settingsHelpBrowser")
            browser.setOpenExternalLinks(True)
            browser.setHtml(help_html())
            layout.addWidget(browser)
            self.tabs.addTab(page, "帮助")

        # ---- data -----------------------------------------------------------

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
            name = current.data(0, QtCore.Qt.UserRole)
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

        def _on_tool_double_click(self, item, _column) -> None:
            name = item.data(0, QtCore.Qt.UserRole)
            if name and self._on_tool_use:
                self._on_tool_use(name)

        def show_subtab(self, name: str) -> None:
            """Switch to a sub-tab by label, e.g. '工具' or '模型与 API'."""
            for i in range(self.tabs.count()):
                if self.tabs.tabText(i) == name:
                    self.tabs.setCurrentIndex(i)
                    return

    return SettingsPanel(parent)
