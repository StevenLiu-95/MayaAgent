---
name: maya-tool-dev
description: >-
  Author Maya tools, scripts, plugins, and shelf buttons inside MayaAgent.
  Use when the user asks to write a tool, plugin, shelf, validate script, or
  look up Maya API / cmds help via maya_dev tools.
metadata:
  category: maya_dev
---

# 工具开发

`read_skill` 后激活 `maya_dev` 工具包。

## 工作流

1. 先摸清环境与官方 API（`lookup_*` / 帮助检索类工具）
2. 出码 → 校验 → 落盘 → 运行测试
3. UI 用 PySide2/6 兼容写法；改场景逻辑包 Undo
4. 危险写盘前说明意图
5. 完成后将工具加到工具架，并用一两句话说明路径与调用方式
