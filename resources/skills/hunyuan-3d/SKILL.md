---
name: hunyuan-3d
description: >-
  Tencent Hunyuan (混元) 3D: text/image/multiview to 3D, texture, reduce face,
  UV, auto-rig, motion, convert, and import. Use when the user mentions 混元,
  Hunyuan, or hunyuan_* tools.
metadata:
  category: hunyuan
  requires: hunyuan
---

# 混元3D

`read_skill` 后激活 `hunyuan` 工具包。鉴权为腾讯云 SecretId/SecretKey（设置「模型 → 混元」）；可用 `hunyuan_test_connection` 测连通（无余额接口）。

## 文/图生 3D

`hunyuan_text_to_3d_pro` / `hunyuan_image_to_3d_pro` / `hunyuan_multiview_to_3d_pro`（或 `*_rapid`）→ `hunyuan_wait_job(kind=...)` → `hunyuan_import_to_maya`。本地参考图用 `image_path`（转 ImageBase64）。

## 后处理串联

纹理/减面/UV/组件/绑骨的 3D 输入只接受公网 `file_url`，或 `input_job_id` + `input_job_kind` 取上一任务 `ResultFile3Ds.Url`。**不支持本地 FBX/GLB 直传**（无 COS 上传）。

## 绑骨与动作

- 绑骨：`hunyuan_auto_rig`（可选 `motion_type`，见 `hunyuan_list_motions`）→ wait → import
- 文生动作：`hunyuan_motion`；人物模板：`hunyuan_profile_to_3d` + `hunyuan_list_profile_templates`
- 格式：`hunyuan_convert(Format=FBX)` 为同步接口；导入优先 FBX

## 查询

查询/等待必须带 `kind`（pro / rapid / texture / reduce_face / part / uv / motion / auto_rig / profile）。
