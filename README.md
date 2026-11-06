# Maya Agent

**v1.6.0** — 面向 **Autodesk Maya 游戏开发管线** 的 AI Agent：用自然语言驱动建模、UV、绑骨蒙皮、动画、材质、灯光与导出。内置 **235 个工具 / 18 个类别**，支持 **15 家**主流大模型（含视觉模型）与云端 AI 3D（Meshy / Tripo / 腾讯混元3D），并可通过 MCP 在 Cursor / VS Code / Claude Desktop 中调用同一套能力。

## 核心能力

| 能力 | 说明 |
| ---- | ---- |
| **工具调用 Agent** | 235 个内置工具（18 个类别）；LLM 规划 → 执行 → 流式回写；单轮可多步工具（默认最多 30 轮，设置里可调至 100） |
| **游戏工作流覆盖** | 场景 / 建模 / UV / 绑骨蒙皮 / 动画 / 材质 / 灯光 / 导出（FBX·OBJ·USD·ABC）/ 游戏管线 / 本地文件 / 数据分析 |
| **原生自动绑骨** | **15 种**模板骨架（biped、bipedGame、UE4/UE5、猫、龙、鸟、马、大猩猩、鱼、昆虫、恐龙、载具、previs 等）+ SkinCage 几何代理蒙皮 + FK/IK 控制器；一键 `auto_rig_character`，**不依赖** AdvancedSkeleton（仅在明确要求且已安装时可用 `adv_*`） |
| **蒙皮与权重** | 11 个权重工具（读取/写入/分析/裁剪/归一/限制影响数/镜像/平滑/对齐/复制/迁移）；`skin_pipeline` 支持烘焙世界姿态、拆皮与清场；Meshy/Tripo 错位资产可自动对齐并同步 `bindPreMatrix` |
| **视觉理解** | 对话可附带参考图；视觉模型可 `capture_viewport`（单视角）/ `capture_viewport_views`（多视角）/ `render_still`（静帧）截取视口核对，也可 `search_images` / `fetch_image` 拉取网络参考图；设置中可切换「图片输入」策略 |
| **网络检索** | `web_search` / `fetch_webpage` / `search_images` / `fetch_image` / `fetch_images`；无需搜索 API Key（DuckDuckGo/Bing 抓取 + Wikipedia 摘要），可在配置 `web.enabled` 关闭 |
| **数据可视化** | `generate_chart` 生成折线/柱状/箱线/散点/直方/饼图，图表自动嵌入回复正文，适合数值对比、权重分布、性能统计 |
| **多模型** | 默认 DeepSeek；另含 OpenAI / Grok (xAI) / Azure OpenAI / Claude / Gemini、通义千问、智谱 GLM、Kimi、豆包、百川、硅基流动、Cursor 代理、Ollama 与自定义 OpenAI 兼容接口，共 **15 家** |
| **云端 AI 3D** | **Meshy（16 工具）/ Tripo（27 工具）/ 腾讯混元3D（20 工具）**：文/图/多视图生 3D、贴图、减面、UV、绑骨、动画与格式转换；任务轮询后下载 FBX 并导入 Maya |
| **Maya 内嵌 UI** | 停靠深色面板：**对话 / 模型 / 设置 / 工具 / 帮助** 五个页签；紧凑输入区；发送与停止合并为同一按钮（绿 / 红）；Enter 发送、Shift+Enter 换行；Ctrl+V 粘贴截图、拖入文件附件 |
| **Agent / Ask / Plan 模式** | 对话栏可切换：**Agent**（全工具）、**Ask**（只读调研）、**Plan**（先 `create_plan` 出步骤卡片，用户「批准执行」后再改场景）；工具按模式白名单裁剪，执行器二次拦截；MCP `mayaagent_chat` 可传 `mode` |
| **上下文压缩与环路守卫** | 发给 LLM 时自动压缩较旧的工具结果（会话 sidecar 仍存全文）；同轮只读工具去重、连续相同调用熔断（可在 `agent.context_compress` / `agent.loop_guard` 关闭） |
| **User Rules** | 设置页或项目 `rules/*.md` 写持久规范（命名/轴向/导出等），自动注入 system prompt；`_` 开头为草稿不注入；不覆盖 Ask/危险确认 |
| **会话随场景** | 多会话管理；自动 sidecar 保存为 `场景文件.mayaagent.json`（与场景同目录，随工程拷贝）；未命名场景暂存临时目录，保存后迁移 |
| **安全可逆** | 场景类工具在 Maya 主线程执行（网络/文件类工具不阻塞主线程）；整轮 Undo 块（一轮修改一次 Ctrl+Z 回退，MCP 侧 `mayaagent_undo`）；危险操作确认；本地文件读写白名单；默认不擅自新建或保存场景 |
| **工具开发** | `maya_dev` 18 个元工具：查 Maya API、检索 cmds 帮助、校验/写入/运行脚本、生成工具模板、创建工具架按钮、加载插件 |
| **MCP** | Cursor / VS Code / Claude Desktop 经 MCP 调用**同一套** Maya 工具，或远程驱动 `mayaagent_chat` 完整 Agent 循环；本地 HTTP 桥仅监听 `127.0.0.1` + Bearer token |
| **国际化** | 10 种界面语言（中简/中繁/英/日/韩/法/德/西/葡/俄）；系统提示词为中文，按语言追加「输出语言」指令 |

