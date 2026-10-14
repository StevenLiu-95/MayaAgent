"""Tools browser panel."""

from __future__ import annotations

from typing import Callable, Optional

from maya_agent.i18n import init_from_config, t
from maya_agent.tools.registry import ensure_tools_loaded, get_tool, tools_by_category
from maya_agent.ui.qt_bind import QtCore, QtGui, QtWidgets

class ToolsPanel(QtWidgets.QWidget):
    def __init__(
        self, parent=None, *, on_tool_use: Optional[Callable[[str], None]] = None
    ):
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


def create_tools_panel(parent=None, *, on_tool_use=None):
    init_from_config()
    return ToolsPanel(parent, on_tool_use=on_tool_use)
