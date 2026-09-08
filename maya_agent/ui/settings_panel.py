"""Settings panel (API / Agent / UI) plus top-level tools / help factories."""

from __future__ import annotations

from typing import Callable, Optional

from maya_agent import __app_name__, __version__
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
    on_saved: Optional[Callable[[], None]] = None,
):
    """
    Build settings QWidget with sub-tabs (模型与 API / Agent / 界面).
    on_saved() — refresh main window after save.
    """
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
            self.save_hint = QtWidgets.QLabel("修改后点击保存才会写入本地配置")
            self.save_hint.setObjectName("settingsSectionHint")
            foot.addWidget(self.save_hint, 1)
            self.save_btn = QtWidgets.QPushButton("保存设置")
            self.save_btn.setObjectName("sendBtn")
            self.save_btn.setCursor(QtCore.Qt.PointingHandCursor)
            self.save_btn.setMinimumWidth(108)
            self.save_btn.setMinimumHeight(32)
            self.save_btn.setEnabled(False)
            self.save_btn.clicked.connect(self._save)
            foot.addWidget(self.save_btn, 0, QtCore.Qt.AlignRight)
            outer.addWidget(footer)

            self._baseline = None
            self._suppress_dirty = False
            self._wire_dirty_tracking()

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

        # ---- data -----------------------------------------------------------

        def _snapshot(self) -> tuple:
            """Serializable form state used for dirty comparison."""
            return (
                self.provider_combo.currentData(),
                self.model_combo.currentText().strip(),
                self.api_key_edit.text(),
                self.base_url_edit.text().strip(),
                round(float(self.temp_spin.value()), 4),
                int(self.max_tokens_spin.value()),
                bool(self.auto_undo.isChecked()),
                bool(self.confirm_destructive.isChecked()),
                bool(self.stream_check.isChecked()),
                bool(self.show_tools.isChecked()),
                int(self.max_rounds.value()),
                self.font_family.text().strip(),
                int(self.font_size.value()),
            )

        def _mark_clean(self) -> None:
            self._baseline = self._snapshot()
            self.save_btn.setEnabled(False)
            self.save_hint.setText("修改后点击保存才会写入本地配置")

        def _update_dirty(self, *_args) -> None:
            if self._suppress_dirty or self._baseline is None:
                return
            dirty = self._snapshot() != self._baseline
            self.save_btn.setEnabled(dirty)
            self.save_hint.setText(
                "有未保存的修改" if dirty else "修改后点击保存才会写入本地配置"
            )

        def _wire_dirty_tracking(self) -> None:
            self.provider_combo.currentIndexChanged.connect(self._update_dirty)
            self.model_combo.currentIndexChanged.connect(self._update_dirty)
            self.model_combo.editTextChanged.connect(self._update_dirty)
            self.api_key_edit.textChanged.connect(self._update_dirty)
            self.base_url_edit.textChanged.connect(self._update_dirty)
            self.temp_spin.valueChanged.connect(self._update_dirty)
            self.max_tokens_spin.valueChanged.connect(self._update_dirty)
            self.auto_undo.toggled.connect(self._update_dirty)
            self.confirm_destructive.toggled.connect(self._update_dirty)
            self.stream_check.toggled.connect(self._update_dirty)
            self.show_tools.toggled.connect(self._update_dirty)
            self.max_rounds.valueChanged.connect(self._update_dirty)
            self.font_family.textChanged.connect(self._update_dirty)
            self.font_size.valueChanged.connect(self._update_dirty)

        def _on_provider_changed(self) -> None:
            pid = self.provider_combo.currentData()
            pconf = self.cfg.get(f"providers.{pid}", {}) or {}
            self.model_combo.clear()
            for m in pconf.get("models") or []:
                self.model_combo.addItem(m)
            self.model_combo.setCurrentText(pconf.get("default_model", ""))
            self.base_url_edit.setText(pconf.get("base_url", ""))
            self.api_key_edit.setText(self.cfg.get_api_key(pid))
            self._update_dirty()

        def _load(self) -> None:
            self._suppress_dirty = True
            try:
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
                self.show_tools.setChecked(
                    bool(self.cfg.get("agent.show_tool_calls", True))
                )
                self.max_rounds.setValue(int(self.cfg.get("maya.max_tool_rounds", 12)))
                self.font_family.setText(
                    self.cfg.get("ui.font_family", "Microsoft YaHei UI")
                )
                self.font_size.setValue(int(self.cfg.get("ui.font_size", 13)))
            finally:
                self._suppress_dirty = False
            self._mark_clean()

        def reload_from_config(self) -> None:
            self.cfg.reload()
            self._load()

        def _save(self) -> None:
            if not self.save_btn.isEnabled():
                return
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
            self._mark_clean()
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
                parent_item = QtWidgets.QTreeWidgetItem([cat])
                parent_item.setFlags(QtCore.Qt.ItemIsEnabled)
                font = parent_item.font(0)
                font.setBold(True)
                parent_item.setFont(0, font)
                parent_item.setForeground(0, QtGui.QColor("#b8c4d4"))
                for t in sorted(cats[cat], key=lambda x: x.name):
                    child = QtWidgets.QTreeWidgetItem([t.name])
                    child.setToolTip(0, t.description)
                    child.setData(0, QtCore.Qt.UserRole, t.name)
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

    blurb = QtWidgets.QLabel(
        "面向游戏开发的 Maya AI 助手。用自然语言驱动建模、UV、绑骨、动画、"
        "材质、灯光与导出；支持国内外主流大模型，兼容 Maya 2020–2026"
        "（PySide2 / PySide6）。"
    )
    blurb.setObjectName("settingsHelpBody")
    blurb.setWordWrap(True)
    intro_lay.addWidget(blurb)
    root.addWidget(intro)

    quick, quick_lay = _section("快速上手", "首次使用按以下步骤即可开始。")
    _add_help_lines(
        quick_lay,
        (
            "打开菜单「Maya Agent → 打开面板」，或点击工具架 Agent 按钮",
            "在「设置 → 模型与 API」选择服务商、填写 API Key，点「测试连接」通过后「保存设置」",
            "切回「对话」，用自然语言描述任务；也可点底部快捷芯片快速试用",
            "Agent 会自动调用工具改场景；危险操作会先确认，可用「撤销」或 Ctrl+Z 回退",
        ),
        numbered=True,
    )
    root.addWidget(quick)

    chat, chat_lay = _section(
        "对话界面",
        "主工作区：会话、输入、快捷操作与结果反馈。",
    )
    _add_help_lines(
        chat_lay,
        (
            "会话：新建 / 重命名 / 删除 / 下拉切换；同一场景可保留多组对话",
            "会话会随场景自动保存（sidecar：场景名.ma.mayaagent.json）；未命名场景先暂存本地，保存场景后迁移",
            "Enter 发送，Shift+Enter 换行；「停止」可中断进行中的任务",
            "「清空」只清空当前会话聊天与记忆，不会清空 Maya 场景",
            "「撤销」回退上一轮 Agent 对场景的修改（开启「自动 Undo 块」时一轮合并为一次撤销）",
            "快捷芯片：场景信息、网格统计、导出 FBX、三点光（栏过窄时可横向滚动）",
            "意图不清时，助手会给出可点击选项按钮，点选即自动回复",
            "开启「显示工具调用详情」后，对话中会展示工具名与结果摘要",
        ),
    )
    root.addWidget(chat)

    settings, settings_lay = _section(
        "设置面板",
        "模型、Agent 行为与界面均可在此配置，修改后需点「保存设置」。",
    )
    _add_help_lines(
        settings_lay,
        (
            "模型与 API：服务商、模型、API Key、Base URL、Temperature、Max Tokens；支持测试连接",
            "服务商包括 OpenAI、Azure、Anthropic、Gemini、DeepSeek、通义、智谱、Kimi、豆包、百川、SiliconFlow、Ollama、自定义 OpenAI 兼容接口等",
            "Agent：自动 Undo 块、危险操作前确认、流式输出、显示工具调用、最大工具轮次（1–30）",
            "界面：字体与字号（部分控件需重新打开面板后完全生效）",
        ),
    )
    root.addWidget(settings)

    tools, tools_lay = _section(
        "内置工具一览",
        "约 60 个工具，按领域分类。用自然语言描述即可，也可在顶栏「工具」页签中双击试用。",
    )
    tool_groups = (
        (
            "场景 scene",
            "get_scene_info、list_selection、select_objects、rename_object、batch_rename、"
            "create_group、delete_objects、parent_objects、duplicate_objects、clean_scene、set_frame_range",
        ),
        (
            "建模 modeling",
            "create_primitive、combine_meshes、separate_meshes、boolean_meshes、extrude_faces、"
            "bevel_edges、smooth_mesh、reduce_mesh、mirror_geometry、center_pivot、freeze_transform、get_mesh_stats",
        ),
        (
            "UV",
            "auto_unwrap_uv、layout_uv、check_uv_overlaps",
        ),
        (
            "绑骨 rigging",
            "create_joint、create_joint_chain、orient_joints、bind_skin、unbind_skin、"
            "create_ik_handle、create_control_curve、constrain_objects",
        ),
        (
            "动画 animation",
            "set_keyframe、delete_keyframes、bake_animation、playblast、copy_animation",
        ),
        (
            "材质 materials",
            "create_material、assign_material、assign_texture、list_materials",
        ),
        (
            "灯光 lighting",
            "create_light、create_three_point_lighting",
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
            "脚本 scripting",
            "execute_python、execute_mel、generate_python_snippet",
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
