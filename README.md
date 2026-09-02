# Maya Agent

面向 **Autodesk Maya 游戏开发管线** 的 AI Agent 工具：自然语言驱动建模、UV、绑骨、动画、材质、灯光与导出，兼容国内外主流大模型 API。

## 特性

- **覆盖游戏工作流**：场景管理、多边形建模、UV、绑骨蒙皮、动画、材质、灯光、FBX/USD/OBJ/Alembic 导出、LOD、碰撞体、命名规范等
- **多模型兼容**：OpenAI / Azure / Anthropic Claude / Google Gemini，以及 DeepSeek、通义千问、智谱 GLM、Moonshot Kimi、豆包、百川、硅基流动、Ollama 本地与自定义 OpenAI 兼容接口
- **Maya 原生界面**：停靠式深色面板，对话 / 设置，符合桌面操作习惯（Enter 发送、Shift+Enter 换行、Undo 块、危险操作确认）
- **版本支持**：Maya 2020–2026（自动适配 PySide2 / PySide6）
- **安全执行**：工具在 Maya 主线程执行，修改可 Ctrl+Z 撤销

## 快速开始

### Windows 一键安装（推荐）

双击项目根目录的 **`install.bat`**。

也可在命令行指定版本：

```bat
install.bat 2025
install.bat all
```

卸载双击 **`uninstall.bat`**。

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

重启 Maya 后，菜单栏会出现 **Maya Agent**，工具架会有 **MayaAgent** 按钮。

### 3. 手动启动（可选）

在 Script Editor（Python）中：

```python
import sys
sys.path.insert(0, r"D:\桌面\MayaAgent")  # 改成你的项目路径
import maya_agent
maya_agent.launch()
```

### 4. 配置 API

打开面板 → **设置** → 选择服务商 → 填入 API Key（或设置对应环境变量，如 `DEEPSEEK_API_KEY`、`OPENAI_API_KEY`、`DASHSCOPE_API_KEY` 等）。

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
│   ├── ui/                      # Qt 界面（对话 / 设置 / 样式）
│   ├── plugin/                  # 菜单 / 工具架 / 场景钩子
│   └── utils/                   # 配置、日志、Maya 兼容
├── resources/prompts/           # 系统提示词
└── scripts/install.py           # 安装脚本
```

## 卸载

```bash
python scripts/install.py --uninstall
```

## 许可

MIT
