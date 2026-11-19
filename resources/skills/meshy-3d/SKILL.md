---
name: meshy-3d
description: >-
  Meshy cloud AI 3D: text/image to 3D, remesh, texture, rig, and import to Maya.
  Use when the user mentions Meshy, meshy_rig, or Meshy convert/import.
metadata:
  category: meshy
  requires: meshy
---

# Meshy

`read_skill` 后激活 `meshy` 工具包。传权/对齐常需再 `activate_tool_pack("rigging")` 与 `export`。

## 绑骨导入流程

正确流程：`export_fbx(embed_textures=true)` → `meshy_convert` 成 GLB → `meshy_rig` → `meshy_import_to_maya`。

- **必须嵌入贴图**。只写外部贴图路径的 FBX 上传后贴图会丢失，绑骨导入必为白模；工具会拒绝无贴图的本地 GLB/FBX。
- **多材质角色**：头/身/发分贴图时，Meshy 绑骨常把材质压成 1 个并只留一张身体贴图。优先：合并仅用于生成权重 → 用 `transfer_skin_weights`（默认对齐 Armature+源网格并同步源 `bindPreMatrix`）拷回原始分件；或先烘焙单 atlas 再送 Meshy。即使当前帧在动画姿态也可直接 transfer。
- 骨架与原模型错位：先 `align_skinned_rig` 或 `transfer_skin_weights(align=true)`，**不要只移动网格或只移动骨骼**；对齐后保持。
- 导入后若提示无贴图，不要先改材质网络，应重新按上面流程导出并转换。
- 不要把关节 translate 清零（绑定姿态依赖关节位移）；复位姿态只清 rotate。

## 通用云端纪律

执行前查余额并估算消耗，等用户确认；失败先尝试恢复任务；导入 Maya 并附材质才算完成。