**版本**：Maya **2020–2026**（自动适配 PySide2 / PySide6）；Python 3.7+。

## 快速开始

### 方式 A：Windows 图形安装器（推荐，免系统 Python）

面向最终用户的商业安装包（Inno Setup）：

1. 运行 **`MayaAgent-Setup-1.6.0.exe`**（由 `installer\build.bat` 生成，见 [`installer/README.md`](installer/README.md)）
2. 选择安装目录（默认 `%LOCALAPPDATA%\MayaAgent`）与要挂钩的 **Maya 版本**
3. **完全退出并重启 Maya** → 菜单 **Maya Agent** / 工具架 **MayaAgent**

- **不需要**本机安装系统 Python；安装引擎通过 **mayapy** 写挂钩并应用预置 `vendor_cache` → `.vendor/cp37|cp39|cp311`
- 不含 MCP / 代码签名 / 自动更新（MCP 仍见下文「MCP」）
- 构建者：先 `python scripts/build_vendor_cache.py`，再 `installer\build.bat`

### 方式 B：`install.bat`（源码 / TD，优先 mayapy）

1. 双击项目根目录 **`install.bat`**（可选：`install.bat 2025` / `install.bat all` / `install.bat force` / `install.bat uninstall`）
2. **完全退出并重启 Maya**
3. 菜单栏应出现 **Maya Agent**，工具架出现 **MayaAgent** 页签

`install.bat` / `uninstall.bat` **优先查找 mayapy**，找不到再回退系统 Python；无 Python 时可改用图形安装器或拖入 mel。

版本与 mayapy 由 `scripts/maya_discover.py` 统一探测（Documents 用户目录、注册表、常见安装路径）。非标准安装可设置：

```bat
set MAYA_AGENT_MAYAPY_ROOTS=D:\LAS\LAD\Maya\Program\2025\Maya2025
install.bat
```

安装结束会打印 **Install Report**（每版本 hooks / deps / mayapy / load_path）。挂钩失败为错误；仅依赖失败时菜单通常仍可用。对话需 `httpx`，统计图表需 `matplotlib`（均在安装必检列表中）。

诊断（只读）：

```bash
python scripts/doctor.py
python scripts/doctor.py --maya-version 2025
```

卸载：双击 **`uninstall.bat`**，或 `mayapy scripts/install_engine.py --uninstall`。

### 方式 C：拖入式安装（当前会话立即生效）

1. 打开 Maya
2. 将 **`install_dragdrop.mel`** 拖进 **视口**（或工具架 / Script Editor）
3. 成功后菜单与工具架**立刻可用**，并写入自动加载（下次启动仍有效）；同时会尝试为当前 mayapy / `.vendor` 安装对话依赖

适合：`install.bat` 后插件列表已有 MayaAgent、但菜单/工具架未出现；或想跳过重启马上使用。

### 依赖（对话必需 httpx；图表必需 matplotlib）

