---
name: game-asset-uv
description: >-
  Game-ready UV workflow for Maya meshes. Use when the user asks for UVs,
  unwrap, texel density, atlas layout, UDIM, seams, prepare_game_uv, or UV
  quality checks. Prefer native uv tools over cloud UV unless user asks.
metadata:
  category: uv
---

# 游戏资产 UV

`read_skill` 后激活 `uv` 工具包。云端 Meshy/混元 UV 仅在走对应云端管线时使用（先读 `meshy-3d` / `hunyuan-3d`）。

## 质量优先级

1. 除非用户明确要求，否则 UV 块不允许重叠、越界
2. 不要切得太碎，保持连贯
3. 避免拉伸
4. 提高利用率

## 游戏资产默认 0–1 atlas

1. **预检**：网格可能非流形/脏拓扑时先 `preflight_uv(apply_cleanup=true)`；`prepare_game_uv` 默认已含清理。
2. **一键**：意图清晰时优先 `prepare_game_uv`（默认 `cut_mode=auto`：适量硬边→hard，否则 none，避免大网格低角度切碎）→ 看质检与 `layout.backend`；再 `capture_uv_layout` 目视。
3. **精确拆分**：`cut_uv_edges`（hard/angle/material/border/selection/indices）；过度切开用 `sew_uv_edges`；决策前可 `get_uv_info`。大网格勿用很小的 `angle_degrees` 乱切。
4. **展开与排布**：`auto_unwrap_uv` / `unfold_uv` / `optimize_uv` → `layout_uv`（可指定 `udim`）；统一密度用 `set_texel_density`。
5. **质检**：`check_uv_quality`（重叠/翻转/零面积/出界；邻接面不记假重叠）；旧名 `check_uv_overlaps` 已转发。

不要手写 `polyMapCut` / `u3dLayout` / `uvSnapshot` 脚本代替上述工具。
