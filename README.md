# Maya Agent

**v1.3.1** — 面向 **Autodesk Maya 游戏开发管线** 的 AI Agent：用自然语言驱动建模、UV、绑骨、动画、材质、灯光与导出，兼容国内外主流大模型（含视觉模型）。

## 核心能力

| 能力 | 说明 |
| ---- | ---- |
| **工具调用 Agent** | 约 **100+** 个 Maya 工具；LLM 规划 → 主线程执行 → 流式回写；单轮可多步工具（默认最多 12 轮，设置里可调至 50） |
| **游戏工作流覆盖** | 场景 / 建模 / UV / 绑骨蒙皮 / 动画 / 材质 / 灯光 / 导出（FBX 等）/ 实用工具 |
| **原生自动绑骨** | **15 种**模板骨架（biped、UE4/UE5、猫、龙、鸟、载具等）+ SkinCage + FK·IK；一键 `auto_rig_character`，**不依赖** AdvancedSkeleton（仅在明确要求且已安装时可用） |
| **视觉理解** | 对话可附带参考图；支持视觉的模型可调用 `capture_viewport` 截取视口对比；设置中可开关「图片输入」 |
| **多模型** | 默认 DeepSeek；另有 OpenAI / Azure / Claude / Gemini、通义、智谱、Kimi、豆包、百川、硅基流动、Cursor 代理、Ollama 与自定义 OpenAI 兼容接口 |
| **Maya 内嵌 UI** | 停靠深色面板：**对话 / 设置 / 工具 / 帮助**；紧凑输入区；发送与停止合并为同一按钮（绿 / 红）；Enter 发送、Shift+Enter 换行 |
| **会话随场景** | 多会话管理；自动 sidecar 保存为 `场景名.ma.mayaagent.json` |
| **安全可逆** | 工具在 Maya 主线程执行；整轮 Undo 块（可一键回退）；危险操作确认；默认不擅自新建空场景 |

**版本**：Maya **2020–2026**（自动适配 PySide2 / PySide6）

## 快速开始

### 方式 A：Windows 一键安装（推荐）

1. 双击项目根目录 **`install.bat`**（可选参数：`install.bat 2025` / `install.bat all`）
2. **完全退出并重启 Maya**
3. 菜单栏应出现 **Maya Agent**，工具架出现 **MayaAgent** 页签

卸载：双击 **`uninstall.bat`**。

### 方式 B：拖入式安装（当前会话立即生效）

1. 打开 Maya  
2. 将 **`install_dragdrop.mel`** 拖进 **视口**（或工具架 / Script Editor）  
3. 成功后菜单与工具架**立刻可用**，并写入自动加载（下次启动仍有效）

适合：`install.bat` 后插件列表已有 MayaAgent、但菜单/工具架未出现；或想跳过重启马上使用。

### 依赖（可选但推荐）

用对应版本的 `mayapy` 安装：

```bash
"C:\Program Files\Autodesk\Maya2025\bin\mayapy.exe" -m pip install -r requirements.txt
```

### 命令行安装

```bash
python scripts/install.py
python scripts/install.py --maya-version 2025
python scripts/install.py --uninstall
```

### 手动启动 / 热重载

Script Editor（Python）：

```python
import maya_agent
maya_agent.launch()   # 打开面板
maya_agent.reload()   # 改代码后重装菜单并打开面板
```

未装到 Maya 路径时，先把项目根目录加入 `sys.path`。也可使用菜单 **Maya Agent → 重新加载**。

### 配置 API

面板 → **设置 → 模型与 API** → 选服务商、填 API Key → 点「测试连接」（结果显示在按钮左侧，成功绿 / 失败红）→ **保存设置**。

也可设环境变量，例如 `DEEPSEEK_API_KEY`、`OPENAI_API_KEY`、`DASHSCOPE_API_KEY`。

## 界面

| 页签 | 内容 |
| ---- | ---- |
| **对话** | 多会话、流式回复、工具调用过程、快捷芯片、图片附件、发送/停止 |
| **设置** | 模型与 API（含图片输入、测试连接）/ Agent 行为（Undo、危险确认、最大工具轮次等）/ 界面字体 |
| **工具** | 按类别浏览全部工具；双击名称插入输入框 |
| **帮助** | 上手说明与功能概览 |

入口：菜单 **Maya Agent → 打开面板**，或工具架 **Agent** 按钮。

## 使用示例

- 「创建一个立方体，命名为 `SM_Crate`，冻结变换并居中枢轴」
- 「查看当前场景信息」
- 「按 UE5 模板创建骨架并对齐到选中网格，再自动蒙皮」
- 「给选中网格绑定到选中骨骼，最大影响数 4」
- 「自动展开 UV 并 Layout」
- 「把当前选择导出 FBX 到桌面」
- 「创建三点布光」
- （附参考图）「按这张图调整角色站姿」——视觉模型可再截视口核对

## 项目结构

```
MayaAgent/
├── config/default_config.yaml   # 默认配置与模型列表
├── maya_agent/
│   ├── core/                    # Agent 循环、记忆、执行器、Undo、会话
│   ├── llm/                     # 多厂商 LLM / 视觉适配
│   ├── tools/                   # Maya 工具（含 skeleton_templates、viewport）
│   ├── ui/                      # Qt 面板（对话 / 设置 / 工具 / 帮助）
│   ├── plugin/                  # 菜单、工具架、场景钩子
│   └── utils/                   # 配置、日志、Maya / Qt 兼容
├── resources/
│   ├── prompts/                 # 系统提示词
│   └── maya_plugin/             # 自动加载插件模板
├── scripts/
│   ├── install.py               # 安装 / 卸载
│   └── drag_install.py          # 拖入式安装逻辑
├── install.bat / uninstall.bat
├── install_dragdrop.mel         # 拖进视口安装
└── requirements.txt
```

## 故障排查

| 现象 | 处理 |
| ---- | ---- |
| 插件列表有 MayaAgent，但无菜单/工具架 | 拖入 `install_dragdrop.mel`，或 Script Editor 执行 `import maya_agent; maya_agent.reload()` |
| 改代码后界面未更新 | `maya_agent.reload()`，或菜单「重新加载」 |
| 测试连接失败 | 核对 API Key、Base URL、网络；通义等接口注意 Max Tokens 上限 |
| 无法附带/截取图片 | 设置中将「图片输入」设为开启，或换用带 vision 的模型 |

## 许可

MIT
