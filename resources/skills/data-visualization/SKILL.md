---
name: data-visualization
description: >-
  Charts and data visualization with generate_chart. Use when the user asks for
  charts, plots, histograms, weight distribution, performance stats, or numeric
  comparisons (line/bar/box/scatter/hist/pie).
metadata:
  category: analysis
---

# 数据可视化

`read_skill` 后激活 `analysis` 工具包（含 `generate_chart`）。

## 用法

1. 调用 `generate_chart`（`chart_type`：`line` / `bar` / `box` / `scatter` / `hist` / `pie`），把整理好的数值放进 `series`。
2. 工具返回的 `path`（及 `embed_markdown` / `embed_chart`）用于正文嵌入。
3. **最终回复必须在合适位置嵌入图表**（作为正文一部分，勿只口头描述）：
   - 推荐：`![图表标题](工具返回的绝对路径)`
   - 或：`[[CHART]]绝对路径|图表标题[[/CHART]]`
4. 可先简短结论，再嵌入图表，必要时再补充解读；一张图对应一处嵌入，多图按叙述顺序排列。
5. 已有 `generate_chart` 时不要手写 matplotlib/脚本画图，也不要用代码块伪表格冒充专业图。