`install.bat` / `install_engine.py` / 图形安装器会自动安装。失败时的加固路径（依次降级）：

1. 预置 **`vendor_cache/<abi>/`** → 项目 **`.vendor/<abi>/`**（离线）
2. mayapy pip（PyPI → 清华 → 阿里 → 腾讯镜像，多镜像 + 代理/直连）
3. 逐包安装缺失模块
4. 可用 Python 下载 wheel → mayapy 离线安装
5. mayapy `pip install --target .vendor/<abi>`（启动时按解释器 ABI 注入）

手动：

```bash
python scripts/install_deps.py --maya-version 2025 --force
python scripts/install_deps.py --vendor-only --tags cp311
python scripts/build_vendor_cache.py --tags cp311
```

### 命令行安装

```bash
# 统一引擎（推荐；可用 mayapy 运行）
mayapy scripts/install_engine.py
mayapy scripts/install_engine.py --maya-version 2025
mayapy scripts/install_engine.py --force-deps
mayapy scripts/install_engine.py --uninstall

python scripts/install.py --maya-version 2025
python scripts/install.py --dry-run
python scripts/doctor.py
```

### 手动启动 / 热重载

Script Editor（Python）：

```python
import maya_agent
maya_agent.launch()   # 打开面板
maya_agent.reload()   # 改代码后重装菜单并打开面板
```

未装到 Maya 路径时，先把项目根目录加入 `sys.path`。也可使用菜单 **Maya Agent → 重新加载**（若面板仍显示旧界面，先关闭面板再打开）。

### 配置 API

面板 → **模型 → LLM** → 选服务商、填 API Key → 点「测试连接」（结果显示在按钮左侧，成功绿 / 失败红）。修改会自动保存；可用「恢复默认」重置参数（API Key 保留）。

也可设环境变量，例如 `DEEPSEEK_API_KEY`、`OPENAI_API_KEY`、`XAI_API_KEY`、`ANTHROPIC_API_KEY`、`GOOGLE_API_KEY`、`DASHSCOPE_API_KEY`、`ZHIPU_API_KEY`、`MOONSHOT_API_KEY`、`ARK_API_KEY`、`SILICONFLOW_API_KEY`、`MESHY_API_KEY`、`TRIPO_API_KEY`、`TENCENTCLOUD_SECRET_ID`、`TENCENTCLOUD_SECRET_KEY`。

