---
name: procedural-modeling
description: >-
  Procedural / in-Maya modeling and scene blocking. Use when the user asks to
  model, build geometry, blockout, whitebox, hard-surface, architecture, or
  scene props with Maya tools (not cloud AI 3D). Also use to decide procedural
  vs Meshy/Tripo/Hunyuan when modeling intent is unclear.
metadata:
  category: modeling
---

# 程序化建模

`read_skill` 后会激活 `modeling` 工具包。跨类需求（材质、灯光、导出）再用 `activate_tool_pack`。

## 何时用

- 硬表面、建筑、场景、规则几何、白盒比例
- 用户明确要求在 Maya 内用工具/脚本建模

有机角色/动植物等不规则物体优先考虑云端 Skill（`meshy-3d` / `tripo-3d` / `hunyuan-3d`）。多种方案均可时用选项块询问。

## 程序化要求

- 优先使用已有建模工具；工具不够时再 `execute_python` / MEL。
- 一般步骤：
  1. 简单几何体搭白盒，确认比例（可 `capture_viewport`）
  2. 一次细化：大块细节
  3. 二次细化：小细节
  4. 材质收尾（需材质工具时 `activate_tool_pack("materials")`）
- 可按任务增删步骤；每步完成后做视觉确认。

## 调用云端 API 建模时（改读对应 Skill）

- 先查余额/估消耗，用户确认后再跑；失败先恢复任务。
- 必须导入 Maya 并带材质才算完成。
- 相关工具不可用时回退本 Skill 的程序化路径。
