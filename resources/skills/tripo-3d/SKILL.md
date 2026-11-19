---
name: tripo-3d
description: >-
  Tripo cloud AI 3D: text/image/multiview to model, texture, rig, retarget,
  animation apply, and import. Use when the user mentions Tripo or tripo_* tools.
metadata:
  category: tripo
  requires: tripo
---

# Tripo

`read_skill` 后激活 `tripo` 工具包。原分件传权可能还需 `rigging` pack。

## 通用

- 执行前先 `tripo_balance`，估算消耗并请用户确认。
- 本地文件需先上传（工具会自动 `tripo_upload_file`）；任务用 `tripo_wait_task` 轮询。
- 导入优先 FBX；非 FBX 时 `tripo_import_to_maya` 会尝试自动 convert。

## 文/图生 3D

`tripo_text_to_model` / `tripo_image_to_model` / `tripo_multiview_to_model` →（可选）`tripo_texture` / `tripo_mesh_decimate` → `tripo_convert(format=FBX)` → `tripo_import_to_maya`。

图像链路可先 `tripo_text_to_image` / `tripo_image_to_multiview`，再用输出 task_id 或本地图接图生 3D。

## 绑骨 + 预设动画（原分件角色）

1. 多网格须先 `tripo_prepare_rig_export`（合并副本+可缩贴图）再 `tripo_rig_check` → `tripo_rig(out_format=fbx)`
2. `tripo_retarget`（默认 `animate_in_place=true`；预设见 `tripo_list_animations`）
3. `tripo_import_to_maya`（看 `scale_warning` / `frame_range`）
4. 需要原分件贴图时：`tripo_apply_to_meshes`（对齐+传权；尺度不匹配会跳过 bindPreMatrix sync）
5. `tripo_apply_animation`（默认只拷旋转；禁止拷肢体 translate）

## 禁止

- 手写 `xform -m` / worldMatrix 迁动画
- 源网格非单位尺度时对原分件盲同步 `bindPreMatrix`
- 用临时 `execute_python` 代替上述 apply 工具