- 本地模型：Ollama 默认 `http://127.0.0.1:11434/v1`；自定义 OpenAI 兼容接口填 Base URL + 模型名即可；Cursor 需先在本机启动 Cursor→OpenAI 代理（默认 `http://127.0.0.1:4646/v1`）。
- Tripo（[开发者文档](https://developers.tripo3d.com/zh/docs)）：面板 → **模型 → Tripo** → 填 API Key →「测试连接」。默认 Base URL 为国区 `https://openapi.tripo3d.com/v3`（国际站可在配置中改为 `https://openapi.tripo3d.ai/v3`）。
- 混元生3D（[API 概览](https://cloud.tencent.com/document/product/1804/120838)）：面板 → **模型 → 混元** → 填腾讯云 `SecretId` / `SecretKey` 与 Region →「测试连接」。默认接入点 `ai3d.tencentcloudapi.com`（国区 `ap-guangzhou`）。3D 后处理输入需公网 URL 或上游任务 JobId 串联，不支持本地网格直传。

## 界面

| 页签 | 内容 |
| ---- | ---- |
| **对话** | 多会话（新建 / 重命名 / 删除 / 切换）、流式回复、思考过程、工具卡片（进度/参数/结果/图片）、可点击选项按钮、快捷指令芯片、图片与文件附件、发送/停止合并按钮 |
| **模型** | 4 个子页：**LLM**（连接 / 生成 / 行为 / 限制，含测试连接）、**Meshy**、**Tripo**、**混元**（启用开关 + 密钥 + 测试连接/余额） |
| **设置** | 语言、字体族、整体缩放（75–175%）、临时文件目录、AdvancedSkeleton 路径与检测、MCP Bridge（开关/端口/确认模式/启停/复制配置） |
| **工具** | 按 18 个类别浏览全部工具；双击工具名插入输入框（「请调用工具 X」）；右侧/下方显示说明与参数 |
| **帮助** | 快速上手、对话与模型设置说明、MCP 接入、内置工具一览、安全约定、菜单与重载 |

入口：菜单 **Maya Agent → 打开面板**，或工具架 **Agent** 按钮。停靠模式下默认停靠到「属性编辑器」标签组右侧。

## 使用示例

**场景与建模**

- 「创建一个立方体，命名为 `SM_Crate`，冻结变换并居中枢轴」
- 「查看当前场景信息，检查相机裁剪面是否覆盖所有物体」
- 「用圆柱和管道搭一个白盒，按 3 步细化并每步截图给我看」
- 「把选中的高模减面并合并，命名规范用 `SM_` 前缀」

**UV（游戏资产）**

- 「给选中模型做游戏 UV」→ `preflight_uv`（可选预检）→ `prepare_game_uv`（默认 `cut_mode=auto` 自动切缝）→ `capture_uv_layout` 目视复核
- 「给这个角色统一 texel density 到 10.24 px/cm，并按 0–1 atlas 排布」

**绑骨与蒙皮**

- 「按 UE5 模板创建骨架并对齐到选中网格，再自动蒙皮」
- 「用 biped 模板一键绑骨，包含 FK/IK 控制器」
- 「给选中网格绑定到选中骨骼，最大影响数 4，然后分析并清理远端着色权重」
- 「把 Meshy 生成的骨架和网格对齐，并把权重迁移到原始分件上」

**动画 / 材质 / 灯光 / 导出**

- 「给选中物体第 1、24、48 帧打关键帧，并播放一遍预览」
- 「创建三点布光并瞄准选中物体」
- 「把当前选择导出 FBX 到桌面，嵌入贴图」
- 「保存场景并生成 LOD 分组」

**云端 AI 3D**

- 「用 Meshy 按这段描述生成一个石头怪模型，确认消耗后生成，完成后导入 Maya」
- 「用 Tripo 把这张参考图生成角色，并做一个奔跑动画」
- 「用混元把上一任务的模型贴图后转成 FBX」

**数据与文件**

- 「统计所有网格的顶点数并生成柱状图」
- 「列出临时目录里的对话截图，把第 2 张图片发给我」
- 「读取我拖入的这份规范文档，按它给模型命名」

**工具开发**

- 「帮我查 `polyReduce` 的参数，写一个可复用的 Maya 工具脚本，校验后保存到 scripts 目录，并在工具架创建按钮」

## 内置工具（235 个 / 18 类）

| 类别 | 数量 | 代表工具 |
| ---- | ---- | ---- |
| 场景 scene | 14 | `get_scene_info`、`list_selection`、`select_objects`、`rename_object`、`batch_rename`、`create_group`、`parent_objects`、`duplicate_objects`、`delete_objects`、`clean_scene`、`set_frame_range`、`capture_viewport`、`capture_viewport_views`、`render_still` |
| 建模 modeling | 25 | `create_primitive`（12 种图元）、`create_primitives`、`arrange_objects`、`combine_meshes`、`separate_meshes`、`boolean_meshes`、`extrude_faces`、`bevel_edges`、`smooth_mesh`、`reduce_mesh`、`mirror_geometry`、`create_curve`、`mesh_from_curve`、`create_text_mesh`、`thicken_mesh`、`cleanup_mesh`、`check_meshes`、`edit_mesh_topology`、`edit_mesh_normals`、`select_mesh_components`、`transform_components` 等 |
| UV uv | 13 | `preflight_uv`、`prepare_game_uv`、`cut_uv_edges`、`sew_uv_edges`、`get_uv_info`、`auto_unwrap_uv`、`unfold_uv`、`optimize_uv`、`layout_uv`（支持 UDIM）、`set_texel_density`、`check_uv_quality`、`capture_uv_layout` 等 |
| 绑骨 rigging | 48 | 15 个 `create_skeleton_*` 模板 + `list_skeleton_templates`、`auto_rig_character`、`auto_rig_biped`、`create_joint`/`create_joint_chain`/`orient_joints`、`bind_skin`/`unbind_skin`、`build_fk_ik_controls`、`create_skin_cage`/`bind_from_skin_cage`、权重 11 件套、`extract_skinned_geometry` 等 |
| ADV adv | 10 | `adv_rig_status`、`adv_auto_rig`、`adv_next_step`、`adv_import_fit_skeleton`、`adv_set_skin_meshes`、`adv_auto_place_fit`、`adv_build_rig`、`adv_bind_skin`、`adv_create_controller`、`adv_list_fit_templates` |
| 动画 animation | 5 | `set_keyframe`、`delete_keyframes`、`bake_animation`、`playblast`、`copy_animation` |
| 材质 materials | 5 | `create_material`、`assign_material`、`assign_texture`、`describe_material_attrs`、`list_materials` |
| 灯光 lighting | 3 | `create_light`、`create_three_point_lighting`、`create_environment_light` |
| 导出 export | 7 | `export_fbx`、`import_fbx`、`export_obj`、`export_usd`、`export_abc`、`save_scene`、`open_scene` |
| 游戏管线 utilities | 5 | `set_transform`、`create_lod_group`、`create_collision_mesh`、`apply_game_naming`、`reset_transform` |
| 本地文件 files | 10 | `get_workspace_info`、`list_directory`、`path_info`、`read_text_file`、`write_text_file`、`copy_file`、`delete_path`、`list_chat_images`、`save_chat_images`、`list_chat_files` |
| 数据分析 analysis | 1 | `generate_chart`（line / bar / box / scatter / hist / pie） |
| 网络检索 web | 5 | `web_search`、`fetch_webpage`、`search_images`、`fetch_image`、`fetch_images` |
| Meshy meshy | 16 | 文/图/多视图生 3D、贴图、减面、转换、UV、绑骨、动画、任务查询/下载/导入、余额 |
| Tripo tripo | 27 | 文/图/多视图生 3D、图像链路、贴图/转换/分割/补洞/减面、绑骨/重定向/动画、上传/任务/下载/导入、余额/用量、权重与动画安全迁移 |
| 混元3D hunyuan | 20 | Pro/Rapid 文/图/多视图、人物模板、贴图/减面/部件/UV、自动绑骨、文生动作、任务查询/转换/下载/导入、连接测试 |
| 脚本 scripting | 3 | `execute_python`（atomic 默认回滚）、`execute_mel`、`generate_python_snippet` |
| 工具开发 maya_dev | 18 | `lookup_cmds_help`、`search_cmds`、`lookup_api_help`、`validate_python`、`run_python_file`、`write_script_file`、`scaffold_maya_tool`、`create_shelf_button`、`list_plugins`、`load_or_unload_plugin` 等 |

> 说明：工具会按可用性动态裁剪——未配置密钥的 Meshy/Tripo/混元工具、未安装的 ADV 工具、以及不支持视觉的模型下的截图/搜图工具不会出现在模型工具列表中；系统提示词中的对应章节也会同步隐藏。`destructive` 工具（删除、解包、打开场景、执行脚本等）在开启「危险操作前确认」时会先弹窗。

## MCP

在 **Cursor / VS Code / Claude Desktop** 等支持 MCP 的 IDE 中控制当前 Maya 会话：工具列表与 MayaAgent 面板共用同一注册表、同一系统提示词与同一撤销语义。

### 步骤

1. **Maya 内启动 MCP**：菜单 **Maya Agent → 启动 MCP**（或「设置」页签中的 MCP Bridge 区块）
2. **系统 Python 安装 MCP 依赖**（不要用 mayapy）：

```bash
pip install -r requirements-mcp.txt
```

3. **复制 MCP 配置**：菜单 **复制 MCP 配置**，粘贴到 Cursor / VS Code 的 `mcp.json`，例如：

```json
{
  "mcpServers": {
    "maya-agent": {
      "command": "python",
      "args": ["D:/path/to/MayaAgent/scripts/maya_mcp.py"]
    }
  }
}
```

将路径改成你的项目根目录；`python` 需能 `import mcp` / `httpx`。

4. 在 IDE 中确认 MCP 已连接，然后：
   - 调用 `mayaagent_status` 检查服务是否在线（含 `tool_count`）
   - **直接调用**任意 Maya 工具（与面板相同的工具名）
   - 或调用 `mayaagent_chat` 走完整 MayaAgent 多轮循环
   - `mayaagent_undo` 回退上一轮 Agent 修改
   - `mayaagent_system_prompt` 获取/刷新系统提示词

### 本地 HTTP 桥

Maya 进程内运行 loopback HTTP 服务，MCP 代理只是无状态适配器：

| 方法 | 路径 | 说明 |
| ---- | ---- | ---- |
| GET | `/v1/health` | 状态、Maya 版本、`tool_count`（免鉴权） |
| GET | `/v1/tools` | 全部工具 schema |
| POST | `/v1/tools/call` | 调用单个工具（含危险确认与 undo） |
| POST | `/v1/agent/chat` | 完整 Agent 循环 |
| POST | `/v1/agent/undo` | 回退上一轮 |
| GET | `/v1/mcp-config` | MCP 配置片段 |
| GET | `/v1/system-prompt` | 与面板同源的系统提示词 |

- 仅监听 `127.0.0.1`，除 health 外均需 `Authorization: Bearer <token>`；token 每次启动随机生成。
- 发现文件：`%APPDATA%/MayaAgent/bridge.json`（含 host / port / token / pid）。重启 MCP 会刷新 token，IDE 需重连。
- 面板与 IDE 共享同一 Agent，同一时间只允许一个对话在跑；面板忙时 MCP 请求会等待或报 busy。

MCP 连接时会把与面板相同的系统提示词（`resources/prompts/system_zh.md` + 运行时环境）注入为 server `instructions`；修改该 md 后，面板与 IDE 两侧都会生效（IDE 侧需重连 MCP 或调 `mayaagent_system_prompt` 获取最新全文）。

## 架构速览

单进程、无 asyncio、无 LLM SDK 依赖：

```
菜单/工具架 ──► ui/main_window（Qt 面板，Maya 主线程）
                    │
                    ├─ AgentWorker（QThread）──► core/MayaAgent.chat() 生成器
                    │        │                      ├─► llm/*Provider（httpx，流式）
                    │        │                      ├─► core/ToolExecutor ──► tools/registry（235 个）
                    │        │                      │        └─ 危险确认 / undo chunk / 主线程 marshal
                    │        │                      └─► memory / session sidecar / undo / system_prompt
                    │        └─ 事件字典（text/thinking/tool_*/done/stopped/error）经 Qt Signal 回主线程
                    │
                    └─ bridge/http_server（127.0.0.1 + token）◄── scripts/maya_mcp.py ◄── Cursor/VS Code
```

- **Agent 循环**：`MayaAgent.chat()` 是同步生成器状态机，`yield` 事件驱动流式文本、工具轮、进度与结束；工具串行执行，取消为协作式（`threading.Event` + 检查点）。
- **线程模型**：Maya 主线程（UI/场景操作）→ QThread（Agent 循环）→ 每工具 side thread（长网络任务可边跑边报进度）→ 需要 `maya.cmds` 时 `executeInMainThreadWithResult` 跳回主线程。
- **可逆性**：一轮内首次工具调用时打开整轮 undo chunk，所有修改折叠为一次 Ctrl+Z；MCP 侧对应 `mayaagent_undo`。
- **能力降级**：ADV 是否安装、云服务是否有密钥、模型是否支持视觉，会同时影响「工具列表 + 系统提示章节 + 运行环境说明」三处。
- **会话模型**：`memory`（给模型看，按条数窗口裁剪）与 `ui_blocks`（给界面看）各存一份，统一写入场景 sidecar。

## 数据与配置目录

| 路径 | 内容 |
| ---- | ---- |
| `<项目>/config/default_config.json` | 默认配置（运行时加载，无第三方依赖）；`default_config.yaml` 为同内容的人类可读版本，JSON 缺失时才兜底 |
| `%APPDATA%/MayaAgent/settings.json` | 用户设置（深合并覆盖默认；语言、模型、UI、Agent、Maya、Bridge 等） |
| `%APPDATA%/MayaAgent/secrets.json` | API Key（优先级高于环境变量） |
| `%APPDATA%/MayaAgent/bridge.json` | MCP 发现文件（Maya 启动 MCP 时写入） |
| `%APPDATA%/MayaAgent/logs/maya_agent.log` | 运行日志 |
| `<场景文件>.mayaagent.json` | 会话 sidecar（与场景同目录）；未命名场景暂存临时目录 |
| `<项目同级>/MayaAgentTempFile/` | 默认临时根目录：对话附图/附件、云 3D 下载、视口截图、未命名会话（设置 `ui.temp_dir` 可改） |
| `<项目>/.vendor/cp37\|cp39\|cp311/` | 按 ABI 分目录的依赖兜底（安装器从 `vendor_cache` 拷贝；已 gitignore） |
| `<项目>/vendor_cache/` | 构建机预置的离线依赖树（打进 Setup；已 gitignore） |
| `<项目>/dist/` | `MayaAgent-Setup-*.exe` 输出目录 |

## 项目结构

```
MayaAgent/
├── VERSION                      # 唯一版本号源（发版改这里）
├── config/default_config.yaml   # 默认配置（人类可读）
├── config/default_config.json   # 运行时加载（无第三方依赖）
├── maya_agent/
│   ├── bridge/                  # 本地 HTTP 桥（工具 + 远程 Agent + 发现文件）
│   ├── core/                    # Agent 循环、记忆、执行器、Undo、会话、提示词
│   ├── llm/                     # 多厂商 LLM / 视觉适配（OpenAI 兼容 / Anthropic / Gemini / Cursor）
│   ├── tools/                   # 235 个 Maya 工具（建模/UV/绑定/蒙皮/动画/云 3D/文件/开发）
│   ├── ui/                      # Qt 面板（对话 / 模型 / 设置 / 工具 / 帮助）
│   ├── plugin/                  # 菜单、工具架、场景钩子
│   └── utils/                   # 配置、路径、日志、Maya / Qt / 线程兼容
├── resources/
│   ├── prompts/                 # 系统提示词（面板与 MCP 共用）
│   ├── locales/                 # 10 种界面语言
│   └── maya_plugin/             # 自动加载插件模板
├── scripts/
│   ├── maya_mcp.py              # MCP stdio 代理（系统 Python）
│   ├── install_engine.py        # 安装器/bat 统一引擎（mayapy 可跑）
│   ├── install.py               # 挂钩写入 + Install Report
│   ├── install_deps.py          # mayapy 依赖 / vendor_cache / .vendor/<abi>
│   ├── build_vendor_cache.py    # 构建离线 vendor_cache
│   ├── version_utils.py         # 读 VERSION / 同步各处副本
│   ├── sync_version.py / bump_version.py
│   ├── maya_abi.py              # Maya 版本 ↔ cp37/cp39/cp311
│   ├── maya_discover.py         # Maya 版本 / mayapy 统一探测
│   ├── doctor.py                # 安装健康检查（只读）
│   ├── drag_install.py          # 拖入式安装逻辑（含依赖加固）
│   └── test_*.py                # 离线/冒烟测试脚本
├── installer/                   # Inno Setup 商业安装器
│   ├── MayaAgent.iss
│   ├── build.bat
│   └── README.md
├── install.bat / uninstall.bat  # 优先 mayapy
├── install_dragdrop.mel         # 拖进视口安装
├── recover_tools_dragdrop.mel   # 工具注册表异常时急救
├── requirements.txt             # Maya 内依赖（httpx / PyYAML / matplotlib）
├── requirements-mcp.txt         # IDE MCP 代理依赖（系统 Python）
├── vendor_cache/                # 预置离线依赖（构建生成，已 gitignore）
├── dist/                        # Setup.exe 输出
└── .vendor/                     # 运行时 ABI 依赖树（自动生成，已 gitignore）
```

## 测试与诊断

| 命令 | 用途 |
| ---- | ---- |
| `python scripts/doctor.py` | 安装健康检查（hooks / mod / junction / 依赖 / 插件模板），只读 |
| `python scripts/smoke_test.py` | 冒烟测试 |
| `python scripts/test_ui_smoke.py` | UI 无头冒烟（需 PySide） |
| `python scripts/test_risk_fixes_unit.py` | 风险修复回归：主线程跳板 / 确认框线程 / 云端轮询取消 / 撤销边界 / 配置持久化 / 会话原子写盘 |
| `python scripts/test_registry_reload_unit.py` | 工具注册表热重载回归 |
| `python scripts/test_bridge_protocol.py` | HTTP 桥协议 / 鉴权 |
| `python scripts/test_mcp_proxy.py` | MCP 代理链路 |
| `python scripts/test_memory.py`、`test_vision_messages.py`、`test_chat_blocks.py`、`test_linkify.py` | 记忆、视觉消息、聊天渲染块、链接解析 |
| `python scripts/test_tripo_client_unit.py`、`test_meshy_upload_timeout.py`、`test_hunyuan_client_unit.py` | 云 3D 客户端离线单测 |
| `python scripts/test_charts.py`、`test_web_tools.py`、`test_uv_helpers_unit.py`、`test_bind_prematrix_sync.py`、`test_install_chain.py` | 图表、网络工具、UV helper、绑定矩阵、安装链 |

## 故障排查

| 现象 | 处理 |
| ---- | ---- |
| 安装状态不明 | 运行 `python scripts/doctor.py`，对照 Install Report |
| 需要发给无系统 Python 的用户 | 使用 `installer\build.bat` 生成的 `MayaAgent-Setup-*.exe` |
| 插件列表有 MayaAgent，但无菜单/工具架 | 拖入 `install_dragdrop.mel`，或 Script Editor（**Python**）执行 `import maya_agent; maya_agent.reload()` |
| MCP `tool_count` 异常 / 工具变少 | 拖入 `recover_tools_dragdrop.mel`，或执行 `maya_agent.reload()` 后重启 MCP |
| 未检测到 mayapy / 自定义安装路径 | 设置 `MAYA_AGENT_MAYAPY_ROOTS` 后重跑 `install.bat` |
| `No module named 'httpx'` / `matplotlib` / pip SSL / 代理报错 | 运行 `install.bat force`，或 `python scripts/install_deps.py --force`；仍失败则 `--vendor-only`。菜单不依赖 PyYAML |
| `No module named 'yaml'` | 默认配置为 JSON，菜单可用；可选装 PyYAML，或同上走 `.vendor` |
| `install_dragdrop.mel` Syntax error | 确认拖入的是项目根目录最新版；MEL 需用 `+` 拼接字符串，勿用 Script Editor 的 MEL 模式粘贴 Python |
| 改代码后界面未更新 | 先关闭面板，再 `maya_agent.reload()` 或菜单「重新加载」 |
| 测试连接失败 | 核对 API Key、Base URL、网络；通义等接口注意 Max Tokens 上限 |
| 无法附带/截取图片 | 设置中将「图片输入」设为开启/自动，或换用带 vision 的模型 |
| MCP 连不上 / unauthorized | 先在 Maya 启动 MCP；重启 MCP 会刷新 token；确认 `pip install -r requirements-mcp.txt` 用的是 mcp.json 里的同一个 Python |
| 云 3D 任务失败 | 检查密钥、余额与网络；Tripo/混元导入优先 FBX（非 FBX 会自动转换）；混元不支持本地网格直传 |
| 会话没随场景恢复 | 确认场景已保存（sidecar 写在场景同目录），或检查 `agent.auto_save_sessions` 是否开启 |

## 版本管理

**唯一源文件**：项目根目录 [`VERSION`](VERSION)（当前内容即发布版本号）。

运行时 UI / About / Bridge / `.mod` 挂钩均读取该文件（经 `maya_agent.__version__` 或 `scripts/version_utils.py`）。发版时同步副本：

```bash
# 只同步（改完 VERSION 之后）
python scripts/sync_version.py

# 或直接升版并同步
python scripts/bump_version.py 1.5.7
python scripts/bump_version.py --patch
```

会更新：`pyproject.toml`、`installer/MayaAgent.iss`、`config/default_config.*`、README / installer 文档中的 Setup 文件名。  
`installer\build.bat` 打包前会自动执行 `sync_version.py`。

## 许可

MIT
