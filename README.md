# Maya Agent

**v1.1.2** — 面向 **Autodesk Maya 游戏开发管线** 的 AI Agent：用自然语言驱动建模、UV、绑骨、动画、材质、灯光与导出，兼容国内外主流大模型 API。

## 特性

- **覆盖游戏工作流**：约 60 个工具，涵盖场景、多边形建模、UV、绑骨蒙皮、动画、材质、灯光、FBX/USD/OBJ/Alembic 导出、LOD、碰撞体、命名规范与脚本执行等
- **多模型兼容**：默认 DeepSeek；另支持 OpenAI / Azure / Anthropic Claude / Google Gemini，以及通义千问、智谱 GLM、Moonshot Kimi、豆包、百川、硅基流动、Ollama 本地与自定义 OpenAI 兼容接口
- **Maya 原生界面**：停靠式深色面板，顶栏 **对话 / 设置 / 工具 / 帮助**；Enter 发送、Shift+Enter 换行、自动 Undo 块、危险操作确认
- **会话与场景联动**：多会话管理；对话随场景 sidecar 自动保存（`场景名.ma.mayaagent.json`）
- **版本支持**：Maya 2020–2026（自动适配 PySide2 / PySide6）
- **安全执行**：工具在 Maya 主线程执行；默认不在当前场景外新建空场景；修改可 Ctrl+Z 回退

## 快速开始

### Windows 一键安装（推荐）

双击项目根目录的 **`install.bat`**。

也可在命令行指定版本：

```bat
install.bat 2025
install.bat all
```

卸载双击 **`uninstall.bat`**。

安装会写入模块路径、自动加载插件（`Documents/maya/plug-ins/MayaAgent.py`）与菜单 / 工具架入口。完成后**重启 Maya**，菜单栏会出现 **Maya Agent**，工具架会有 Agent 按钮。

### 1. 安装依赖

用对应 Maya 版本的 `mayapy`（推荐）安装：

```bash
mayapy -m pip install -r requirements.txt
```

Windows 示例（按本机路径调整）：

```bash
"C:\Program Files\Autodesk\Maya2024\bin\mayapy.exe" -m pip install -r requirements.txt
```

### 2. 安装到 Maya

```bash
python scripts/install.py
# 或指定版本
python scripts/install.py --maya-version 2024
```

### 3. 手动启动 / 重载（可选）

在 Script Editor（Python）中：

```python
import maya_agent
maya_agent.launch()   # 打开面板
maya_agent.reload()   # 修改代码后热重载菜单与面板
```

若尚未安装到 Maya 路径，需先把项目根目录加入 `sys.path`：

```python
import sys
sys.path.insert(0, r"D:\path\to\MayaAgent")  # 改成你的项目路径
import maya_agent
maya_agent.launch()
```

也可通过菜单 **Maya Agent → 重新加载** 刷新插件。

### 4. 配置 API

打开面板 → **设置 → 模型与 API** → 选择服务商、填写 API Key，建议先点「测试连接」，再「保存设置」。

也可通过环境变量配置（如 `DEEPSEEK_API_KEY`、`OPENAI_API_KEY`、`DASHSCOPE_API_KEY` 等）。

## 界面一览

| 顶栏页签 | 说明 |
| -------- | ---- |
| **对话** | 主工作区：会话、输入、快捷芯片、流式回复与工具结果 |
| **设置** | 子页：模型与 API / Agent 行为 / 界面字体字号 |
| **工具** | 按类别浏览全部工具；双击工具名可插入对话输入框 |
| **帮助** | 快速上手、功能说明与内置工具一览 |

## 使用示例

- 「创建一个立方体，命名为 `SM_Crate`，冻结变换并居中枢轴」
- 「查看当前场景信息」
- 「给选中网格绑定到选中骨骼，最大影响数 4」
- 「自动展开 UV 并 Layout」
- 「把当前选择导出 FBX 到桌面」
- 「创建三点布光」

## 项目结构

```
MayaAgent/
├── config/default_config.yaml   # 默认配置与模型列表
├── maya_agent/
│   ├── core/                    # Agent 循环、内存、执行器、Undo、会话
│   ├── llm/                     # 多厂商 LLM 适配
│   ├── tools/                   # Maya 工具集（_maya 公共访问层）
│   ├── ui/                      # Qt 界面（对话 / 设置 / 工具 / 帮助）
│   ├── plugin/                  # 菜单 / 工具架 / 场景钩子
│   └── utils/                   # 配置、日志、Maya 兼容
├── resources/
│   ├── prompts/                 # 系统提示词
│   └── maya_plugin/             # 自动加载插件模板
├── scripts/install.py           # 安装 / 卸载脚本
├── install.bat / uninstall.bat  # Windows 一键入口
└── requirements.txt
```

## 卸载

```bash
python scripts/install.py --uninstall
```

或双击 **`uninstall.bat`**。会清理模块、插件自动加载、工具架按钮与项目 junction。

## 许可

MIT
