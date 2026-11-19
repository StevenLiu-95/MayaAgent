---
name: character-rigging
description: >-
  Character skinning, skeleton, auto-rig, FK/IK, and keyframe animation with
  native MayaAgent tools. Use when the user asks for 绑骨, 蒙皮, skin weights,
  auto_rig, skeleton, ControlSet, or animation keys. Chooses among ADV, native,
  and cloud rig paths.
metadata:
  categories: rigging,animation
---

# 骨骼绑定与动画（原生总览）

`read_skill` 后激活 `rigging` + `animation` 工具包。导出 FBX 时再 `activate_tool_pack("export")`。

## 方案选择

按**当前可用工具**选择（运行环境会标注 AdvancedSkeleton）：

1. **AdvancedSkeleton（ADV）**：读 `advanced-skeleton`（Fit→Build→控制器/蒙皮）
2. **原生工具**：`auto_rig_character` / `create_skeleton_*` + SkinCage + FK/IK（本 Skill）
3. **AI 云端绑骨**：读 `meshy-3d` / `tripo-3d` / `hunyuan-3d`

优先级：**ADV > 原生 > 云端**。多种方案均可时用选项块询问。  
云端生 3D 多家可用时，用选项块询问选用哪一家。

## 原生路径要点

- 一键：`auto_rig_character` 或先 `list_skeleton_templates` 再 `create_skeleton_*`
- 蒙皮/权重：SkinCage、权重读写/镜像/平滑、`transfer_skin_weights`、`align_skinned_rig`
- 动画 K 帧优先用 animation 工具；ADV 控制器生成后可对 ControlSet 打关键帧（先读 `advanced-skeleton`）
