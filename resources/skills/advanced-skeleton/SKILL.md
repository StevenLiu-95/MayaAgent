---
name: advanced-skeleton
description: >-
  AdvancedSkeleton (ADV) Fit/Build auto-rig workflow. Use when ADV is available
  and the user wants AdvancedSkeleton, adv_auto_rig, adv_next_step, Fit templates,
  or production character controllers.
metadata:
  category: adv
  requires: adv
---

# AdvancedSkeleton

`read_skill` 后激活 `adv` 工具包（仅 ADV 可用时本 Skill 会出现在目录中）。

## 快速路径

1. `adv_rig_status` — 看 `next` / `oneshot`，确认阶段
2. **一键**：选中角色网格后 `adv_auto_rig`（template 如 biped / bipedGame / UE5；默认 cage 蒙皮）
3. **分步**：反复 `adv_next_step`（可中途手调 Fit；`skip_place=true` 跳过 AutoScale 直接 Build）
4. 补控：`adv_create_controller`；查模板：`adv_list_fit_templates`

## 注意

- 不要手写 MEL 调用 `AdvancedSkeleton` / `asReBuildAdvancedSkeleton` 等，一律用 `adv_*`。
- AutoPlace 失败可继续 Build，或请用户调 Fit 后再 `adv_next_step(skip_place=true)`。
- 场景勿有无关的 `Group` 命名冲突。
- ADV 不可用时改用 `character-rigging` 的 `auto_rig_character`。
